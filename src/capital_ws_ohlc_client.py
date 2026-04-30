from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import orjson
import pandas as pd
import websockets

from capital_auth import CapitalAuthenticator
from config import BridgeSettings, WS_URL, safe_epic_for_filename, validate_resolution
from kronos_mapper import KRONOS_COLUMNS, ws_ohlc_to_kronos_row
from prediction_store import insert_raw_market_event, upsert_ohlcv_df

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
    ) -> None:
        self.settings = settings
        self.authenticator = authenticator
        self.epic = epic
        self.symbol = symbol or epic
        self.price_side = price_side
        self.postgres_dsn = postgres_dsn
        self.resolution = validate_resolution(resolution)
        self.max_rows = max_rows
        self.events_path = settings.output_dir / f"ws_ohlc_events_{safe_epic_for_filename(epic)}_{self.resolution}.jsonl"
        self.csv_path = settings.output_dir / f"kronos_stream_input_{safe_epic_for_filename(epic)}_{self.resolution}.csv"
        self.df = pd.DataFrame(columns=KRONOS_COLUMNS)
        self._running = False

    async def stream_forever(self) -> None:
        tokens = self.authenticator.tokens or self.authenticator.authenticate()
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        async with websockets.connect(WS_URL, ping_interval=60, ping_timeout=20) as websocket:
            await websocket.send(orjson.dumps(self._subscription_payload(tokens.cst, tokens.security_token)).decode())
            LOGGER.info("Subscribed to OHLC stream for %s %s", self.epic, self.resolution)
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

    def _subscription_payload(self, cst: str, security_token: str) -> dict[str, Any]:
        return {
            "destination": "OHLCMarketData.subscribe",
            "correlationId": "ohlc-1",
            "cst": cst,
            "securityToken": security_token,
            "payload": {"epics": [self.epic], "resolutions": [self.resolution], "type": "classic"},
        }

    def _unsubscribe_payload(self, cst: str, security_token: str) -> dict[str, Any]:
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
            await websocket.send(orjson.dumps(self._unsubscribe_payload(tokens.cst, tokens.security_token)).decode())
            LOGGER.info("Unsubscribed from OHLC stream for %s %s", self.epic, self.resolution)
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup on shutdown.
            LOGGER.warning("WebSocket unsubscribe failed during shutdown: %s", exc)

    async def _keepalive(self, websocket: websockets.WebSocketClientProtocol) -> None:
        while True:
            await asyncio.sleep(60)
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
                await websocket.ping()
                await websocket.send(orjson.dumps(payload).decode())
            except Exception as exc:  # noqa: BLE001
                raise CapitalWebSocketError("WebSocket keepalive failed") from exc

    async def _handle_message(self, message: str | bytes) -> None:
        event = orjson.loads(message)
        destination = str(event.get("destination", ""))
        if event.get("status") == "ERROR":
            raise CapitalWebSocketError(f"Capital.com WebSocket error: {event}")
        if "ohlc" not in destination.lower() and not {"t", "o", "h", "l", "c"}.issubset(event.get("payload", {}).keys()):
            LOGGER.debug("Ignoring non-OHLC WebSocket message: %s", destination or event.keys())
            return
        payload = event.get("payload", {})
        row = ws_ohlc_to_kronos_row(payload)
        LOGGER.info(
            "OHLC %s %s close=%s at %s",
            payload.get("epic", self.epic),
            payload.get("resolution", self.resolution),
            row["close"],
            row["timestamps"],
        )
        self._append_jsonl(event, self.events_path)
        insert_raw_market_event(
            symbol=self.symbol,
            epic=self.epic,
            event_type=destination or "ohlc",
            payload=event,
            event_timestamp_utc=str(row["timestamps"]),
            dsn=self.postgres_dsn,
        )
        self._append_row(row)

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
        self.df.to_csv(self.csv_path, index=False)
        upsert_ohlcv_df(
            pd.DataFrame([row], columns=KRONOS_COLUMNS),
            symbol=self.symbol,
            epic=self.epic,
            resolution=self.resolution,
            price_side=self.price_side,
            source="websocket_ohlc",
            dsn=self.postgres_dsn,
        )
