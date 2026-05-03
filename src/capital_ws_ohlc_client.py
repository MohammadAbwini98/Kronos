from __future__ import annotations

import asyncio
import logging
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import orjson
import pandas as pd
import websockets

from capital_auth import CapitalAuthenticator
from config import BridgeSettings, WS_URL, safe_epic_for_filename, validate_resolution
from kronos_mapper import KRONOS_COLUMNS, KronosMappingError, ws_ohlc_to_kronos_row
from prediction_store import insert_raw_market_event, upsert_live_quote, upsert_ohlcv_df

LOGGER = logging.getLogger(__name__)


class CapitalWebSocketError(RuntimeError):
    """Raised for Capital.com WebSocket failures."""


class CapitalOhlcWebSocketClient:
    def __init__(
        self,
        settings: BridgeSettings,
        authenticator: CapitalAuthenticator,
        epic: str,
        resolution: str,
        symbol: str | None = None,
        price_side: str = "mid",
        postgres_dsn: str | None = None,
        max_rows: int = 512,
        heartbeat_callback: Callable[[str, dict[str, Any]], None] | None = None,
        heartbeat_interval_seconds: int = 60,
        subscribe_quotes: bool = True,
    ) -> None:
        self.settings = settings
        self.authenticator = authenticator
        self.epic = epic
        self.symbol = symbol or epic
        self.price_side = price_side
        self.postgres_dsn = postgres_dsn
        self.heartbeat_callback = heartbeat_callback
        self.heartbeat_interval_seconds = max(1, heartbeat_interval_seconds)
        self.subscribe_quotes = subscribe_quotes
        self.keepalive_seconds = max(60, int(os.getenv("CAPITAL_WS_KEEPALIVE_SECONDS", "300")))
        self._last_heartbeat_at = 0.0
        self.resolution = validate_resolution(resolution)
        self.max_rows = max_rows
        self.events_path = settings.output_dir / f"ws_ohlc_events_{safe_epic_for_filename(epic)}_{self.resolution}.jsonl"
        self.csv_path = settings.output_dir / f"kronos_stream_input_{safe_epic_for_filename(epic)}_{self.resolution}.csv"
        self.df = pd.DataFrame(columns=KRONOS_COLUMNS)
        self._running = False
        # CSV write-buffer: avoid full-frame rewrite on every incoming candle.
        self._csv_write_pending: int = 0
        self._csv_write_interval: int = max(1, int(os.getenv("WS_CSV_WRITE_INTERVAL", "5")))

    async def stream_forever(self) -> None:
        tokens = self.authenticator.tokens or self.authenticator.authenticate()
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        async with websockets.connect(WS_URL, ping_interval=None, close_timeout=5) as websocket:
            if self.subscribe_quotes:
                await websocket.send(orjson.dumps(self._quote_subscription_payload(tokens.cst, tokens.security_token)).decode())
            await websocket.send(orjson.dumps(self._ohlc_subscription_payload(tokens.cst, tokens.security_token)).decode())
            LOGGER.info("Subscribed to quote%s stream for %s %s", " and OHLC" if self.subscribe_quotes else "", self.epic, self.resolution)
            keepalive_task = asyncio.create_task(self._keepalive(websocket))
            try:
                async for message in websocket:
                    await self._handle_message(message)
                    if not self._running:
                        break
            finally:
                keepalive_task.cancel()
                await self._unsubscribe(websocket)

    async def stop(self) -> None:
        self._running = False

    def _quote_subscription_payload(self, cst: str, security_token: str) -> dict[str, Any]:
        return {
            "destination": "marketData.subscribe",
            "correlationId": "quote-1",
            "cst": cst,
            "securityToken": security_token,
            "payload": {"epics": [self.epic]},
        }

    def _quote_unsubscribe_payload(self, cst: str, security_token: str) -> dict[str, Any]:
        return {
            "destination": "marketData.unsubscribe",
            "correlationId": "quote-unsub-1",
            "cst": cst,
            "securityToken": security_token,
            "payload": {"epics": [self.epic]},
        }

    def _ohlc_subscription_payload(self, cst: str, security_token: str) -> dict[str, Any]:
        return {
            "destination": "OHLCMarketData.subscribe",
            "correlationId": "ohlc-1",
            "cst": cst,
            "securityToken": security_token,
            "payload": {"epics": [self.epic], "resolutions": [self.resolution], "type": "classic"},
        }

    def _ohlc_unsubscribe_payload(self, cst: str, security_token: str) -> dict[str, Any]:
        return {
            "destination": "OHLCMarketData.unsubscribe",
            "correlationId": "ohlc-unsub-1",
            "cst": cst,
            "securityToken": security_token,
            "payload": {"epics": [self.epic], "resolutions": [self.resolution], "types": ["classic"]},
        }

    async def _unsubscribe(self, websocket: websockets.WebSocketClientProtocol) -> None:
        tokens = self.authenticator.tokens
        if tokens is None:
            return
        try:
            if self.subscribe_quotes:
                await websocket.send(orjson.dumps(self._quote_unsubscribe_payload(tokens.cst, tokens.security_token)).decode())
            await websocket.send(orjson.dumps(self._ohlc_unsubscribe_payload(tokens.cst, tokens.security_token)).decode())
            LOGGER.info("Unsubscribed from OHLC stream for %s %s", self.epic, self.resolution)
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup on shutdown.
            LOGGER.warning("WebSocket unsubscribe failed during shutdown: %s", exc)

    async def _keepalive(self, websocket: websockets.WebSocketClientProtocol) -> None:
        while True:
            await asyncio.sleep(self.keepalive_seconds)
            tokens = self.authenticator.tokens
            if tokens is None:
                continue
            payload = {
                "destination": "ping",
                "correlationId": "ping-1",
                "cst": tokens.cst,
                "securityToken": tokens.security_token,
            }
            try:
                await websocket.send(orjson.dumps(payload).decode())
            except Exception as exc:  # noqa: BLE001
                raise CapitalWebSocketError("WebSocket keepalive failed") from exc

    async def _handle_message(self, message: str | bytes) -> None:
        event = orjson.loads(message)
        destination = str(event.get("destination", ""))
        if event.get("status") == "ERROR":
            raise CapitalWebSocketError(f"Capital.com WebSocket error: {event}")
        payload = event.get("payload", {})
        if destination.lower() == "quote":
            await self._handle_quote(event, payload)
            return
        if destination.lower() == "ping":
            self._heartbeat_if_due(
                {
                    "timestamps": pd.Timestamp.now(tz="UTC").isoformat(),
                    "close": None,
                },
                state="keepalive",
            )
            return
        if "ohlc" not in destination.lower():
            LOGGER.debug("Ignoring non-OHLC WebSocket message: %s", destination or event.keys())
            return
        self._append_jsonl(event, self.events_path)
        raw_timestamp = self._normalized_event_timestamp_utc(payload)
        insert_raw_market_event(
            symbol=self.symbol,
            epic=self.epic,
            event_type=destination or "ohlc",
            payload=event,
            event_timestamp_utc=raw_timestamp,
            dsn=self.postgres_dsn,
        )
        try:
            row = ws_ohlc_to_kronos_row(payload)
        except KronosMappingError as exc:
            LOGGER.debug("Skipping OHLC payload that cannot be mapped yet: %s", exc)
            return
        LOGGER.info(
            "OHLC %s %s close=%s at %s",
            payload.get("epic", self.epic),
            payload.get("resolution", self.resolution),
            row["close"],
            row["timestamps"],
        )
        self._append_row(row)

    async def _handle_quote(self, event: dict[str, Any], payload: dict[str, Any]) -> None:
        self._append_jsonl(event, self.events_path)
        quote_timestamp = self._normalized_event_timestamp_utc(payload)
        insert_raw_market_event(
            symbol=self.symbol,
            epic=self.epic,
            event_type="quote",
            payload=event,
            event_timestamp_utc=quote_timestamp,
            dsn=self.postgres_dsn,
        )
        quote = upsert_live_quote(
            symbol=self.symbol,
            epic=self.epic,
            payload=payload,
            dsn=self.postgres_dsn,
        )
        LOGGER.debug(
            "QUOTE %s bid=%s ask=%s price=%s at %s",
            payload.get("epic", self.epic),
            quote.get("bid"),
            quote.get("ask"),
            quote.get("price"),
            quote.get("timestamp_utc") or quote.get("updated_at"),
        )
        self._heartbeat_if_due(
            {
                "timestamps": quote.get("timestamp_utc") or quote.get("updated_at"),
                "close": quote.get("price"),
            },
            state="streaming_quote",
        )

    @staticmethod
    def _normalized_event_timestamp_utc(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        raw_value = payload.get("timestamp") or payload.get("t") or payload.get("T") or payload.get("utm") or payload.get("UTM")
        if raw_value in (None, ""):
            return None
        try:
            if isinstance(raw_value, (int, float)):
                numeric = int(raw_value)
                unit = "ms" if abs(numeric) > 10_000_000_000 else "s"
                return pd.to_datetime(numeric, unit=unit, utc=True).isoformat()

            text = str(raw_value).strip()
            if text.isdigit():
                numeric = int(text)
                unit = "ms" if abs(numeric) > 10_000_000_000 else "s"
                return pd.to_datetime(numeric, unit=unit, utc=True).isoformat()

            return pd.to_datetime(text, utc=True).isoformat()
        except Exception:  # noqa: BLE001
            LOGGER.debug("Unable to normalize websocket timestamp value: %r", raw_value, exc_info=True)
            return None

    @staticmethod
    def _append_jsonl(event: dict[str, Any], path: Path) -> None:
        with path.open("ab") as handle:
            handle.write(orjson.dumps(event))
            handle.write(b"\n")

    def _append_row(self, row: dict[str, Any]) -> None:
        new_df = pd.DataFrame([row], columns=KRONOS_COLUMNS)
        self.df = pd.concat([self.df, new_df], ignore_index=True)
        self.df["timestamps"] = pd.to_datetime(self.df["timestamps"], utc=True)
        self.df = (
            self.df.sort_values("timestamps")
            .drop_duplicates("timestamps", keep="last")
            .tail(self.max_rows)
            .reset_index(drop=True)
        )
        self._csv_write_pending += 1
        if self._csv_write_pending >= self._csv_write_interval:
            self.df.to_csv(self.csv_path, index=False)
            self._csv_write_pending = 0
        upsert_ohlcv_df(
            pd.DataFrame([row], columns=KRONOS_COLUMNS),
            symbol=self.symbol,
            epic=self.epic,
            resolution=self.resolution,
            price_side=self.price_side,
            source="websocket_ohlc",
            dsn=self.postgres_dsn,
        )
        self._heartbeat_if_due(row, state="streaming_ohlc")

    def _heartbeat_if_due(self, row: dict[str, Any], *, state: str = "streaming") -> None:
        if self.heartbeat_callback is None:
            return
        now = time.monotonic()
        if self._last_heartbeat_at and (now - self._last_heartbeat_at) < self.heartbeat_interval_seconds:
            return
        self._last_heartbeat_at = now
        self.heartbeat_callback(
            "OK",
            {
                "state": "streaming",
                "stream_state": state,
                "epic": self.epic,
                "resolution": self.resolution,
                "symbol": self.symbol,
                "last_candle_timestamp_utc": str(row.get("timestamps")),
                "last_close": self._jsonable_number(row.get("close")),
            },
        )

    @staticmethod
    def _jsonable_number(value: Any) -> float | int | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (float, int)):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
