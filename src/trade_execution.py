from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

import requests
from psycopg.errors import UniqueViolation

from config import DEMO_BASE_URL, ConfigError, TradeExecutionSettings, load_trade_execution_settings
from db import connect
from logging_utils import log_event, safe_log_dict


LOGGER = logging.getLogger(__name__)

ACTIONABLE_SIGNAL_TO_DIRECTION = {
    "LONG": "BUY",
    "BUY": "BUY",
    "SHORT": "SELL",
    "SELL": "SELL",
}
EXECUTABLE_SIGNAL_DECISIONS = {"LONG", "SHORT"}
ALLOWED_LONG_VALIDATION_STATUSES = {"LONG", "STRONG_LONG"}
ALLOWED_SHORT_VALIDATION_STATUSES = {"SHORT", "STRONG_SHORT"}
ALLOWED_EXECUTION_VALIDATION_STATUSES = ALLOWED_LONG_VALIDATION_STATUSES | ALLOWED_SHORT_VALIDATION_STATUSES
BLOCKED_EXECUTION_VALIDATION_STATUSES = {
    "BLOCKED",
    "HOLD",
    "WATCH",
    "VALIDATION_UNAVAILABLE",
    "WEAK_LONG",
    "WEAK_SHORT",
    "NEEDS_MORE_SAMPLES",
    "UNKNOWN",
}
DIRECTION_TO_ORDER_DIRECTION = {
    "UP": "BUY",
    "BULLISH": "BUY",
    "DOWN": "SELL",
    "BEARISH": "SELL",
}
NON_ACTIONABLE_SIGNALS = {"HOLD", "NO_TRADE", "WATCH", "BLOCKED", "VALIDATION_UNAVAILABLE", "VALIDATION_DISABLED"}
OPENISH_TRADE_STATUSES = {"PENDING", "SUBMITTED", "OPEN", "CLOSE_REQUESTED"}
RETRYABLE_STATUS_CODES = {401, 408, 425, 429, 500, 502, 503, 504}


class TradeExecutionError(RuntimeError):
    """Base error for broker execution failures."""


class TradeValidationError(TradeExecutionError):
    """Raised when a signal fails execution policy validation."""


class RetryableTradeExecutionError(TradeExecutionError):
    """Raised when a broker operation should be retried by the queue."""


class MarketNotTradeableError(RetryableTradeExecutionError):
    """Raised when the broker market is temporarily closed or not tradeable."""


class CapitalTradingApiError(TradeExecutionError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload

    @property
    def retryable(self) -> bool:
        return self.status_code in RETRYABLE_STATUS_CODES


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, default=_json_default)


def _normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def _parse_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return _utc_now()
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _parse_utc_optional(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        return _parse_utc(value)
    except Exception:
        return None


def _raw_execution_signal(candidate: "ExecutionCandidate") -> str:
    raw_signal = str(candidate.metadata.get("raw_signal") or "").strip().upper()
    if raw_signal:
        return raw_signal
    if candidate.direction == "BUY":
        return "LONG"
    if candidate.direction == "SELL":
        return "SHORT"
    return str(candidate.direction or "").strip().upper()


def _direction_from_validation_status(status: str) -> str | None:
    normalized = str(status or "").strip().upper()
    if normalized in {"LONG", "STRONG_LONG", "WEAK_LONG"}:
        return "LONG"
    if normalized in {"SHORT", "STRONG_SHORT", "WEAK_SHORT"}:
        return "SHORT"
    return None


@dataclass(frozen=True)
class ExecutionCandidate:
    signal_id: str
    run_id: str | None
    source_model: str
    symbol: str
    epic: str
    timeframe: str
    direction: str
    recommended_entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    confidence: Decimal
    generated_at_utc: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        raw_signal = str(self.metadata.get("raw_signal") or "").strip().upper()
        if raw_signal:
            return raw_signal in EXECUTABLE_SIGNAL_DECISIONS
        return self.direction in {"BUY", "SELL"}


@dataclass(frozen=True)
class CapitalAccount:
    account_id: str
    account_name: str
    status: str
    currency: str = "USD"
    preferred: bool = False
    is_demo: bool | None = None
    balance: Decimal = Decimal("0")
    available: Decimal = Decimal("0")
    profit_loss: Decimal = Decimal("0")
    equity: Decimal = Decimal("0")
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapitalMarketInfo:
    epic: str
    symbol: str
    instrument_name: str
    currency: str
    tradeable: bool
    bid: Decimal
    offer: Decimal
    decimal_places: int
    min_deal_size: Decimal
    min_size_increment: Decimal
    min_stop_or_profit_distance: Decimal
    min_stop_or_profit_distance_unit: str
    market_status: str = ""


@dataclass(frozen=True)
class ExecutionPlan:
    candidate: ExecutionCandidate
    account: CapitalAccount
    market: CapitalMarketInfo
    size: Decimal
    market_entry: Decimal
    stop_level: Decimal
    profit_level: Decimal
    validation_note: str


@dataclass(frozen=True)
class ExecutionDecision:
    signal_id: str
    raw_signal: str
    validation_status: str | None
    validation_score: Decimal | None
    validation_age_seconds: Decimal | None
    expected_move_pct: Decimal | None
    spread_pct: Decimal | None
    estimated_fee_pct: Decimal
    estimated_slippage_pct: Decimal
    safety_margin_pct: Decimal
    net_expected_edge_pct: Decimal | None
    execution_decision: str
    block_reason: str | None
    evaluated_at: datetime
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    status: str
    executed_trade_id: int | None = None
    deal_reference: str | None = None
    deal_id: str | None = None
    failure_reason: str | None = None
    error_details: str | None = None
    retry_requested: bool = False
    message: str = ""


class CapitalAccountSelectionPolicy:
    @staticmethod
    def resolve_required_demo_account(
        accounts: list[CapitalAccount],
        required_account_name: str,
        *,
        is_demo_environment: bool,
    ) -> CapitalAccount:
        if not is_demo_environment:
            raise ConfigError("Capital demo account selection requires the demo API environment.")

        enabled = [a for a in accounts if a.status.upper() == "ENABLED"]
        matches = [a for a in enabled if a.account_name == required_account_name]
        if not matches:
            raise TradeValidationError(f"Required Capital demo account {required_account_name!r} was not found.")
        if len(matches) > 1:
            raise TradeValidationError(f"Multiple enabled accounts named {required_account_name!r}; refusing ambiguous execution.")
        target = matches[0]
        if target.is_demo is False:
            raise TradeValidationError(
                f"Capital account {target.account_name!r} resolved as a live/real account."
            )
        if target.is_demo is None:
            target = replace(target, is_demo=True)
        return target


class CapitalTradingClient:
    def __init__(
        self,
        settings: TradeExecutionSettings | None = None,
        http: requests.Session | None = None,
    ) -> None:
        self.settings = settings or load_trade_execution_settings()
        self.settings.ensure_demo_base_url()
        self.http = http or requests.Session()
        self.base_url = _normalize_base_url(self.settings.api_base_url)
        self._tokens: tuple[str, str, float] | None = None
        self._auth_lock = threading.Lock()
        self._account_lock = threading.Lock()
        self._active_account: CapitalAccount | None = None

    @property
    def is_demo_environment(self) -> bool:
        return self.base_url == DEMO_BASE_URL

    def _authenticate_locked(self, *, force: bool = False) -> tuple[str, str]:
        self.settings.ensure_demo_base_url()
        self.settings.ensure_credentials()
        if self._tokens and not force and time.time() - self._tokens[2] < 60 * 60 * 4:
            return self._tokens[0], self._tokens[1]

        log_event(LOGGER, logging.INFO, "capital.trading.auth.start", base_url=self.base_url)
        response = self.http.post(
            f"{self.base_url}/session",
            json={
                "identifier": self.settings.identifier,
                "password": self.settings.password,
                "encryptedPassword": False,
            },
            headers={"X-CAP-API-KEY": self.settings.api_key},
            timeout=20,
        )
        if response.status_code >= 400:
            raise CapitalTradingApiError(
                f"Capital.com authentication failed with HTTP {response.status_code}",
                status_code=response.status_code,
                payload=response.text,
            )
        cst = response.headers.get("CST")
        security_token = response.headers.get("X-SECURITY-TOKEN")
        if not cst or not security_token:
            raise CapitalTradingApiError("Capital.com authentication did not return CST and X-SECURITY-TOKEN headers.")
        self._tokens = (cst, security_token, time.time())
        log_event(LOGGER, logging.INFO, "capital.trading.auth.success", base_url=self.base_url)
        return cst, security_token

    def authenticate(self, *, force: bool = False) -> tuple[str, str]:
        with self._auth_lock:
            return self._authenticate_locked(force=force)

    def _auth_headers(self) -> dict[str, str]:
        cst, security_token = self.authenticate()
        return {
            "X-CAP-API-KEY": self.settings.api_key,
            "CST": cst,
            "X-SECURITY-TOKEN": security_token,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        self.settings.ensure_demo_base_url()
        url = f"{self.base_url}{path}"
        log_event(
            LOGGER,
            logging.INFO,
            "capital.trading.request.start",
            method=method,
            path=path,
            payload_summary=safe_log_dict(json_body or {}),
        )
        response = self.http.request(method, url, json=json_body, headers=self._auth_headers(), timeout=30)
        if response.status_code == 401 and retry_auth:
            with self._auth_lock:
                self._tokens = None
                self._authenticate_locked(force=True)
            response = self.http.request(method, url, json=json_body, headers=self._auth_headers(), timeout=30)
        if response.status_code == 404 and path.startswith("/confirms/"):
            raise CapitalTradingApiError("Capital deal confirmation is not available yet.", status_code=404, payload=response.text)
        if response.status_code >= 400:
            raise CapitalTradingApiError(
                f"Capital.com HTTP {response.status_code} for {path}: {response.text}",
                status_code=response.status_code,
                payload=response.text,
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise CapitalTradingApiError(f"Capital.com returned non-JSON response for {path}") from exc

    def get_accounts(self) -> list[CapitalAccount]:
        data = self._request("GET", "/accounts")
        return [self._map_account(row) for row in data.get("accounts", [])]

    def ensure_demo_ready(self) -> CapitalAccount:
        self.settings.ensure_demo_base_url()
        if not self.is_demo_environment:
            raise ConfigError("Capital trading is allowed only against the demo API base URL.")
        with self._account_lock:
            if self._active_account is not None:
                return self._active_account
            accounts = self.get_accounts()
            account = CapitalAccountSelectionPolicy.resolve_required_demo_account(
                accounts,
                self.settings.demo_account_name,
                is_demo_environment=self.is_demo_environment,
            )
            if not account.preferred:
                self._request("PUT", "/session", json_body={"accountId": account.account_id})
                accounts = self.get_accounts()
                account = CapitalAccountSelectionPolicy.resolve_required_demo_account(
                    accounts,
                    self.settings.demo_account_name,
                    is_demo_environment=self.is_demo_environment,
                )
                if not account.preferred:
                    raise TradeValidationError(f"Capital account {account.account_name!r} was not activated by PUT /session.")
            self._active_account = account
            return account

    def get_account_snapshot(self) -> CapitalAccount:
        return self.ensure_demo_ready()

    def get_market_info(self, epic: str) -> CapitalMarketInfo:
        data = self._request("GET", f"/markets/{quote(epic, safe='')}")
        instrument = data.get("instrument") or {}
        snapshot = data.get("snapshot") or {}
        rules = data.get("dealingRules") or {}
        market_status = str(snapshot.get("marketStatus") or data.get("marketStatus") or "").upper()
        return CapitalMarketInfo(
            epic=str(instrument.get("epic") or epic),
            symbol=str(instrument.get("symbol") or epic),
            instrument_name=str(instrument.get("name") or epic),
            currency=str(instrument.get("currency") or "USD"),
            tradeable=market_status == "TRADEABLE",
            market_status=market_status,
            bid=_to_decimal(snapshot.get("bid") or data.get("bid")),
            offer=_to_decimal(snapshot.get("offer") or data.get("offer")),
            decimal_places=int(snapshot.get("decimalPlacesFactor") or 2),
            min_deal_size=_to_decimal((rules.get("minDealSize") or {}).get("value"), Decimal("1")),
            min_size_increment=_to_decimal((rules.get("minSizeIncrement") or {}).get("value"), Decimal("1")),
            min_stop_or_profit_distance=_to_decimal((rules.get("minStopOrProfitDistance") or {}).get("value")),
            min_stop_or_profit_distance_unit=str((rules.get("minStopOrProfitDistance") or {}).get("unit") or ""),
        )

    def place_position(self, plan: ExecutionPlan) -> dict[str, Any]:
        payload = {
            "epic": plan.candidate.epic,
            "direction": plan.candidate.direction,
            "size": float(plan.size),
            "guaranteedStop": False,
            "trailingStop": False,
            "stopLevel": float(plan.stop_level),
            "profitLevel": float(plan.profit_level),
        }
        result = self._request("POST", "/positions", json_body=payload)
        deal_reference = result.get("dealReference")
        if not deal_reference:
            raise CapitalTradingApiError("POST /positions did not return dealReference.", payload=result)
        return {"dealReference": deal_reference, "payload": result}

    def confirm_deal(self, deal_reference: str) -> dict[str, Any]:
        return self._request("GET", f"/confirms/{quote(deal_reference, safe='')}")

    def get_open_positions(self) -> list[dict[str, Any]]:
        self.ensure_demo_ready()
        data = self._request("GET", "/positions")
        return list(data.get("positions") or [])

    def get_activity_history(self, *, last_period_seconds: int = 86400, deal_id: str | None = None) -> list[dict[str, Any]]:
        self.ensure_demo_ready()
        path = f"/history/activity?lastPeriod={max(60, int(last_period_seconds))}&detailed=true"
        if deal_id:
            path += f"&dealId={quote(deal_id, safe='')}"
        data = self._request("GET", path)
        return list(data.get("activities") or [])

    def get_transaction_history(
        self,
        *,
        last_period_seconds: int = 86400,
        transaction_type: str | None = "TRADE",
        from_utc: datetime | None = None,
        to_utc: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_demo_ready()
        params: dict[str, str | int] = {}
        if from_utc and to_utc:
            params["from"] = self._format_capital_history_time(from_utc)
            params["to"] = self._format_capital_history_time(to_utc)
        else:
            params["lastPeriod"] = max(60, min(86400, int(last_period_seconds)))
        if transaction_type:
            params["type"] = transaction_type
        data = self._request("GET", f"/history/transactions?{urlencode(params)}")
        return list(data.get("transactions") or [])

    def close_position(self, deal_id: str) -> dict[str, Any]:
        self.ensure_demo_ready()
        result = self._request("DELETE", f"/positions/{quote(deal_id, safe='')}")
        deal_reference = result.get("dealReference")
        if not deal_reference:
            raise CapitalTradingApiError("DELETE /positions/{dealId} did not return dealReference.", payload=result)
        return {"dealReference": deal_reference, "payload": result}

    @staticmethod
    def _infer_demo_flag(row: dict[str, Any]) -> bool | None:
        for key in ("isDemo", "demo"):
            if key in row and row[key] is not None:
                return bool(row[key])
        text = " ".join(str(row.get(key) or "") for key in ("accountType", "accountCategory", "type", "environment"))
        if "demo" in text.lower() or "practice" in text.lower():
            return True
        if "live" in text.lower() or "real" in text.lower():
            return False
        return None

    @staticmethod
    def _format_capital_history_time(value: datetime) -> str:
        normalized = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.replace(tzinfo=None, microsecond=0).isoformat()

    @classmethod
    def _map_account(cls, row: dict[str, Any]) -> CapitalAccount:
        balance = row.get("balance") or {}
        bal = _to_decimal(balance.get("balance"))
        pnl = _to_decimal(balance.get("profitLoss"))
        return CapitalAccount(
            account_id=str(row.get("accountId") or "").strip(),
            account_name=str(row.get("accountName") or "").strip(),
            status=str(row.get("status") or "").strip(),
            currency=str(row.get("currency") or "USD"),
            preferred=bool(row.get("preferred")),
            is_demo=cls._infer_demo_flag(row),
            balance=bal,
            available=_to_decimal(balance.get("available")),
            profit_loss=pnl,
            equity=bal + pnl,
            raw_payload=row,
        )


class TradeExecutionRepository:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn

    def candidate_from_signal(self, signal_id: str) -> ExecutionCandidate | None:
        with connect(self.dsn) as conn:
            row = conn.execute(
                """
                SELECT
                    s.signal_id, s.run_id, s.symbol, s.epic, s.resolution, s.timestamp_utc,
                    s.signal, s.direction, s.confidence, s.expected_move_pct, s.cost_threshold_pct,
                    s.entry_price, s.tp_price, s.sl_price,
                    s.reason, s.validation_status, s.validation_score, s.validation_summary,
                    s.updated_at AS signal_updated_at,
                    svr.updated_at AS validation_updated_at,
                    svr.final_signal AS validation_final_signal,
                    svr.blocked AS validation_blocked,
                    svr.block_reason AS validation_block_reason,
                    svr.reason_codes AS validation_reason_codes,
                    svr.net_edge_pct AS validation_net_edge_pct,
                    r.model_name, r.model_path, r.tokenizer_path, r.generated_at_utc, r.metadata_path
                FROM signals s
                JOIN prediction_runs r ON r.run_id = s.run_id
                LEFT JOIN signal_validation_runs svr ON svr.run_id = s.run_id
                WHERE s.signal_id = %s OR s.run_id = %s
                ORDER BY s.timestamp_utc DESC
                LIMIT 1
                """,
                (signal_id, signal_id),
            ).fetchone()
        return self._candidate_from_row(dict(row)) if row else None

    def latest_candidate(self, *, symbol: str = "ETHUSD", resolution: str | None = None) -> ExecutionCandidate | None:
        params: list[Any] = [symbol]
        where = ["s.symbol = %s"]
        if resolution:
            where.append("s.resolution = %s")
            params.append(resolution)
        with connect(self.dsn) as conn:
            row = conn.execute(
                f"""
                SELECT
                    s.signal_id, s.run_id, s.symbol, s.epic, s.resolution, s.timestamp_utc,
                    s.signal, s.direction, s.confidence, s.expected_move_pct, s.cost_threshold_pct,
                    s.entry_price, s.tp_price, s.sl_price,
                    s.reason, s.validation_status, s.validation_score, s.validation_summary,
                    s.updated_at AS signal_updated_at,
                    svr.updated_at AS validation_updated_at,
                    svr.final_signal AS validation_final_signal,
                    svr.blocked AS validation_blocked,
                    svr.block_reason AS validation_block_reason,
                    svr.reason_codes AS validation_reason_codes,
                    svr.net_edge_pct AS validation_net_edge_pct,
                    r.model_name, r.model_path, r.tokenizer_path, r.generated_at_utc, r.metadata_path
                FROM signals s
                JOIN prediction_runs r ON r.run_id = s.run_id
                LEFT JOIN signal_validation_runs svr ON svr.run_id = s.run_id
                WHERE {" AND ".join(where)}
                ORDER BY s.timestamp_utc DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        return self._candidate_from_row(dict(row)) if row else None

    def upsert_candidate(self, candidate: ExecutionCandidate) -> int:
        with connect(self.dsn) as conn:
            row = conn.execute(
                """
                INSERT INTO trade_execution_candidates(
                    signal_id, run_id, source_model, symbol, epic, timeframe, direction,
                    recommended_entry, stop_loss, take_profit, confidence, generated_at_utc, metadata, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
                ON CONFLICT(signal_id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    source_model = EXCLUDED.source_model,
                    symbol = EXCLUDED.symbol,
                    epic = EXCLUDED.epic,
                    timeframe = EXCLUDED.timeframe,
                    direction = EXCLUDED.direction,
                    recommended_entry = EXCLUDED.recommended_entry,
                    stop_loss = EXCLUDED.stop_loss,
                    take_profit = EXCLUDED.take_profit,
                    confidence = EXCLUDED.confidence,
                    generated_at_utc = EXCLUDED.generated_at_utc,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                RETURNING id
                """,
                (
                    candidate.signal_id,
                    candidate.run_id,
                    candidate.source_model,
                    candidate.symbol,
                    candidate.epic,
                    candidate.timeframe,
                    candidate.direction,
                    candidate.recommended_entry,
                    candidate.stop_loss,
                    candidate.take_profit,
                    candidate.confidence,
                    candidate.generated_at_utc,
                    _json_dumps(candidate.metadata),
                ),
            ).fetchone()
        return int(row["id"])

    def get_trade_by_signal(self, signal_id: str) -> dict[str, Any] | None:
        with connect(self.dsn) as conn:
            row = conn.execute("SELECT * FROM executed_trades WHERE signal_id = %s", (signal_id,)).fetchone()
        return dict(row) if row else None

    def get_trade_by_id(self, trade_id: int) -> dict[str, Any] | None:
        with connect(self.dsn) as conn:
            row = conn.execute("SELECT * FROM executed_trades WHERE id = %s", (trade_id,)).fetchone()
        return dict(row) if row else None

    def insert_or_get_pending_trade(self, candidate: ExecutionCandidate, candidate_id: int, plan: ExecutionPlan) -> int:
        spread = abs(plan.market.offer - plan.market.bid)
        mid = (plan.market.offer + plan.market.bid) / Decimal("2") if (plan.market.offer + plan.market.bid) > 0 else Decimal("0")
        entry_spread_pct = (spread / mid * Decimal("100")) if mid > 0 else None
        spread_cost = spread * plan.size if spread > 0 else None
        slippage_estimate = abs((plan.market_entry or Decimal("0")) - (candidate.recommended_entry or Decimal("0"))) * plan.size
        validation_score = None if candidate.metadata.get("validation_score") in (None, "") else _to_decimal(candidate.metadata.get("validation_score"))
        expected_move_pct = None if candidate.metadata.get("expected_move_pct") in (None, "") else _to_decimal(candidate.metadata.get("expected_move_pct"))
        with connect(self.dsn) as conn:
            try:
                row = conn.execute(
                    """
                    INSERT INTO executed_trades(
                        signal_id, candidate_id, run_id, source_model, symbol, epic, timeframe, direction,
                        requested_size, recommended_entry, stop_loss, take_profit, status,
                        account_id, account_name, is_demo, entry_price, spread_cost, slippage_estimate,
                        validation_status_at_execution, validation_score_at_execution,
                        expected_move_pct_at_execution, entry_spread_pct, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING',
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    RETURNING id
                    """,
                    (
                        candidate.signal_id,
                        candidate_id,
                        candidate.run_id,
                        candidate.source_model,
                        candidate.symbol,
                        candidate.epic,
                        candidate.timeframe,
                        candidate.direction,
                        plan.size,
                        candidate.recommended_entry,
                        plan.stop_level,
                        plan.profit_level,
                        plan.account.account_id,
                        plan.account.account_name,
                        plan.account.is_demo,
                        plan.market_entry,
                        spread_cost,
                        slippage_estimate,
                        candidate.metadata.get("validation_status"),
                        validation_score,
                        expected_move_pct,
                        entry_spread_pct,
                    ),
                ).fetchone()
                return int(row["id"])
            except UniqueViolation:
                conn.rollback()
                row = conn.execute("SELECT id FROM executed_trades WHERE signal_id = %s", (candidate.signal_id,)).fetchone()
                return int(row["id"])

    def update_trade(self, trade_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = _utc_now()
        names = list(fields)
        values = [fields[name] for name in names]
        set_sql = ", ".join(f"{name} = %s::jsonb" if name == "broker_payload" else f"{name} = %s" for name in names)
        with connect(self.dsn) as conn:
            conn.execute(f"UPDATE executed_trades SET {set_sql} WHERE id = %s", (*values, trade_id))

    def insert_attempt(
        self,
        *,
        trade_id: int | None,
        signal_id: str,
        stage: str,
        success: bool,
        summary: str | None = None,
        error_details: str | None = None,
        broker_payload: Any = None,
    ) -> None:
        with connect(self.dsn) as conn:
            conn.execute(
                """
                INSERT INTO trade_execution_attempts(
                    executed_trade_id, signal_id, stage, success, summary, error_details, broker_payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (trade_id, signal_id, stage, success, summary, error_details, _json_dumps(broker_payload)),
            )

    def insert_event(self, *, trade_id: int | None, signal_id: str, event_type: str, message: str, payload: Any = None) -> None:
        with connect(self.dsn) as conn:
            conn.execute(
                """
                INSERT INTO trade_execution_events(executed_trade_id, signal_id, event_type, message, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (trade_id, signal_id, event_type, message, _json_dumps(payload)),
            )

    def record_execution_decision(self, decision: ExecutionDecision) -> None:
        details = dict(decision.details or {})
        with connect(self.dsn) as conn:
            conn.execute(
                """
                INSERT INTO trade_execution_decisions(
                    signal_id, raw_signal, validation_status, validation_score, validation_age_seconds,
                    expected_move_pct, spread_pct, estimated_fee_pct, estimated_slippage_pct, safety_margin_pct,
                    net_expected_edge_pct, execution_decision, block_reason, evaluated_at, details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    decision.signal_id,
                    decision.raw_signal,
                    decision.validation_status,
                    decision.validation_score,
                    decision.validation_age_seconds,
                    decision.expected_move_pct,
                    decision.spread_pct,
                    decision.estimated_fee_pct,
                    decision.estimated_slippage_pct,
                    decision.safety_margin_pct,
                    decision.net_expected_edge_pct,
                    decision.execution_decision,
                    decision.block_reason,
                    decision.evaluated_at,
                    _json_dumps(details),
                ),
            )
            conn.execute(
                """
                UPDATE trade_execution_candidates
                SET last_execution_decision = %s,
                    last_block_reason = %s,
                    last_decision_at = %s,
                    execution_decision_details = %s::jsonb,
                    updated_at = now()
                WHERE signal_id = %s
                """,
                (
                    decision.execution_decision,
                    decision.block_reason,
                    decision.evaluated_at,
                    _json_dumps(
                        {
                            **details,
                            "raw_signal": decision.raw_signal,
                            "validation_status": decision.validation_status,
                            "validation_score": decision.validation_score,
                            "validation_age_seconds": decision.validation_age_seconds,
                            "expected_move_pct": decision.expected_move_pct,
                            "spread_pct": decision.spread_pct,
                            "estimated_fee_pct": decision.estimated_fee_pct,
                            "estimated_slippage_pct": decision.estimated_slippage_pct,
                            "safety_margin_pct": decision.safety_margin_pct,
                            "net_expected_edge_pct": decision.net_expected_edge_pct,
                            "execution_decision": decision.execution_decision,
                            "block_reason": decision.block_reason,
                            "evaluated_at": decision.evaluated_at,
                        }
                    ),
                    decision.signal_id,
                ),
            )
        log_event(
            LOGGER,
            logging.INFO if decision.execution_decision == "ALLOW" else logging.WARNING,
            "trade.execution.decision",
            signal_id=decision.signal_id,
            raw_signal=decision.raw_signal,
            validation_status=decision.validation_status,
            validation_score=float(decision.validation_score) if decision.validation_score is not None else None,
            validation_age_seconds=float(decision.validation_age_seconds)
            if decision.validation_age_seconds is not None
            else None,
            expected_move_pct=float(decision.expected_move_pct) if decision.expected_move_pct is not None else None,
            spread_pct=float(decision.spread_pct) if decision.spread_pct is not None else None,
            net_expected_edge_pct=float(decision.net_expected_edge_pct) if decision.net_expected_edge_pct is not None else None,
            execution_decision=decision.execution_decision,
            block_reason=decision.block_reason,
        )

    def enqueue(
        self,
        candidate: ExecutionCandidate,
        *,
        requested_by: str = "auto",
        requested_size: Decimal | None = None,
        force_market_execution: bool = False,
    ) -> dict[str, Any]:
        candidate_id = self.upsert_candidate(candidate)
        existing_trade = self.get_trade_by_signal(candidate.signal_id)
        if existing_trade and str(existing_trade.get("status") or "").upper() not in {"FAILED", "REJECTED", "VALIDATION_FAILED"}:
            return {
                "accepted": False,
                "status": existing_trade.get("status"),
                "executed_trade_id": existing_trade.get("id"),
                "failure_reason": "DuplicateExecution",
                "message": f"Signal {candidate.signal_id} already has execution record {existing_trade.get('id')}.",
            }
        with connect(self.dsn) as conn:
            try:
                row = conn.execute(
                    """
                    INSERT INTO trade_execution_queue(
                        signal_id, candidate_id, requested_by, requested_size, force_market_execution, status, next_attempt_at
                    )
                    VALUES (%s, %s, %s, %s, %s, 'QUEUED', now())
                    RETURNING id, status
                    """,
                    (candidate.signal_id, candidate_id, requested_by, requested_size, bool(force_market_execution)),
                ).fetchone()
            except UniqueViolation:
                conn.rollback()
                row = conn.execute(
                    """
                    SELECT id, status, executed_trade_id
                    FROM trade_execution_queue
                    WHERE signal_id = %s AND status IN ('QUEUED', 'PROCESSING')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (candidate.signal_id,),
                ).fetchone()
        return {
            "accepted": True,
            "queue_entry_id": int(row["id"]),
            "status": row["status"],
            "message": f"Signal {candidate.signal_id} queued for Capital.com demo execution.",
        }

    def claim_next_queue_entry(self) -> dict[str, Any] | None:
        with connect(self.dsn) as conn:
            row = conn.execute(
                """
                UPDATE trade_execution_queue q
                SET status = 'PROCESSING', updated_at = now(), attempt_count = attempt_count + 1
                WHERE q.id = (
                    SELECT id
                    FROM trade_execution_queue
                    WHERE status = 'QUEUED' AND next_attempt_at <= now()
                    ORDER BY created_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING q.*
                """
            ).fetchone()
        return dict(row) if row else None

    def get_candidate_by_id(self, candidate_id: int) -> ExecutionCandidate | None:
        with connect(self.dsn) as conn:
            row = conn.execute("SELECT * FROM trade_execution_candidates WHERE id = %s", (candidate_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        return ExecutionCandidate(
            signal_id=str(data["signal_id"]),
            run_id=data.get("run_id"),
            source_model=str(data.get("source_model") or "Kronos"),
            symbol=str(data["symbol"]),
            epic=str(data["epic"]),
            timeframe=str(data["timeframe"]),
            direction=str(data["direction"]).upper(),
            recommended_entry=_to_decimal(data.get("recommended_entry")),
            stop_loss=_to_decimal(data.get("stop_loss")),
            take_profit=_to_decimal(data.get("take_profit")),
            confidence=_to_decimal(data.get("confidence")),
            generated_at_utc=_parse_utc(data.get("generated_at_utc")),
            metadata=dict(data.get("metadata") or {}),
        )

    def complete_queue_entry(self, queue_entry_id: int, result: ExecutionResult) -> None:
        with connect(self.dsn) as conn:
            conn.execute(
                """
                UPDATE trade_execution_queue
                SET status = 'COMPLETED',
                    executed_trade_id = %s,
                    failure_reason = %s,
                    error_details = %s,
                    updated_at = now(),
                    processed_at = now()
                WHERE id = %s
                """,
                (result.executed_trade_id, result.failure_reason, result.error_details or result.message, queue_entry_id),
            )

    def fail_or_retry_queue_entry(self, queue_entry: dict[str, Any], result: ExecutionResult) -> None:
        retry = result.retry_requested and (
            result.failure_reason == "MarketNotTradeableError" or int(queue_entry.get("attempt_count") or 0) < 5
        )
        status = "QUEUED" if retry else "FAILED"
        delay_seconds = 300 if result.failure_reason == "MarketNotTradeableError" else min(60, 2 ** max(0, int(queue_entry.get("attempt_count") or 1)))
        with connect(self.dsn) as conn:
            conn.execute(
                """
                UPDATE trade_execution_queue
                SET status = %s,
                    executed_trade_id = %s,
                    failure_reason = %s,
                    error_details = %s,
                    next_attempt_at = now() + (%s || ' seconds')::interval,
                    updated_at = now(),
                    processed_at = CASE WHEN %s = 'FAILED' THEN now() ELSE NULL END
                WHERE id = %s
                """,
                (
                    status,
                    result.executed_trade_id,
                    result.failure_reason,
                    result.error_details or result.message,
                    delay_seconds,
                    status,
                    queue_entry["id"],
                ),
            )

    def save_account_snapshot(self, account: CapitalAccount, *, open_positions: int = 0) -> None:
        with connect(self.dsn) as conn:
            conn.execute(
                """
                INSERT INTO broker_account_snapshots(
                    account_id, account_name, is_demo, currency, balance, available,
                    profit_loss, equity, open_positions, raw_payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    account.account_id,
                    account.account_name,
                    bool(account.is_demo),
                    account.currency,
                    account.balance,
                    account.available,
                    account.profit_loss,
                    account.equity,
                    open_positions,
                    _json_dumps(account.raw_payload),
                ),
            )

    def queue_snapshot(self, limit: int = 50) -> dict[str, Any]:
        with connect(self.dsn) as conn:
            counts = conn.execute(
                "SELECT status, COUNT(*)::int AS count FROM trade_execution_queue GROUP BY status"
            ).fetchall()
            entries = conn.execute(
                """
                SELECT
                    q.*,
                    c.symbol,
                    c.epic,
                    c.direction,
                    c.confidence,
                    c.recommended_entry,
                    c.stop_loss,
                    c.take_profit,
                    s.status AS signal_status,
                    s.signal AS signal_label,
                    s.validation_status,
                    d.execution_decision,
                    d.block_reason AS execution_block_reason,
                    d.evaluated_at AS execution_decision_at,
                    d.details AS execution_decision_details,
                    d.net_expected_edge_pct AS execution_net_expected_edge_pct,
                    d.spread_pct AS execution_spread_pct
                FROM trade_execution_queue q
                LEFT JOIN trade_execution_candidates c ON c.id = q.candidate_id
                LEFT JOIN signals s ON s.signal_id = q.signal_id
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM trade_execution_decisions ted
                    WHERE ted.signal_id = q.signal_id
                    ORDER BY ted.evaluated_at DESC, ted.id DESC
                    LIMIT 1
                ) d ON true
                ORDER BY q.updated_at DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return {
            "counts": {str(row["status"]).lower(): int(row["count"]) for row in counts},
            "entries": [dict(row) for row in entries],
        }

    def executed_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        with connect(self.dsn) as conn:
            rows = conn.execute(
                """
                SELECT
                    e.*,
                    s.status AS signal_status,
                    s.signal AS signal_label,
                    s.validation_status,
                    d.execution_decision,
                    d.block_reason AS execution_block_reason,
                    d.evaluated_at AS execution_decision_at,
                    d.details AS execution_decision_details,
                    d.net_expected_edge_pct AS execution_net_expected_edge_pct,
                    d.spread_pct AS execution_spread_pct
                FROM executed_trades e
                LEFT JOIN signals s ON s.signal_id = e.signal_id
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM trade_execution_decisions ted
                    WHERE ted.signal_id = e.signal_id
                    ORDER BY ted.evaluated_at DESC, ted.id DESC
                    LIMIT 1
                ) d ON true
                ORDER BY e.updated_at DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def execution_decisions(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.dsn) as conn:
            rows = conn.execute(
                """
                SELECT
                    d.*,
                    c.symbol,
                    c.epic,
                    c.direction,
                    c.confidence,
                    c.recommended_entry,
                    c.stop_loss,
                    c.take_profit,
                    s.status AS signal_status,
                    s.signal AS signal_label,
                    s.validation_status AS signal_validation_status
                FROM trade_execution_decisions d
                LEFT JOIN trade_execution_candidates c ON c.signal_id = d.signal_id
                LEFT JOIN signals s ON s.signal_id = d.signal_id
                ORDER BY d.evaluated_at DESC, d.id DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def open_trade_count(self, account: CapitalAccount) -> int:
        with connect(self.dsn) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)::int AS count
                FROM executed_trades
                WHERE account_id = %s AND account_name = %s AND is_demo = true AND status IN ('PENDING', 'SUBMITTED', 'OPEN', 'CLOSE_REQUESTED')
                """,
                (account.account_id, account.account_name),
            ).fetchone()
        return int(row["count"] if row else 0)

    def daily_trade_count(self, account: CapitalAccount) -> int:
        with connect(self.dsn) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)::int AS count
                FROM executed_trades
                WHERE account_id = %s AND account_name = %s AND is_demo = true AND created_at >= date_trunc('day', now())
                  AND status NOT IN ('VALIDATION_FAILED')
                """,
                (account.account_id, account.account_name),
            ).fetchone()
        return int(row["count"] if row else 0)

    def daily_loss(self, account: CapitalAccount) -> Decimal:
        with connect(self.dsn) as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(ABS(COALESCE(actual_entry, 0) - COALESCE(recommended_entry, 0)) * COALESCE(executed_size, requested_size, 0)), 0) AS loss
                FROM executed_trades
                WHERE account_id = %s AND account_name = %s AND is_demo = true
                  AND created_at >= date_trunc('day', now())
                  AND status = 'LOSS'
                """,
                (account.account_id, account.account_name),
            ).fetchone()
        return _to_decimal(row["loss"] if row else 0)

    def reconciliation_trades(self, limit: int = 250) -> list[dict[str, Any]]:
        with connect(self.dsn) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM executed_trades
                WHERE status IN ('SUBMITTED', 'OPEN', 'CLOSE_REQUESTED')
                   OR (status = 'CLOSED' AND closed_at >= now() - interval '24 hours')
                ORDER BY updated_at
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _candidate_from_row(row: dict[str, Any]) -> ExecutionCandidate:
        raw_signal = str(row.get("signal") or row.get("direction") or "").upper()
        raw_direction = str(row.get("direction") or "").upper()
        if raw_signal in EXECUTABLE_SIGNAL_DECISIONS:
            direction = ACTIONABLE_SIGNAL_TO_DIRECTION[raw_signal]
        elif raw_signal:
            direction = "NO_TRADE"
        else:
            direction = ACTIONABLE_SIGNAL_TO_DIRECTION.get(
                raw_direction,
                DIRECTION_TO_ORDER_DIRECTION.get(raw_direction, "NO_TRADE"),
            )
        configured_epic = row.get("epic")
        validation_summary = row.get("validation_summary") or {}
        validation_status = row.get("validation_status") or row.get("validation_final_signal")
        validation_updated_at = row.get("validation_updated_at") or (validation_summary or {}).get("updated_at")
        metadata = {
            "reason": row.get("reason"),
            "validation_status": validation_status,
            "validation_score": row.get("validation_score"),
            "validation_summary": validation_summary,
            "validation_updated_at": validation_updated_at,
            "signal_updated_at": row.get("signal_updated_at"),
            "validation_blocked": row.get("validation_blocked"),
            "validation_block_reason": row.get("validation_block_reason"),
            "validation_reason_codes": row.get("validation_reason_codes"),
            "validation_net_edge_pct": row.get("validation_net_edge_pct"),
            "expected_move_pct": row.get("expected_move_pct"),
            "cost_threshold_pct": row.get("cost_threshold_pct"),
            "original_direction": raw_direction,
            "model_path": row.get("model_path"),
            "tokenizer_path": row.get("tokenizer_path"),
            "metadata_path": row.get("metadata_path"),
            "raw_signal": raw_signal,
        }
        return ExecutionCandidate(
            signal_id=str(row.get("signal_id") or row.get("run_id")),
            run_id=row.get("run_id"),
            source_model=str(row.get("model_name") or "Kronos"),
            symbol=str(row.get("symbol") or "ETHUSD"),
            epic=str(configured_epic or "ETHUSD"),
            timeframe=str(row.get("resolution") or ""),
            direction=str(direction or "NO_TRADE").upper(),
            recommended_entry=_to_decimal(row.get("entry_price")),
            stop_loss=_to_decimal(row.get("sl_price")),
            take_profit=_to_decimal(row.get("tp_price")),
            confidence=_to_decimal(row.get("confidence")),
            generated_at_utc=_parse_utc(row.get("timestamp_utc") or row.get("generated_at_utc")),
            metadata=metadata,
        )


class SymbolEpicMapper:
    def __init__(self, settings: TradeExecutionSettings) -> None:
        self.settings = settings

    def resolve(self, symbol: str, current_epic: str | None = None) -> str:
        if symbol.strip().upper() in {"ETH", "ETHUSD", "ETH/USD"}:
            return self.settings.capital_eth_epic
        return current_epic or symbol


class TradeExecutionPolicy:
    def __init__(
        self,
        settings: TradeExecutionSettings | None = None,
        client: CapitalTradingClient | None = None,
        repository: TradeExecutionRepository | None = None,
    ) -> None:
        self.settings = settings or load_trade_execution_settings()
        self.client = client or CapitalTradingClient(self.settings)
        self.repository = repository or TradeExecutionRepository()
        self.mapper = SymbolEpicMapper(self.settings)

    @staticmethod
    def _validation_timestamp(candidate: ExecutionCandidate) -> datetime | None:
        metadata = candidate.metadata or {}
        for key in ("validation_updated_at", "validation_evaluated_at", "validation_created_at"):
            parsed = _parse_utc_optional(metadata.get(key))
            if parsed is not None:
                return parsed
        summary = metadata.get("validation_summary") if isinstance(metadata.get("validation_summary"), dict) else {}
        for key in ("updated_at", "created_at", "evaluated_at"):
            parsed = _parse_utc_optional(summary.get(key))
            if parsed is not None:
                return parsed
        return None

    @classmethod
    def _validation_age_seconds(cls, candidate: ExecutionCandidate, now: datetime) -> Decimal | None:
        timestamp = cls._validation_timestamp(candidate)
        if timestamp is None:
            return None
        return Decimal(str(max(0.0, (now - timestamp).total_seconds())))

    @staticmethod
    def _metadata_quality_status(candidate: ExecutionCandidate) -> str:
        metadata = candidate.metadata or {}
        summary = metadata.get("validation_summary") if isinstance(metadata.get("validation_summary"), dict) else {}
        for key in ("forecast_quality_status", "quality_status", "actual_window_status", "validation_quality_status"):
            value = metadata.get(key) or summary.get(key)
            if value:
                return str(value).strip().upper()
        return ""

    @staticmethod
    def _market_regime_is_blocked(candidate: ExecutionCandidate) -> bool:
        metadata = candidate.metadata or {}
        summary = metadata.get("validation_summary") if isinstance(metadata.get("validation_summary"), dict) else {}
        if bool(metadata.get("market_regime_blocked") or metadata.get("regime_blocked") or summary.get("market_regime_blocked")):
            return True
        regime = str(metadata.get("market_regime_status") or metadata.get("market_regime") or summary.get("market_regime_status") or "").upper()
        return regime in {"BLOCKED", "INVALID", "EXTREME_VOLATILITY", "NO_TRADE"}

    @staticmethod
    def _volume_regime_is_invalid(candidate: ExecutionCandidate) -> bool:
        metadata = candidate.metadata or {}
        summary = metadata.get("validation_summary") if isinstance(metadata.get("validation_summary"), dict) else {}
        if bool(metadata.get("volume_regime_blocked") or summary.get("volume_regime_blocked")):
            return True
        regime = str(metadata.get("volume_regime_status") or metadata.get("volume_regime") or summary.get("volume_regime_status") or "").upper()
        return regime in {"", "MISSING", "UNKNOWN", "INVALID", "VERY_LOW_VOLUME", "BLOCKED", "NO_TRADE"}

    @classmethod
    def metadata_execution_block_reason(
        cls,
        candidate: ExecutionCandidate,
        settings: TradeExecutionSettings,
        *,
        now: datetime | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        now = now or _utc_now()
        raw_signal = _raw_execution_signal(candidate)
        validation_status = str(candidate.metadata.get("validation_status") or "").strip().upper()
        validation_score_raw = candidate.metadata.get("validation_score")
        expected_move_raw = candidate.metadata.get("expected_move_pct")
        details: dict[str, Any] = {
            "raw_signal": raw_signal,
            "direction": candidate.direction,
            "validation_status": validation_status or None,
            "min_validation_score": settings.min_validation_score,
            "min_confidence": settings.min_confidence,
            "min_expected_move_pct": settings.min_expected_move_pct,
            "max_validation_age_seconds": settings.max_validation_age_seconds,
            "heuristic_confidence_note": (
                "Signal confidence remains a heuristic display score. "
                "TODO: replace/augment execution confidence with calibrated rolling live-outcome probability."
            ),
        }

        if raw_signal not in EXECUTABLE_SIGNAL_DECISIONS:
            return "NON_ACTIONABLE_SIGNAL", details
        expected_direction = ACTIONABLE_SIGNAL_TO_DIRECTION[raw_signal]
        if candidate.direction != expected_direction:
            details["expected_direction"] = expected_direction
            return "RAW_SIGNAL_DIRECTION_MISMATCH", details

        validation_direction = _direction_from_validation_status(validation_status)
        if validation_direction and validation_direction != raw_signal:
            details["validation_direction"] = validation_direction
            return "RAW_SIGNAL_VALIDATION_DIRECTION_MISMATCH", details

        if validation_score_raw not in (None, ""):
            details["validation_score"] = _to_decimal(validation_score_raw)

        validation_age = cls._validation_age_seconds(candidate, now)
        details["validation_age_seconds"] = validation_age
        if validation_age is not None and validation_age > Decimal(str(settings.max_validation_age_seconds)):
            return "STALE_VALIDATION", details

        quality_status = cls._metadata_quality_status(candidate)
        if quality_status:
            details["forecast_quality_status"] = quality_status
        if quality_status in {"NEEDS_MORE_SAMPLES", "PARTIAL_PROGRESS"}:
            return "FORECAST_QUALITY_NEEDS_MORE_SAMPLES", details

        if expected_move_raw in (None, ""):
            return "EXPECTED_MOVE_MISSING", details
        expected_move_pct = abs(_to_decimal(expected_move_raw))
        details["expected_move_pct"] = expected_move_pct
        if expected_move_pct <= Decimal(str(settings.min_expected_move_pct)):
            return "NEAR_ZERO_PREDICTED_MOVE", details

        if cls._market_regime_is_blocked(candidate):
            return "MARKET_REGIME_BLOCKED", details
        if settings.require_valid_volume_regime and cls._volume_regime_is_invalid(candidate):
            return "VOLUME_REGIME_INVALID", details

        return None, details

    @staticmethod
    def _spread_pct(market: CapitalMarketInfo) -> Decimal | None:
        if market.bid <= 0 or market.offer <= 0 or market.offer < market.bid:
            return None
        mid = (market.bid + market.offer) / Decimal("2")
        if mid <= 0:
            return None
        return (abs(market.offer - market.bid) / mid) * Decimal("100")

    def _record_decision(
        self,
        candidate: ExecutionCandidate,
        *,
        execution_decision: str,
        block_reason: str | None,
        raw_signal: str | None = None,
        validation_status: str | None = None,
        validation_age_seconds: Decimal | None = None,
        expected_move_pct: Decimal | None = None,
        spread_pct: Decimal | None = None,
        net_expected_edge_pct: Decimal | None = None,
        details: dict[str, Any] | None = None,
    ) -> ExecutionDecision:
        raw_signal = raw_signal or _raw_execution_signal(candidate)
        validation_status = validation_status if validation_status is not None else str(candidate.metadata.get("validation_status") or "").strip().upper() or None
        validation_score = None
        if candidate.metadata.get("validation_score") not in (None, ""):
            validation_score = _to_decimal(candidate.metadata.get("validation_score"))
        if validation_age_seconds is None:
            validation_age_seconds = self._validation_age_seconds(candidate, _utc_now())
        if expected_move_pct is None and candidate.metadata.get("expected_move_pct") not in (None, ""):
            expected_move_pct = abs(_to_decimal(candidate.metadata.get("expected_move_pct")))
        decision = ExecutionDecision(
            signal_id=candidate.signal_id,
            raw_signal=raw_signal,
            validation_status=validation_status,
            validation_score=validation_score,
            validation_age_seconds=validation_age_seconds,
            expected_move_pct=expected_move_pct,
            spread_pct=spread_pct,
            estimated_fee_pct=Decimal(str(self.settings.estimated_fee_pct)),
            estimated_slippage_pct=Decimal(str(self.settings.estimated_slippage_pct)),
            safety_margin_pct=Decimal(str(self.settings.execution_safety_margin_pct)),
            net_expected_edge_pct=net_expected_edge_pct,
            execution_decision=execution_decision,
            block_reason=block_reason,
            evaluated_at=_utc_now(),
            details=details or {},
        )
        recorder = getattr(self.repository, "record_execution_decision", None)
        if callable(recorder):
            recorder(decision)
        return decision

    def _block(
        self,
        candidate: ExecutionCandidate,
        reason: str,
        *,
        details: dict[str, Any] | None = None,
        spread_pct: Decimal | None = None,
        net_expected_edge_pct: Decimal | None = None,
    ) -> None:
        self._record_decision(
            candidate,
            execution_decision="BLOCK",
            block_reason=reason,
            spread_pct=spread_pct,
            net_expected_edge_pct=net_expected_edge_pct,
            details=details,
        )
        raise TradeValidationError(reason)

    def evaluate(
        self,
        candidate: ExecutionCandidate,
        *,
        requested_size: Decimal | None = None,
        force_market_execution: bool = False,
    ) -> ExecutionPlan:
        now = _utc_now()
        if not candidate.is_actionable:
            self._block(candidate, "NON_ACTIONABLE_SIGNAL", details={"direction": candidate.direction})
        validation_status = str(candidate.metadata.get("validation_status") or "").strip().upper()
        metadata_block, metadata_details = self.metadata_execution_block_reason(candidate, self.settings, now=now)
        if metadata_block:
            self._block(candidate, metadata_block, details=metadata_details)
        age = now - candidate.generated_at_utc
        if age > timedelta(minutes=self.settings.stale_signal_minutes):
            self._block(
                candidate,
                "STALE_SIGNAL",
                details={**metadata_details, "signal_age_seconds": age.total_seconds()},
            )
        if candidate.recommended_entry <= 0 or candidate.stop_loss <= 0 or candidate.take_profit <= 0:
            self._block(candidate, "INVALID_SIGNAL_LEVELS", details=metadata_details)
        existing_trade = self.repository.get_trade_by_signal(candidate.signal_id)
        if existing_trade and str(existing_trade.get("status") or "").upper() not in {"FAILED", "REJECTED", "VALIDATION_FAILED"}:
            self._block(
                candidate,
                "DUPLICATE_EXECUTION",
                details={**metadata_details, "existing_trade_id": existing_trade.get("id"), "existing_trade_status": existing_trade.get("status")},
            )

        account = self.client.ensure_demo_ready()
        if account.is_demo is not True:
            raise TradeValidationError("Active Capital account is not a confirmed demo account.")
        epic = self.mapper.resolve(candidate.symbol, candidate.epic)
        mapped = ExecutionCandidate(**{**asdict(candidate), "epic": epic})
        market = self.client.get_market_info(epic)
        if not market.tradeable:
            status_note = f" status {market.market_status}" if market.market_status else ""
            self._record_decision(
                mapped,
                execution_decision="BLOCK",
                block_reason="MARKET_NOT_TRADEABLE",
                details={**metadata_details, "epic": epic, "market_status": market.market_status},
            )
            raise MarketNotTradeableError(f"Market {epic} is not TRADEABLE{status_note}.")
        spread_pct = self._spread_pct(market)
        expected_move_pct = abs(_to_decimal(mapped.metadata.get("expected_move_pct")))
        fee_pct = Decimal(str(self.settings.estimated_fee_pct))
        slippage_pct = Decimal(str(self.settings.estimated_slippage_pct))
        safety_margin_pct = Decimal(str(self.settings.execution_safety_margin_pct))
        if spread_pct is None:
            if self.settings.allow_missing_spread_demo_fallback:
                spread_pct = Decimal("0")
                metadata_details["missing_spread_demo_fallback"] = True
            else:
                self._block(mapped, "MISSING_SPREAD", details={**metadata_details, "epic": epic})
        if spread_pct > Decimal(str(self.settings.max_spread_pct)):
            self._block(
                mapped,
                "SPREAD_TOO_WIDE",
                details={**metadata_details, "max_spread_pct": self.settings.max_spread_pct},
                spread_pct=spread_pct,
            )
        required_edge_pct = spread_pct + fee_pct + slippage_pct + safety_margin_pct
        net_expected_edge_pct = expected_move_pct - required_edge_pct
        edge_details = {
            **metadata_details,
            "epic": epic,
            "expected_move_pct": expected_move_pct,
            "spread_pct": spread_pct,
            "estimated_fee_pct": fee_pct,
            "estimated_slippage_pct": slippage_pct,
            "safety_margin_pct": safety_margin_pct,
            "required_edge_pct": required_edge_pct,
            "net_expected_edge_pct": net_expected_edge_pct,
        }
        if not expected_move_pct > required_edge_pct:
            self._block(
                mapped,
                "INSUFFICIENT_NET_EDGE",
                details=edge_details,
                spread_pct=spread_pct,
                net_expected_edge_pct=net_expected_edge_pct,
            )
        market_entry = market.offer if mapped.direction == "BUY" else market.bid
        if market_entry <= 0:
            self._block(mapped, "INVALID_MARKET_ENTRY", details=edge_details, spread_pct=spread_pct, net_expected_edge_pct=net_expected_edge_pct)
        if not self._levels_are_directional(mapped.direction, market_entry, mapped.take_profit, mapped.stop_loss):
            if self._levels_are_directional(mapped.direction, mapped.recommended_entry, mapped.take_profit, mapped.stop_loss):
                mapped = self._reanchor_levels_for_market(mapped, market_entry)
            else:
                mapped = self._derive_levels_for_market(mapped, market_entry, market)
        else:
            mapped = self._mark_market_execution_entry(mapped, market_entry)
        mapped = self._enforce_broker_level_boundaries(mapped, market)

        size = self._normalize_size(requested_size or Decimal(str(self.settings.default_trade_size)), market)
        if size < market.min_deal_size:
            self._block(mapped, "SIZE_BELOW_MIN_DEAL_SIZE", details={**edge_details, "requested_size": size, "min_deal_size": market.min_deal_size}, spread_pct=spread_pct, net_expected_edge_pct=net_expected_edge_pct)
        if self.repository.open_trade_count(account) >= self.settings.max_concurrent_open_trades:
            self._block(mapped, "MAX_CONCURRENT_OPEN_TRADES", details=edge_details, spread_pct=spread_pct, net_expected_edge_pct=net_expected_edge_pct)
        if self.settings.max_daily_trades and self.repository.daily_trade_count(account) >= self.settings.max_daily_trades:
            self._block(mapped, "MAX_DAILY_TRADES", details=edge_details, spread_pct=spread_pct, net_expected_edge_pct=net_expected_edge_pct)
        if self.settings.max_daily_loss and self.repository.daily_loss(account) >= Decimal(str(self.settings.max_daily_loss)):
            self._block(mapped, "MAX_DAILY_LOSS", details=edge_details, spread_pct=spread_pct, net_expected_edge_pct=net_expected_edge_pct)

        decision = self._record_decision(
            mapped,
            execution_decision="ALLOW",
            block_reason=None,
            spread_pct=spread_pct,
            net_expected_edge_pct=net_expected_edge_pct,
            details=edge_details,
        )
        mapped = replace(
            mapped,
            metadata={
                **mapped.metadata,
                "execution_decision": decision.execution_decision,
                "execution_decision_details": edge_details,
            },
        )

        return ExecutionPlan(
            candidate=mapped,
            account=account,
            market=market,
            size=size,
            market_entry=market_entry,
            stop_level=self._round_price(mapped.stop_loss, market.decimal_places),
            profit_level=self._round_price(mapped.take_profit, market.decimal_places),
            validation_note=(
                "Execution candidate passed demo policy, broker, risk, and cost-aware edge checks. "
                f"Validation status {validation_status or 'UNSPECIFIED'} did not block by label alone; "
                f"net expected edge {net_expected_edge_pct:.6f}%."
            ),
        )

    @staticmethod
    def _levels_are_directional(direction: str, entry: Decimal, tp: Decimal, sl: Decimal) -> bool:
        return (direction == "BUY" and tp > entry and sl < entry) or (direction == "SELL" and tp < entry and sl > entry)

    @staticmethod
    def _price_tick(decimal_places: int) -> Decimal:
        if decimal_places <= 0:
            return Decimal("1")
        return Decimal("1").scaleb(-decimal_places)

    @classmethod
    def _minimum_level_distance(cls, market: CapitalMarketInfo, reference_price: Decimal) -> Decimal:
        distance = market.min_stop_or_profit_distance
        if distance <= 0:
            return Decimal("0")
        unit = str(market.min_stop_or_profit_distance_unit or "").strip().upper()
        if unit in {"PERCENT", "PERCENTAGE"}:
            return reference_price * (distance / Decimal("100"))
        return distance

    def _broker_level_buffer(self, market: CapitalMarketInfo) -> Decimal:
        tolerance = Decimal(str(self.settings.price_tolerance))
        capped_tolerance = min(tolerance, Decimal("0.1")) if tolerance > 0 else Decimal("0")
        return max(self._price_tick(market.decimal_places), capped_tolerance)

    def _enforce_broker_level_boundaries(
        self,
        candidate: ExecutionCandidate,
        market: CapitalMarketInfo,
    ) -> ExecutionCandidate:
        tick = self._price_tick(market.decimal_places)
        buffer = self._broker_level_buffer(market)
        stop_loss = candidate.stop_loss
        take_profit = candidate.take_profit
        metadata_updates: dict[str, Any] = {}

        if candidate.direction == "BUY":
            exit_reference = market.bid
            min_distance = self._minimum_level_distance(market, exit_reference)
            max_stop = exit_reference - min_distance - buffer
            min_profit = exit_reference + min_distance + buffer
            if stop_loss >= max_stop:
                metadata_updates["original_stop_loss_before_broker_boundary"] = str(stop_loss)
                stop_loss = max_stop
            if take_profit <= min_profit:
                metadata_updates["original_take_profit_before_broker_boundary"] = str(take_profit)
                take_profit = min_profit
        else:
            exit_reference = market.offer
            min_distance = self._minimum_level_distance(market, exit_reference)
            min_stop = exit_reference + min_distance + buffer
            max_profit = exit_reference - min_distance - buffer
            if stop_loss <= min_stop:
                metadata_updates["original_stop_loss_before_broker_boundary"] = str(stop_loss)
                stop_loss = min_stop
            if take_profit >= max_profit:
                metadata_updates["original_take_profit_before_broker_boundary"] = str(take_profit)
                take_profit = max_profit

        stop_loss = self._round_price(stop_loss, market.decimal_places)
        take_profit = self._round_price(take_profit, market.decimal_places)
        if candidate.direction == "BUY":
            stop_loss = min(stop_loss, max_stop - tick)
            take_profit = max(take_profit, min_profit + tick)
        else:
            stop_loss = max(stop_loss, min_stop + tick)
            take_profit = min(take_profit, max_profit - tick)

        if not metadata_updates:
            return candidate
        metadata_updates.update(
            {
                "broker_level_boundary_adjusted": True,
                "broker_level_reference": str(exit_reference),
                "broker_min_level_distance": str(min_distance),
                "broker_level_buffer": str(buffer),
                "broker_min_stop_or_profit_distance_unit": market.min_stop_or_profit_distance_unit,
            }
        )
        return replace(candidate, stop_loss=stop_loss, take_profit=take_profit, metadata={**candidate.metadata, **metadata_updates})

    @classmethod
    def _reanchor_levels_for_market(cls, candidate: ExecutionCandidate, market_entry: Decimal) -> ExecutionCandidate:
        if not cls._levels_are_directional(
            candidate.direction,
            candidate.recommended_entry,
            candidate.take_profit,
            candidate.stop_loss,
        ):
            raise TradeValidationError("Stop loss and take profit are not valid for the original signal entry.")
        stop_distance = abs(candidate.recommended_entry - candidate.stop_loss)
        profit_distance = abs(candidate.take_profit - candidate.recommended_entry)
        if stop_distance <= 0 or profit_distance <= 0:
            raise TradeValidationError("Stop loss and take profit distances must be positive.")
        if candidate.direction == "BUY":
            stop_loss = market_entry - stop_distance
            take_profit = market_entry + profit_distance
        else:
            stop_loss = market_entry + stop_distance
            take_profit = market_entry - profit_distance
        metadata = {
            **candidate.metadata,
            "manual_force_market_execution": True,
            "original_stop_loss": str(candidate.stop_loss),
            "original_take_profit": str(candidate.take_profit),
            "original_recommended_entry": str(candidate.recommended_entry),
        }
        return replace(candidate, recommended_entry=market_entry, stop_loss=stop_loss, take_profit=take_profit, metadata=metadata)

    @staticmethod
    def _mark_market_execution_entry(candidate: ExecutionCandidate, market_entry: Decimal) -> ExecutionCandidate:
        metadata = {
            **candidate.metadata,
            "original_recommended_entry": str(candidate.recommended_entry),
            "market_execution_entry": str(market_entry),
        }
        return replace(candidate, recommended_entry=market_entry, metadata=metadata)

    @classmethod
    def _derive_levels_for_market(
        cls,
        candidate: ExecutionCandidate,
        market_entry: Decimal,
        market: CapitalMarketInfo,
    ) -> ExecutionCandidate:
        expected_move_pct = abs(_to_decimal(candidate.metadata.get("expected_move_pct")))
        cost_threshold_pct = abs(_to_decimal(candidate.metadata.get("cost_threshold_pct"), Decimal("0.05")))
        level_pct = max(expected_move_pct, cost_threshold_pct, Decimal("0.05"))
        distance = market_entry * (level_pct / Decimal("100"))
        if market.min_stop_or_profit_distance > 0:
            distance = max(distance, market.min_stop_or_profit_distance)
        if distance <= 0:
            distance = max(Decimal("0.1"), market_entry * Decimal("0.0005"))
        if candidate.direction == "BUY":
            stop_loss = market_entry - distance
            take_profit = market_entry + distance
        else:
            stop_loss = market_entry + distance
            take_profit = market_entry - distance
        metadata = {
            **candidate.metadata,
            "execution_levels_derived": True,
            "original_stop_loss": str(candidate.stop_loss),
            "original_take_profit": str(candidate.take_profit),
            "derived_from_market_entry": str(market_entry),
            "derived_level_pct": str(level_pct),
        }
        return replace(candidate, recommended_entry=market_entry, stop_loss=stop_loss, take_profit=take_profit, metadata=metadata)

    @staticmethod
    def _normalize_size(size: Decimal, market: CapitalMarketInfo) -> Decimal:
        step = market.min_size_increment if market.min_size_increment > 0 else market.min_deal_size
        if step <= 0:
            return size
        steps = Decimal(math.ceil(float(size / step)))
        return steps * step

    @staticmethod
    def _round_price(price: Decimal, decimal_places: int) -> Decimal:
        if decimal_places < 0:
            return price
        quant = Decimal("1") if decimal_places == 0 else Decimal("1").scaleb(-decimal_places)
        return price.quantize(quant)


class TradeExecutionService:
    def __init__(
        self,
        settings: TradeExecutionSettings | None = None,
        client: CapitalTradingClient | None = None,
        repository: TradeExecutionRepository | None = None,
    ) -> None:
        self.settings = settings or load_trade_execution_settings()
        self.repository = repository or TradeExecutionRepository()
        self.client = client or CapitalTradingClient(self.settings)
        self.policy = TradeExecutionPolicy(self.settings, self.client, self.repository)

    def execute(
        self,
        candidate: ExecutionCandidate,
        *,
        requested_size: Decimal | None = None,
        force_market_execution: bool = False,
    ) -> ExecutionResult:
        existing = self.repository.get_trade_by_signal(candidate.signal_id)
        if existing and str(existing.get("status") or "").upper() not in {"FAILED", "REJECTED", "VALIDATION_FAILED"}:
            return ExecutionResult(
                success=True,
                status=str(existing.get("status")),
                executed_trade_id=int(existing["id"]),
                deal_reference=existing.get("deal_reference"),
                deal_id=existing.get("deal_id"),
                failure_reason="DuplicateExecution",
                message="Existing execution record returned; no duplicate order was submitted.",
        )
        trade_id: int | None = None
        plan: ExecutionPlan | None = None
        deal_reference: str | None = None
        try:
            plan = self.policy.evaluate(
                candidate,
                requested_size=requested_size,
                force_market_execution=force_market_execution,
            )
            candidate_id = self.repository.upsert_candidate(plan.candidate)
            self.repository.save_account_snapshot(plan.account, open_positions=len(self.client.get_open_positions()))
            trade_id = self.repository.insert_or_get_pending_trade(plan.candidate, candidate_id, plan)
            self.repository.insert_event(
                trade_id=trade_id,
                signal_id=plan.candidate.signal_id,
                event_type="execution_requested",
                message="Execution requested after policy approval.",
                payload={"epic": plan.candidate.epic, "direction": plan.candidate.direction, "size": plan.size},
            )
            log_event(
                LOGGER,
                logging.INFO,
                "trade.execution.place.start",
                signal_id=plan.candidate.signal_id,
                epic=plan.candidate.epic,
                direction=plan.candidate.direction,
                size=float(plan.size),
            )
            open_result = self.client.place_position(plan)
            deal_reference = str(open_result["dealReference"])
            self.repository.update_trade(
                trade_id,
                status="SUBMITTED",
                deal_reference=deal_reference,
                broker_payload=_json_dumps(open_result.get("payload")),
            )
            self.repository.insert_attempt(
                trade_id=trade_id,
                signal_id=plan.candidate.signal_id,
                stage="place_position",
                success=True,
                summary="Order submitted to Capital.com demo.",
                broker_payload=open_result.get("payload"),
            )
            try:
                confirm = self.client.confirm_deal(deal_reference)
            except CapitalTradingApiError as exc:
                if exc.status_code == 404 or exc.retryable:
                    self.repository.insert_event(
                        trade_id=trade_id,
                        signal_id=plan.candidate.signal_id,
                        event_type="execution_pending_confirmation",
                        message="Broker confirmation is not available yet; reconciliation will continue tracking.",
                        payload={"dealReference": deal_reference, "error": str(exc)},
                    )
                    return ExecutionResult(
                        success=True,
                        status="SUBMITTED",
                        executed_trade_id=trade_id,
                        deal_reference=deal_reference,
                        retry_requested=True,
                        message="Trade submitted and pending confirmation.",
                    )
                raise
            return self._apply_confirmation(trade_id, plan, deal_reference, confirm)
        except TradeValidationError as exc:
            trade_id = self._persist_validation_failure(candidate, str(exc))
            return ExecutionResult(
                success=False,
                status="VALIDATION_FAILED",
                executed_trade_id=trade_id,
                failure_reason=type(exc).__name__,
                error_details=str(exc),
                message=str(exc),
            )
        except RetryableTradeExecutionError as exc:
            self.repository.insert_event(
                trade_id=None,
                signal_id=candidate.signal_id,
                event_type="execution_retry_requested",
                message=str(exc),
                payload={"reason": type(exc).__name__},
            )
            return ExecutionResult(
                success=False,
                status="QUEUED",
                executed_trade_id=None,
                failure_reason=type(exc).__name__,
                error_details=str(exc),
                retry_requested=True,
                message=str(exc),
            )
        except CapitalTradingApiError as exc:
            retryable = exc.retryable
            broker_payload = {
                "status_code": exc.status_code,
                "payload": exc.payload,
                "message": str(exc),
            }
            failure_reason = "BrokerConfirmationFailed" if deal_reference else "BrokerExecutionFailed"
            if trade_id is not None:
                status = "SUBMITTED" if deal_reference else "FAILED"
                self.repository.update_trade(
                    trade_id,
                    status=status,
                    failure_reason=failure_reason,
                    broker_rejection_reason=str(exc),
                    broker_payload=_json_dumps(broker_payload),
                )
                self.repository.insert_attempt(
                    trade_id=trade_id,
                    signal_id=plan.candidate.signal_id if plan else candidate.signal_id,
                    stage="confirm_position" if deal_reference else "place_position",
                    success=False,
                    summary=failure_reason,
                    error_details=str(exc),
                    broker_payload=broker_payload,
                )
                self.repository.insert_event(
                    trade_id=trade_id,
                    signal_id=plan.candidate.signal_id if plan else candidate.signal_id,
                    event_type="broker_confirmation_failed" if deal_reference else "broker_execution_failed",
                    message=str(exc),
                    payload=broker_payload,
                )
            return ExecutionResult(
                success=False,
                status="SUBMITTED" if deal_reference else "FAILED",
                executed_trade_id=trade_id,
                deal_reference=deal_reference,
                failure_reason=failure_reason,
                error_details=str(exc),
                retry_requested=retryable or bool(deal_reference),
                message=str(exc),
            )

    def force_close(self, executed_trade_id: int) -> dict[str, Any]:
        trades = [row for row in self.repository.executed_trades(limit=500) if int(row["id"]) == int(executed_trade_id)]
        if not trades:
            return {"success": False, "message": "Executed trade not found."}
        trade = trades[0]
        if str(trade.get("status") or "").upper() != "OPEN":
            return {"success": False, "message": f"Trade status {trade.get('status')} is not force-closeable."}
        deal_id = trade.get("deal_id")
        if not deal_id:
            return {"success": False, "message": "Executed trade does not have a broker deal id."}
        self.repository.update_trade(executed_trade_id, status="CLOSE_REQUESTED")
        close_result = self.client.close_position(str(deal_id))
        confirm = self.client.confirm_deal(str(close_result["dealReference"]))
        accepted = str(confirm.get("dealStatus") or confirm.get("status") or "").upper() == "ACCEPTED"
        if accepted:
            self.repository.update_trade(
                executed_trade_id,
                status="CLOSED",
                closed_at=_utc_now(),
                close_reason="MANUAL_FORCE_CLOSE",
                final_outcome="UNKNOWN",
                outcome_finalized_at=_utc_now(),
            )
            self.repository.insert_event(
                trade_id=executed_trade_id,
                signal_id=str(trade["signal_id"]),
                event_type="force_closed",
                message="Trade force-closed successfully.",
                payload=confirm,
            )
            return {"success": True, "message": "Trade force-closed successfully.", "confirmation": confirm}
        self.repository.update_trade(
            executed_trade_id,
            status="CLOSE_FAILED",
            failure_reason=str(confirm.get("reason") or "CloseRejected"),
            broker_rejection_reason=str(confirm.get("reason") or ""),
        )
        return {"success": False, "message": "Close rejected by broker.", "confirmation": confirm}

    def fetch_transaction_reference(
        self,
        *,
        executed_trade_id: int | None = None,
        deal_id: str | None = None,
    ) -> dict[str, Any]:
        trade = self.repository.get_trade_by_id(executed_trade_id) if executed_trade_id is not None else None
        resolved_deal_id = str(deal_id or (trade or {}).get("deal_id") or "").strip()
        if not resolved_deal_id:
            return {
                "success": False,
                "message": "No dealId is available for this executed signal.",
                "transaction_id": None,
                "transaction": None,
                "transactions_checked": 0,
            }

        window_anchor = _parse_utc((trade or {}).get("opened_at") or (trade or {}).get("created_at")) if trade else None
        transactions = self._transaction_history_for_trade_window(window_anchor)
        match = self._match_transaction_for_trade(resolved_deal_id, trade or {}, transactions)
        if match is None and window_anchor is not None:
            transactions = self.client.get_transaction_history(last_period_seconds=86400, transaction_type="TRADE")
            match = self._match_transaction_for_trade(resolved_deal_id, trade or {}, transactions)

        transaction_id = self._transaction_identifier(match) if match else None
        result = {
            "success": bool(match),
            "message": (
                f"Capital.com transaction reference {transaction_id} found."
                if transaction_id
                else "No matching Capital.com transaction-history record was found for this dealId."
            ),
            "executed_trade_id": executed_trade_id,
            "deal_id": resolved_deal_id,
            "transaction_id": transaction_id,
            "transaction": match,
            "transactions_checked": len(transactions),
        }
        if trade:
            self.repository.insert_event(
                trade_id=int(trade["id"]),
                signal_id=str(trade["signal_id"]),
                event_type="transaction_history_lookup",
                message=result["message"],
                payload=result,
            )
        return result

    def enrich_transaction_references(
        self,
        trades: list[dict[str, Any]],
        *,
        transactions: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        enriched = [dict(trade) for trade in trades]
        trades_with_deals = [trade for trade in enriched if str(trade.get("deal_id") or "").strip()]
        if not trades_with_deals:
            return enriched

        transaction_rows = (
            transactions
            if transactions is not None
            else self.client.get_transaction_history(last_period_seconds=86400, transaction_type="TRADE")
        )
        for trade in trades_with_deals:
            deal_id = str(trade.get("deal_id") or "").strip()
            match = self._match_transaction_by_deal_id(deal_id, transaction_rows)
            transaction_id = self._transaction_identifier(match) if match else None
            trade["transaction_id"] = transaction_id
            trade["transaction_lookup_status"] = "FOUND" if transaction_id else "NOT_FOUND"
        return enriched

    def enrich_trade_outcomes(
        self,
        trades: list[dict[str, Any]],
        *,
        activities: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        enriched = [dict(trade) for trade in trades]
        closed_with_deals = [
            trade
            for trade in enriched
            if str(trade.get("deal_id") or "").strip() and str(trade.get("status") or "").upper() == "CLOSED"
        ]
        for trade in enriched:
            if str(trade.get("status") or "").upper() in {"OPEN", "PENDING", "SUBMITTED", "CLOSE_REQUESTED"}:
                trade["trade_outcome"] = "OPEN"
                trade["trade_outcome_reason"] = "Trade is not closed yet."
        if not closed_with_deals:
            return enriched

        activity_rows = activities if activities is not None else self.client.get_activity_history(last_period_seconds=86400)
        for trade in closed_with_deals:
            deal_id = str(trade.get("deal_id") or "").strip()
            close_activity = self._match_close_activity_by_deal_id(deal_id, activity_rows)
            outcome = self._trade_outcome_from_activity(trade, close_activity)
            trade.update(outcome)
        return enriched

    def _transaction_history_for_trade_window(self, window_anchor: datetime | None) -> list[dict[str, Any]]:
        if window_anchor is None:
            return self.client.get_transaction_history(last_period_seconds=86400, transaction_type="TRADE")
        now = _utc_now()
        from_utc = window_anchor - timedelta(minutes=10)
        to_utc = min(window_anchor + timedelta(minutes=10), now)
        if to_utc <= from_utc:
            return self.client.get_transaction_history(last_period_seconds=86400, transaction_type="TRADE")
        return self.client.get_transaction_history(
            transaction_type="TRADE",
            from_utc=from_utc,
            to_utc=to_utc,
        )

    @staticmethod
    def _transaction_identifier(transaction: dict[str, Any] | None) -> str | None:
        if not transaction:
            return None
        for key in ("transactionId", "transaction_id", "reference", "referenceId", "id"):
            value = transaction.get(key)
            if value not in (None, ""):
                return str(value)
        return None

    @classmethod
    def _match_transaction_for_trade(
        cls,
        deal_id: str,
        trade: dict[str, Any],
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        direct_match = cls._match_transaction_by_deal_id(deal_id, transactions)
        if direct_match:
            return direct_match

        trade_size = _to_decimal(trade.get("executed_size")) or _to_decimal(trade.get("requested_size"))
        trade_opened = _parse_utc(trade.get("opened_at") or trade.get("created_at")) if trade else None
        trade_symbols = {
            str(trade.get("epic") or "").replace("/", "").replace(" ", "").upper(),
            str(trade.get("symbol") or "").replace("/", "").replace(" ", "").upper(),
        } - {""}

        best: tuple[int, dict[str, Any]] | None = None
        for transaction in transactions:
            score = 0
            if str(transaction.get("transactionType") or "").upper() == "TRADE":
                score += 1
            transaction_size = _to_decimal(transaction.get("size"))
            if trade_size > 0 and transaction_size > 0 and abs(trade_size - transaction_size) <= Decimal("0.00000001"):
                score += 2
            transaction_symbol = str(transaction.get("instrumentName") or "").replace("/", "").replace(" ", "").upper()
            if transaction_symbol and any(symbol in transaction_symbol or transaction_symbol in symbol for symbol in trade_symbols):
                score += 1
            transaction_time = cls._transaction_time(transaction)
            if trade_opened and transaction_time:
                delta = abs((transaction_time - trade_opened).total_seconds())
                if delta <= 600:
                    score += 3
                elif delta <= 3600:
                    score += 1
            if score >= 5 and (best is None or score > best[0]):
                best = (score, transaction)
        return best[1] if best else None

    @staticmethod
    def _match_transaction_by_deal_id(
        deal_id: str,
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        deal_id_text = str(deal_id)
        for transaction in transactions:
            for key in ("dealId", "deal_id", "positionDealId", "positionId"):
                if str(transaction.get(key) or "") == deal_id_text:
                    return transaction
        return None

    @staticmethod
    def _transaction_time(transaction: dict[str, Any]) -> datetime | None:
        for key in ("dateUtc", "dateUTC", "date"):
            value = transaction.get(key)
            if value:
                try:
                    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                except Exception:
                    return None
        return None

    @classmethod
    def _match_close_activity_by_deal_id(
        cls,
        deal_id: str,
        activities: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        deal_id_text = str(deal_id)
        candidates: list[tuple[int, dict[str, Any]]] = []
        for activity in activities:
            if str(activity.get("dealId") or activity.get("deal_id") or "") != deal_id_text:
                continue
            status = str(activity.get("status") or "").upper()
            if status and status not in {"ACCEPTED", "EXECUTED", "PROCESSED"}:
                continue
            details = activity.get("details") or {}
            source = str(activity.get("source") or "").upper()
            activity_type = str(activity.get("type") or "").upper()
            score = 0
            if activity_type == "POSITION":
                score += 1
            if source in {"SL", "STOP", "STOP_LOSS", "TP", "TAKE_PROFIT", "PROFIT", "LIMIT"}:
                score += 4
            if details.get("openPrice") not in (None, ""):
                score += 3
            if details.get("level") not in (None, ""):
                score += 1
            if score > 0:
                candidates.append((score, activity))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], cls._activity_time(item[1]) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        return candidates[0][1]

    @staticmethod
    def _activity_time(activity: dict[str, Any]) -> datetime | None:
        for key in ("dateUTC", "dateUtc", "date"):
            value = activity.get(key)
            if value:
                try:
                    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                except Exception:
                    return None
        return None

    @classmethod
    def _trade_outcome_from_activity(
        cls,
        trade: dict[str, Any],
        activity: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if activity is None:
            return {
                "trade_outcome": "UNKNOWN",
                "trade_outcome_reason": "No matching Capital.com close activity was found for this dealId.",
                "trade_close_source": "",
                "trade_close_level": None,
            }

        details = activity.get("details") or {}
        source = str(activity.get("source") or "").upper()
        level = _to_decimal(details.get("level"))
        entry = _to_decimal(trade.get("entry_price"), _to_decimal(trade.get("actual_entry"), _to_decimal(trade.get("recommended_entry"))))
        size = _to_decimal(trade.get("executed_size"), _to_decimal(trade.get("requested_size"), Decimal("1")))
        fee_amount = _to_decimal(trade.get("fee_amount"))
        stop_level = _to_decimal(details.get("stopLevel"), _to_decimal(trade.get("stop_loss")))
        profit_level = _to_decimal(details.get("profitLevel"), _to_decimal(trade.get("take_profit")))
        tolerance = cls._outcome_price_tolerance(level, stop_level, profit_level)
        outcome = "UNKNOWN"
        reason = f"Capital.com close source {source or 'UNKNOWN'} did not match TP or SL."

        if source in {"SL", "STOP", "STOP_LOSS"}:
            outcome = "LOSS"
            reason = "Capital.com close activity source indicates stop loss."
        elif source in {"TP", "TAKE_PROFIT", "PROFIT", "LIMIT"}:
            outcome = "WIN"
            reason = "Capital.com close activity source indicates take profit."
        elif level > 0 and profit_level > 0 and abs(level - profit_level) <= tolerance:
            outcome = "WIN"
            reason = "Close level matched the stored take-profit level."
        elif level > 0 and stop_level > 0 and abs(level - stop_level) <= tolerance:
            outcome = "LOSS"
            reason = "Close level matched the stored stop-loss level."

        return {
            "trade_outcome": outcome,
            "trade_outcome_reason": reason,
            "trade_close_source": source,
            "trade_close_level": level if level > 0 else None,
            "gross_pnl": cls._gross_pnl(
                direction=str(trade.get("direction") or ""),
                entry_price=entry,
                exit_price=level,
                size=size,
            ) if level > 0 and entry > 0 else None,
            "net_pnl": (
                cls._gross_pnl(direction=str(trade.get("direction") or ""), entry_price=entry, exit_price=level, size=size) - fee_amount
                if level > 0 and entry > 0
                else None
            ),
        }

    @staticmethod
    def _outcome_price_tolerance(*levels: Decimal) -> Decimal:
        positive = [abs(level) for level in levels if level > 0]
        if not positive:
            return Decimal("0.00000001")
        return max(Decimal("0.00000001"), max(positive) * Decimal("0.000001"))

    @staticmethod
    def _gross_pnl(*, direction: str, entry_price: Decimal, exit_price: Decimal, size: Decimal) -> Decimal:
        side = str(direction or "").upper()
        if side == "SELL":
            return (entry_price - exit_price) * size
        return (exit_price - entry_price) * size

    def _apply_confirmation(
        self,
        trade_id: int,
        plan: ExecutionPlan,
        deal_reference: str,
        confirm: dict[str, Any],
    ) -> ExecutionResult:
        deal_status = str(confirm.get("dealStatus") or confirm.get("status") or "").upper()
        deal_id = confirm.get("dealId") or (confirm.get("affectedDeals") or [{}])[0].get("dealId")
        accepted = deal_status == "ACCEPTED"
        self.repository.insert_attempt(
            trade_id=trade_id,
            signal_id=plan.candidate.signal_id,
            stage="confirm_position",
            success=accepted and bool(deal_id),
            summary="Broker deal confirmed." if accepted else str(confirm.get("reason") or deal_status),
            broker_payload=confirm,
        )
        if accepted and deal_id:
            actual_entry = _to_decimal(confirm.get("level"), plan.market_entry)
            fill_delta = abs(actual_entry - plan.market_entry)
            tolerance = Decimal(str(self.settings.price_tolerance))
            tolerance_note = None
            if tolerance > 0 and fill_delta > tolerance:
                tolerance_note = (
                    f"Broker fill {actual_entry} differed from execution quote {plan.market_entry} "
                    f"by {fill_delta}, above tolerance {tolerance}."
                )
            self.repository.update_trade(
                trade_id,
                status="OPEN",
                deal_id=str(deal_id),
                actual_entry=actual_entry,
                entry_price=actual_entry,
                executed_size=_to_decimal(confirm.get("size"), plan.size),
                slippage_estimate=abs(actual_entry - plan.market_entry) * _to_decimal(confirm.get("size"), plan.size),
                opened_at=_utc_now(),
                failure_reason=tolerance_note,
                broker_payload=_json_dumps(confirm),
            )
            if tolerance_note:
                self.repository.insert_event(
                    trade_id=trade_id,
                    signal_id=plan.candidate.signal_id,
                    event_type="execution_price_tolerance_warning",
                    message=tolerance_note,
                    payload={
                        "execution_quote": plan.market_entry,
                        "actual_entry": actual_entry,
                        "delta": fill_delta,
                        "tolerance": tolerance,
                    },
                )
            self.repository.insert_event(
                trade_id=trade_id,
                signal_id=plan.candidate.signal_id,
                event_type="execution_opened",
                message=f"Deal {deal_id} confirmed open.",
                payload={"dealReference": deal_reference, "dealId": deal_id},
            )
            return ExecutionResult(
                success=True,
                status="OPEN",
                executed_trade_id=trade_id,
                deal_reference=deal_reference,
                deal_id=str(deal_id),
                message="Trade opened on Capital.com demo account.",
            )
        if accepted and not deal_id:
            return ExecutionResult(
                success=True,
                status="SUBMITTED",
                executed_trade_id=trade_id,
                deal_reference=deal_reference,
                retry_requested=True,
                message="Confirmation accepted but dealId is not available yet.",
            )
        reason = str(confirm.get("reason") or confirm.get("status") or confirm.get("dealStatus") or "BrokerRejected")
        self.repository.update_trade(
            trade_id,
            status="REJECTED",
            failure_reason=reason,
            broker_rejection_reason=reason,
            broker_payload=_json_dumps(confirm),
        )
        self.repository.insert_event(
            trade_id=trade_id,
            signal_id=plan.candidate.signal_id,
            event_type="execution_rejected",
            message=reason,
            payload=confirm,
        )
        return ExecutionResult(
            success=False,
            status="REJECTED",
            executed_trade_id=trade_id,
            deal_reference=deal_reference,
            failure_reason=reason,
            error_details=reason,
            message=reason,
        )

    def _persist_validation_failure(self, candidate: ExecutionCandidate, reason: str) -> int:
        candidate_id = self.repository.upsert_candidate(candidate)
        fallback_account = CapitalAccount(
            account_id="",
            account_name=self.settings.demo_account_name,
            status="ENABLED",
            is_demo=True,
        )
        fallback_market = CapitalMarketInfo(
            epic=candidate.epic,
            symbol=candidate.symbol,
            instrument_name=candidate.symbol,
            currency="USD",
            tradeable=False,
            bid=Decimal("0"),
            offer=Decimal("0"),
            decimal_places=2,
            min_deal_size=Decimal("1"),
            min_size_increment=Decimal("1"),
            min_stop_or_profit_distance=Decimal("0"),
            min_stop_or_profit_distance_unit="",
        )
        plan = ExecutionPlan(
            candidate=candidate,
            account=fallback_account,
            market=fallback_market,
            size=Decimal(str(self.settings.default_trade_size)),
            market_entry=candidate.recommended_entry,
            stop_level=candidate.stop_loss,
            profit_level=candidate.take_profit,
            validation_note=reason,
        )
        trade_id = self.repository.insert_or_get_pending_trade(candidate, candidate_id, plan)
        self.repository.update_trade(trade_id, status="VALIDATION_FAILED", failure_reason=reason)
        self.repository.insert_attempt(
            trade_id=trade_id,
            signal_id=candidate.signal_id,
            stage="validation",
            success=False,
            summary="Execution policy rejected the signal.",
            error_details=reason,
        )
        self.repository.insert_event(
            trade_id=trade_id,
            signal_id=candidate.signal_id,
            event_type="validation_failed",
            message=reason,
        )
        return trade_id


class TradeExecutionQueueService:
    def __init__(
        self,
        settings: TradeExecutionSettings | None = None,
        repository: TradeExecutionRepository | None = None,
        service: TradeExecutionService | None = None,
    ) -> None:
        self.settings = settings or load_trade_execution_settings()
        self.repository = repository or TradeExecutionRepository()
        self.service = service or TradeExecutionService(self.settings, repository=self.repository)
        self._lock = threading.Lock()

    def enqueue(
        self,
        candidate: ExecutionCandidate,
        *,
        requested_by: str = "auto",
        requested_size: Decimal | None = None,
        force_market_execution: bool = False,
    ) -> dict[str, Any]:
        if not candidate.is_actionable:
            return {
                "accepted": False,
                "status": "SKIPPED",
                "failure_reason": "NonActionableSignal",
                "message": f"Signal {candidate.signal_id} direction {candidate.direction} is not actionable.",
            }
        block_reason, details = TradeExecutionPolicy.metadata_execution_block_reason(candidate, self.settings)
        if block_reason:
            upsert = getattr(self.repository, "upsert_candidate", None)
            if callable(upsert):
                upsert(candidate)
            recorder = getattr(self.repository, "record_execution_decision", None)
            if callable(recorder):
                recorder(
                    ExecutionDecision(
                        signal_id=candidate.signal_id,
                        raw_signal=_raw_execution_signal(candidate),
                        validation_status=str(candidate.metadata.get("validation_status") or "").strip().upper() or None,
                        validation_score=(
                            _to_decimal(candidate.metadata.get("validation_score"))
                            if candidate.metadata.get("validation_score") not in (None, "")
                            else None
                        ),
                        validation_age_seconds=TradeExecutionPolicy._validation_age_seconds(candidate, _utc_now()),
                        expected_move_pct=(
                            abs(_to_decimal(candidate.metadata.get("expected_move_pct")))
                            if candidate.metadata.get("expected_move_pct") not in (None, "")
                            else None
                        ),
                        spread_pct=None,
                        estimated_fee_pct=Decimal(str(self.settings.estimated_fee_pct)),
                        estimated_slippage_pct=Decimal(str(self.settings.estimated_slippage_pct)),
                        safety_margin_pct=Decimal(str(self.settings.execution_safety_margin_pct)),
                        net_expected_edge_pct=None,
                        execution_decision="BLOCK",
                        block_reason=block_reason,
                        evaluated_at=_utc_now(),
                        details=details,
                    )
                )
            return {
                "accepted": False,
                "status": "BLOCKED",
                "failure_reason": block_reason,
                "message": f"Signal {candidate.signal_id} blocked by execution gate: {block_reason}.",
            }
        return self.repository.enqueue(
            candidate,
            requested_by=requested_by,
            requested_size=requested_size,
            force_market_execution=force_market_execution,
        )

    def drain_once(self) -> int:
        if not self._lock.acquire(blocking=False):
            return 0
        processed = 0
        try:
            for _ in range(max(1, self.settings.queue_concurrency)):
                entry = self.repository.claim_next_queue_entry()
                if not entry:
                    break
                candidate = self.repository.get_candidate_by_id(int(entry["candidate_id"]))
                if candidate is None:
                    result = ExecutionResult(False, "FAILED", failure_reason="CandidateMissing", message="Candidate missing.")
                    self.repository.fail_or_retry_queue_entry(entry, result)
                    processed += 1
                    continue
                result = self.service.execute(
                    candidate,
                    requested_size=_to_decimal(entry.get("requested_size")) if entry.get("requested_size") else None,
                    force_market_execution=bool(entry.get("force_market_execution")),
                )
                if result.success and not result.retry_requested:
                    self.repository.complete_queue_entry(int(entry["id"]), result)
                elif result.retry_requested:
                    self.repository.fail_or_retry_queue_entry(entry, result)
                else:
                    self.repository.complete_queue_entry(int(entry["id"]), result)
                processed += 1
        finally:
            self._lock.release()
        return processed

    def snapshot(self) -> dict[str, Any]:
        return self.repository.queue_snapshot()


class TradeLifecycleReconciliationService:
    def __init__(
        self,
        settings: TradeExecutionSettings | None = None,
        client: CapitalTradingClient | None = None,
        repository: TradeExecutionRepository | None = None,
    ) -> None:
        self.settings = settings or load_trade_execution_settings()
        self.client = client or CapitalTradingClient(self.settings)
        self.repository = repository or TradeExecutionRepository()

    def run_once(self) -> int:
        trades = self.repository.reconciliation_trades()
        if not trades:
            return 0
        positions = self.client.get_open_positions()
        by_deal_id: dict[str, dict[str, Any]] = {}
        for row in positions:
            position = self._position_body(row)
            deal_id = position.get("dealId")
            if deal_id:
                by_deal_id[str(deal_id)] = row
        updated = 0
        matched_position_ids: set[str] = set()
        for trade in trades:
            trade_id = int(trade["id"])
            deal_id = trade.get("deal_id")
            deal_reference = trade.get("deal_reference")
            status = str(trade.get("status") or "").upper()
            if deal_id and str(deal_id) in by_deal_id:
                matched_position_ids.add(str(deal_id))
                if status != "OPEN" or trade.get("closed_at") is not None:
                    self.repository.update_trade(
                        trade_id,
                        status="OPEN",
                        opened_at=trade.get("opened_at") or _utc_now(),
                        closed_at=None,
                    )
                    updated += 1
                continue
            matched_position = self._match_open_position(trade, positions, matched_position_ids)
            if matched_position is not None:
                position = self._position_body(matched_position)
                position_deal_id = str(position.get("dealId") or "")
                if position_deal_id:
                    matched_position_ids.add(position_deal_id)
                update_fields: dict[str, Any] = {
                    "status": "OPEN",
                    "opened_at": trade.get("opened_at") or _utc_now(),
                    "closed_at": None,
                }
                if position_deal_id and position_deal_id != str(deal_id or ""):
                    update_fields["deal_id"] = position_deal_id
                level = _to_decimal(position.get("level"))
                size = _to_decimal(position.get("size"))
                stop_level = _to_decimal(position.get("stopLevel"))
                profit_level = _to_decimal(position.get("profitLevel"))
                if level > 0:
                    update_fields["actual_entry"] = level
                if size > 0:
                    update_fields["executed_size"] = size
                if stop_level > 0:
                    update_fields["stop_loss"] = stop_level
                if profit_level > 0:
                    update_fields["take_profit"] = profit_level
                self.repository.update_trade(trade_id, **update_fields)
                updated += 1
                continue
            if status == "SUBMITTED" and deal_reference:
                try:
                    confirm = self.client.confirm_deal(str(deal_reference))
                except CapitalTradingApiError as exc:
                    if exc.status_code == 404:
                        continue
                    raise
                deal_status = str(confirm.get("dealStatus") or confirm.get("status") or "").upper()
                confirmed_id = confirm.get("dealId") or (confirm.get("affectedDeals") or [{}])[0].get("dealId")
                if deal_status == "ACCEPTED" and confirmed_id:
                    self.repository.update_trade(
                        trade_id,
                        status="OPEN",
                        deal_id=str(confirmed_id),
                        actual_entry=_to_decimal(confirm.get("level")),
                        executed_size=_to_decimal(confirm.get("size")),
                        opened_at=_utc_now(),
                    )
                    updated += 1
                elif deal_status in {"REJECTED", "FAILED", "ERROR"}:
                    reason = str(confirm.get("reason") or deal_status)
                    self.repository.update_trade(
                        trade_id,
                        status="REJECTED",
                        failure_reason=reason,
                        broker_rejection_reason=reason,
                    )
                    updated += 1
            elif status in {"OPEN", "CLOSE_REQUESTED"} and deal_id:
                activities = self.client.get_activity_history(deal_id=str(deal_id))
                close = next((a for a in activities if str(a.get("dealId") or "") == str(deal_id)), None)
                if close and str(close.get("status") or "").upper() in {"ACCEPTED", "EXECUTED", "PROCESSED"}:
                    outcome = TradeExecutionService._trade_outcome_from_activity(trade, close)
                    self.repository.update_trade(
                        trade_id,
                        status="CLOSED",
                        closed_at=_utc_now(),
                        exit_price=outcome.get("trade_close_level"),
                        gross_pnl=outcome.get("gross_pnl"),
                        net_pnl=outcome.get("net_pnl"),
                        close_reason=outcome.get("trade_close_source") or outcome.get("trade_outcome_reason"),
                        final_outcome=outcome.get("trade_outcome") or "UNKNOWN",
                        outcome_finalized_at=_utc_now(),
                    )
                    updated += 1
        return updated

    @staticmethod
    def _position_body(row: dict[str, Any]) -> dict[str, Any]:
        return row.get("position") or row

    @staticmethod
    def _position_market(row: dict[str, Any]) -> dict[str, Any]:
        return row.get("market") or {}

    @staticmethod
    def _decimal_close(left: Decimal, right: Decimal, tolerance: Decimal) -> bool:
        if left <= 0 or right <= 0:
            return True
        return abs(left - right) <= tolerance

    def _match_open_position(
        self,
        trade: dict[str, Any],
        positions: list[dict[str, Any]],
        matched_position_ids: set[str],
    ) -> dict[str, Any] | None:
        tolerance = max(Decimal(str(self.settings.price_tolerance or 0)), Decimal("0.02"))
        trade_epic = str(trade.get("epic") or "").upper()
        trade_direction = str(trade.get("direction") or "").upper()
        trade_size = _to_decimal(trade.get("executed_size")) or _to_decimal(trade.get("requested_size"))
        trade_entry = _to_decimal(trade.get("actual_entry")) or _to_decimal(trade.get("recommended_entry"))
        trade_stop = _to_decimal(trade.get("stop_loss"))
        trade_profit = _to_decimal(trade.get("take_profit"))

        best: tuple[int, dict[str, Any]] | None = None
        for row in positions:
            position = self._position_body(row)
            market = self._position_market(row)
            position_deal_id = str(position.get("dealId") or "")
            if position_deal_id and position_deal_id in matched_position_ids:
                continue
            position_epic = str(position.get("epic") or market.get("epic") or "").upper()
            position_direction = str(position.get("direction") or "").upper()
            if trade_epic and position_epic and trade_epic != position_epic:
                continue
            if trade_direction and position_direction and trade_direction != position_direction:
                continue

            score = 0
            position_size = _to_decimal(position.get("size"))
            position_entry = _to_decimal(position.get("level"))
            position_stop = _to_decimal(position.get("stopLevel"))
            position_profit = _to_decimal(position.get("profitLevel"))
            if self._decimal_close(trade_size, position_size, Decimal("0.00000001")):
                score += 1
            if self._decimal_close(trade_entry, position_entry, tolerance):
                score += 2
            if self._decimal_close(trade_stop, position_stop, tolerance):
                score += 2
            if self._decimal_close(trade_profit, position_profit, tolerance):
                score += 2
            if score >= 5 and (best is None or score > best[0]):
                best = (score, row)
        return best[1] if best else None


def enqueue_signal_for_execution(
    signal_id: str,
    *,
    dsn: str | None = None,
    requested_by: str = "auto",
    require_auto_enabled: bool = True,
    requested_size: Decimal | None = None,
    force_market_execution: bool = False,
    execute_immediately: bool = True,
) -> dict[str, Any]:
    settings = load_trade_execution_settings()
    if require_auto_enabled and not settings.auto_execute_signals:
        return {
            "accepted": False,
            "status": "DISABLED",
            "message": "AUTO_EXECUTE_SIGNALS is not enabled; signal was not queued.",
        }
    repository = TradeExecutionRepository(dsn)
    candidate = repository.candidate_from_signal(signal_id)
    if candidate is None:
        return {"accepted": False, "status": "NOT_FOUND", "message": f"Signal {signal_id} was not found."}
    queue = TradeExecutionQueueService(settings=settings, repository=repository)
    result = queue.enqueue(
        candidate,
        requested_by=requested_by,
        requested_size=requested_size,
        force_market_execution=force_market_execution,
    )
    if execute_immediately and result.get("accepted"):
        drained = queue.drain_once()
        result = {
            **result,
            "drained_immediately": drained,
            "queue": queue.snapshot(),
            "trade": repository.get_trade_by_signal(candidate.signal_id),
        }
    return result


def enqueue_latest_signal_for_execution(
    *,
    symbol: str = "ETHUSD",
    resolution: str | None = None,
    dsn: str | None = None,
    requested_by: str = "auto",
    require_auto_enabled: bool = True,
    requested_size: Decimal | None = None,
    force_market_execution: bool = False,
    execute_immediately: bool = True,
) -> dict[str, Any]:
    settings = load_trade_execution_settings()
    if require_auto_enabled and not settings.auto_execute_signals:
        return {
            "accepted": False,
            "status": "DISABLED",
            "message": "AUTO_EXECUTE_SIGNALS is not enabled; signal was not queued.",
        }
    repository = TradeExecutionRepository(dsn)
    candidate = repository.latest_candidate(symbol=symbol, resolution=resolution)
    if candidate is None:
        return {"accepted": False, "status": "NOT_FOUND", "message": "No generated signal was found."}
    queue = TradeExecutionQueueService(settings=settings, repository=repository)
    result = queue.enqueue(
        candidate,
        requested_by=requested_by,
        requested_size=requested_size,
        force_market_execution=force_market_execution,
    )
    if execute_immediately and result.get("accepted"):
        drained = queue.drain_once()
        result = {
            **result,
            "drained_immediately": drained,
            "queue": queue.snapshot(),
            "trade": repository.get_trade_by_signal(candidate.signal_id),
        }
    return result
