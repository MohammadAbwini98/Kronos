from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import pandas as pd

from .context import StrategyContext
from .exits import build_exit_plan
from .indicators import IndicatorBuilder, IndicatorConfig
from .models import StrategyCandidate


_RAW_PRICE_COLUMNS = {"open", "high", "low", "close"}
_ACTIVE_POSITION_STATUSES = {"OPEN", "ACTIVE", "PENDING", "FILLED"}


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade: float = 0.005
    conservative_risk_per_trade: float = 0.0025
    max_risk_per_trade: float = 0.01
    max_daily_loss: float = 0.02
    max_consecutive_losses: int = 3
    loss_cooldown_minutes: int = 120
    signal_cooldown_minutes: int = 0
    max_open_positions_per_symbol: int = 1
    max_spread_absolute: float | None = 3.0
    max_spread_atr: float | None = 0.15
    stop_distance_atr_min: float = 0.5
    stop_distance_atr_max: float = 2.5
    tp1_close_fraction: float = 0.60
    tp2_close_fraction: float = 0.40
    breakeven_r_multiple: float = 1.0
    trailing_stop_atr_multiple: float = 0.50
    time_stop_progress_r_multiple: float = 0.30
    weak_win_rate_threshold: float = 0.50
    weak_profit_factor_threshold: float = 1.0
    severe_loss_lookback: int = 10
    severe_loss_threshold: int = 6
    broker_size_step: float = 0.01
    default_time_stop_bars_trend: int = 8
    default_time_stop_bars_breakout: int = 6
    default_time_stop_bars_mean_reversion: int = 5

    def time_stop_bars(self, strategy_type: str) -> int:
        normalized = str(strategy_type or "").strip().lower()
        if normalized == "trend_pullback":
            return self.default_time_stop_bars_trend
        if normalized == "breakout_momentum":
            return self.default_time_stop_bars_breakout
        if normalized == "range_mean_reversion":
            return self.default_time_stop_bars_mean_reversion
        return self.default_time_stop_bars_trend


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    risk_score: float | None = None
    position_size: float | None = None
    blocked_by: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def approved_decision(
        cls,
        *,
        risk_score: float | None = None,
        position_size: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> "RiskDecision":
        return cls(
            approved=True,
            reason="APPROVED",
            risk_score=risk_score,
            position_size=position_size,
            blocked_by=[],
            details=dict(details or {}),
        )

    @classmethod
    def blocked(
        cls,
        reason: str,
        *,
        risk_score: float | None = None,
        blocked_by: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> "RiskDecision":
        return cls(
            approved=False,
            reason=reason,
            risk_score=risk_score,
            position_size=None,
            blocked_by=list(blocked_by or [reason]),
            details=dict(details or {}),
        )


class RiskManager:
    """Risk gate, sizing engine, and exit-plan builder for StrategyCandidate evaluation."""

    def __init__(
        self,
        config: RiskConfig | None = None,
        *,
        indicator_config: IndicatorConfig | None = None,
    ) -> None:
        self.config = config or RiskConfig()
        self.indicator_config = indicator_config or IndicatorConfig()
        self.indicator_builder = IndicatorBuilder(config=self.indicator_config)

    def evaluate(self, candidate: StrategyCandidate, context: StrategyContext) -> RiskDecision:
        metadata = dict(context.metadata or {})
        entry_price = float(candidate.entry_price)
        stop_loss = float(candidate.stop_loss)
        signal = str(candidate.signal).upper().strip()
        risk_side = "LONG" if signal == "BUY" else "SHORT"
        stop_distance = self._stop_distance(signal, entry_price, stop_loss)
        if stop_distance <= 0.0:
            return RiskDecision.blocked(
                "INVALID_STOP_DISTANCE",
                blocked_by=["STOP_QUALITY"],
                details={
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "signal": signal,
                },
            )

        take_profit_1 = self._validate_take_profit(candidate.take_profit_1, signal, entry_price, label="TP1")
        if take_profit_1 is False:
            return RiskDecision.blocked(
                "INVALID_TAKE_PROFIT_1",
                blocked_by=["TAKE_PROFIT"],
                details={"entry_price": entry_price, "take_profit_1": candidate.take_profit_1, "signal": signal},
            )
        take_profit_2 = self._validate_take_profit(candidate.take_profit_2, signal, entry_price, label="TP2")
        if take_profit_2 is False:
            return RiskDecision.blocked(
                "INVALID_TAKE_PROFIT_2",
                blocked_by=["TAKE_PROFIT"],
                details={"entry_price": entry_price, "take_profit_2": candidate.take_profit_2, "signal": signal},
            )
        if take_profit_1 not in (None, False) and take_profit_2 not in (None, False):
            if signal == "BUY" and float(take_profit_2) < float(take_profit_1):
                return RiskDecision.blocked(
                    "INVALID_TAKE_PROFIT_ORDER",
                    blocked_by=["TAKE_PROFIT"],
                    details={"take_profit_1": take_profit_1, "take_profit_2": take_profit_2, "signal": signal},
                )
            if signal == "SELL" and float(take_profit_2) > float(take_profit_1):
                return RiskDecision.blocked(
                    "INVALID_TAKE_PROFIT_ORDER",
                    blocked_by=["TAKE_PROFIT"],
                    details={"take_profit_1": take_profit_1, "take_profit_2": take_profit_2, "signal": signal},
                )

        current_row = self._current_row(context)
        atr_value = self._coerce_float(
            self._first_not_none(
                self._value_from_row(current_row, "ATR_14"),
                candidate.indicators.get("ATR_14"),
                context.indicators.get("ATR_14"),
            )
        )
        if atr_value is None or atr_value <= 0.0:
            return RiskDecision.blocked(
                "MISSING_ATR_14",
                blocked_by=["STOP_QUALITY"],
                details={"entry_price": entry_price, "stop_loss": stop_loss, "signal": signal},
            )

        stop_distance_atr = stop_distance / atr_value
        if stop_distance_atr < self.config.stop_distance_atr_min:
            return RiskDecision.blocked(
                "STOP_DISTANCE_TOO_TIGHT",
                blocked_by=["STOP_QUALITY"],
                details={
                    "stop_distance": stop_distance,
                    "ATR_14": atr_value,
                    "stop_distance_atr": stop_distance_atr,
                },
            )
        if stop_distance_atr > self.config.stop_distance_atr_max:
            return RiskDecision.blocked(
                "STOP_DISTANCE_TOO_WIDE",
                blocked_by=["STOP_QUALITY"],
                details={
                    "stop_distance": stop_distance,
                    "ATR_14": atr_value,
                    "stop_distance_atr": stop_distance_atr,
                },
            )

        account_equity = self._account_equity(metadata)
        active_daily_loss = self._daily_loss_fraction(metadata, account_equity, context.now_utc)
        if active_daily_loss is not None and active_daily_loss >= self.config.max_daily_loss:
            return RiskDecision.blocked(
                "MAX_DAILY_LOSS_HIT",
                blocked_by=["MAX_DAILY_LOSS"],
                details={
                    "daily_loss_fraction": active_daily_loss,
                    "max_daily_loss": self.config.max_daily_loss,
                },
            )

        if self._cooldown_active(metadata, context.now_utc):
            return RiskDecision.blocked(
                "LOSS_COOLDOWN_ACTIVE",
                blocked_by=["MAX_CONSECUTIVE_LOSSES", "COOLDOWN"],
                details={
                    "consecutive_losses": self._coerce_int(metadata.get("consecutive_losses"), default=0),
                    "max_consecutive_losses": self.config.max_consecutive_losses,
                    "loss_cooldown_minutes": self.config.loss_cooldown_minutes,
                },
            )

        if self._signal_cooldown_active(metadata, context.symbol, context.now_utc):
            last_signal_at = self._last_signal_at(metadata, context.symbol)
            cooldown_until = None
            if last_signal_at is not None:
                cooldown_until = last_signal_at + pd.Timedelta(minutes=self.config.signal_cooldown_minutes)
            return RiskDecision.blocked(
                "SIGNAL_COOLDOWN_ACTIVE",
                blocked_by=["COOLDOWN"],
                details={
                    "signal_cooldown_minutes": self.config.signal_cooldown_minutes,
                    "last_signal_at": None if last_signal_at is None else last_signal_at.isoformat(),
                    "cooldown_until": None if cooldown_until is None else cooldown_until.isoformat(),
                },
            )

        spread = self._spread_value(current_row, candidate, metadata)
        spread_atr = spread / atr_value if atr_value > 0.0 else None
        if self.config.max_spread_absolute is not None and spread > self.config.max_spread_absolute:
            return RiskDecision.blocked(
                "SPREAD_TOO_WIDE_ABSOLUTE",
                blocked_by=["SPREAD_PROTECTION"],
                details={
                    "spread": spread,
                    "max_spread_absolute": self.config.max_spread_absolute,
                    "spread_atr": spread_atr,
                },
            )
        if self.config.max_spread_atr is not None and spread_atr is not None and spread_atr > self.config.max_spread_atr:
            return RiskDecision.blocked(
                "SPREAD_TOO_WIDE_ATR",
                blocked_by=["SPREAD_PROTECTION"],
                details={
                    "spread": spread,
                    "ATR_14": atr_value,
                    "spread_atr": spread_atr,
                    "max_spread_atr": self.config.max_spread_atr,
                },
            )

        open_positions = self._open_positions_for_symbol(metadata, context.symbol)
        if open_positions >= self.config.max_open_positions_per_symbol:
            return RiskDecision.blocked(
                "MAX_OPEN_POSITIONS_PER_SYMBOL",
                blocked_by=["OPEN_POSITION_LIMIT"],
                details={
                    "symbol": context.symbol,
                    "open_positions": open_positions,
                    "max_open_positions_per_symbol": self.config.max_open_positions_per_symbol,
                },
            )

        risk_per_trade, performance_flags = self._risk_per_trade(metadata)
        if account_equity is None:
            if candidate.position_size is None:
                return RiskDecision.blocked(
                    "MISSING_ACCOUNT_EQUITY",
                    blocked_by=["POSITION_SIZING"],
                    details={"risk_per_trade": risk_per_trade},
                )
            position_size = float(candidate.position_size)
            risk_amount = None
            sizing_mode = "CANDIDATE_POSITION_SIZE"
        else:
            risk_amount = account_equity * risk_per_trade
            raw_position_size = risk_amount / stop_distance
            position_size = self._apply_broker_limits(raw_position_size, metadata)
            if position_size is None or position_size <= 0.0:
                return RiskDecision.blocked(
                    "POSITION_SIZE_BELOW_MINIMUM",
                    blocked_by=["POSITION_SIZING"],
                    details={
                        "raw_position_size": raw_position_size,
                        "size_step": self._size_step(metadata),
                    },
                )
            sizing_mode = "RISK_BASED"

        exit_plan = self._exit_plan(
            candidate=candidate,
            signal=signal,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit_1=float(take_profit_1) if take_profit_1 not in (None, False) else None,
            take_profit_2=float(take_profit_2) if take_profit_2 not in (None, False) else None,
            stop_distance=stop_distance,
            spread=spread,
            atr_value=atr_value,
            current_row=current_row,
        )
        risk_score = self._risk_score(
            risk_per_trade=risk_per_trade,
            stop_distance_atr=stop_distance_atr,
            performance_flags=performance_flags,
            position_size=position_size,
        )
        return RiskDecision.approved_decision(
            risk_score=risk_score,
            position_size=position_size,
            details={
                "account_equity": account_equity,
                "risk_side": risk_side,
                "risk_per_trade": risk_per_trade,
                "risk_amount": risk_amount,
                "position_sizing_mode": sizing_mode,
                "stop_loss": stop_loss,
                "take_profit_1": float(take_profit_1) if take_profit_1 not in (None, False) else None,
                "take_profit_2": float(take_profit_2) if take_profit_2 not in (None, False) else None,
                "stop_distance": stop_distance,
                "stop_distance_atr": stop_distance_atr,
                "take_profit_split": {
                    "tp1_fraction": self.config.tp1_close_fraction,
                    "tp2_fraction": self.config.tp2_close_fraction,
                },
                "performance_flags": performance_flags,
                "exit_plan": exit_plan,
            },
        )

    def _current_row(self, context: StrategyContext) -> dict[str, Any] | None:
        frame = context.candles
        if frame is None or frame.empty:
            return None

        prepared = frame.copy()
        if "ts" not in prepared.columns and "timestamps" in prepared.columns:
            prepared = prepared.rename(columns={"timestamps": "ts"})
        if "ts" in prepared.columns:
            prepared["ts"] = pd.to_datetime(prepared["ts"], utc=True)
            prepared = prepared.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)

        required = {"ATR_14", "EMA_20", "EMA_50", "spread"}
        if not required.issubset(prepared.columns):
            has_timestamps = ("ts" in prepared.columns) or ("timestamps" in prepared.columns)
            if _RAW_PRICE_COLUMNS.issubset(prepared.columns) and has_timestamps:
                prepared = self.indicator_builder.build(prepared)

        return prepared.iloc[-1].to_dict()

    def _account_equity(self, metadata: dict[str, Any]) -> float | None:
        return self._coerce_float(
            self._first_not_none(
                metadata.get("account_equity"),
                metadata.get("equity"),
                metadata.get("account_balance"),
            )
        )

    def _daily_loss_fraction(
        self,
        metadata: dict[str, Any],
        account_equity: float | None,
        now_utc,
    ) -> float | None:
        explicit_pct = self._coerce_float(metadata.get("daily_loss_pct"))
        if explicit_pct is not None:
            return explicit_pct

        daily_loss_hit_at = self._coerce_timestamp(
            self._first_not_none(metadata.get("daily_loss_hit_at"), metadata.get("daily_loss_hit_at_utc"))
        )
        if daily_loss_hit_at is not None and daily_loss_hit_at.date() != now_utc.date():
            return None

        raw_loss = self._coerce_float(
            self._first_not_none(metadata.get("daily_loss"), metadata.get("daily_realized_loss"))
        )
        if raw_loss is None:
            daily_pnl = self._coerce_float(metadata.get("daily_pnl"))
            if daily_pnl is not None and daily_pnl < 0.0:
                raw_loss = abs(daily_pnl)

        if raw_loss is None or account_equity is None or account_equity <= 0.0:
            return None
        return abs(raw_loss) / account_equity

    def _cooldown_active(self, metadata: dict[str, Any], now_utc) -> bool:
        consecutive_losses = self._coerce_int(metadata.get("consecutive_losses"), default=0)
        if consecutive_losses < self.config.max_consecutive_losses:
            return False

        cooldown_until = self._coerce_timestamp(
            self._first_not_none(metadata.get("cooldown_until"), metadata.get("cooldown_until_utc"))
        )
        if cooldown_until is not None:
            return cooldown_until > now_utc

        last_loss_at = self._coerce_timestamp(
            self._first_not_none(metadata.get("last_loss_at"), metadata.get("last_loss_utc"))
        )
        if last_loss_at is None:
            return True
        return last_loss_at + pd.Timedelta(minutes=self.config.loss_cooldown_minutes) > now_utc

    def _signal_cooldown_active(self, metadata: dict[str, Any], symbol: str, now_utc) -> bool:
        if self.config.signal_cooldown_minutes <= 0:
            return False
        last_signal_at = self._last_signal_at(metadata, symbol)
        if last_signal_at is None:
            return False
        return last_signal_at + pd.Timedelta(minutes=self.config.signal_cooldown_minutes) > now_utc

    def _last_signal_at(self, metadata: dict[str, Any], symbol: str):
        per_symbol = metadata.get("last_signal_at_per_symbol")
        if isinstance(per_symbol, dict):
            timestamp = self._coerce_timestamp(per_symbol.get(symbol))
            if timestamp is not None:
                return timestamp
        return self._coerce_timestamp(
            self._first_not_none(
                metadata.get("last_signal_at"),
                metadata.get("last_signal_utc"),
                metadata.get("last_decision_at"),
                metadata.get("last_decision_utc"),
            )
        )

    def _open_positions_for_symbol(self, metadata: dict[str, Any], symbol: str) -> int:
        per_symbol = metadata.get("open_positions_per_symbol")
        if isinstance(per_symbol, dict):
            value = self._coerce_int(per_symbol.get(symbol), default=0)
            if value > 0:
                return value

        positions = metadata.get("open_positions")
        if isinstance(positions, list):
            count = 0
            for position in positions:
                if not isinstance(position, dict):
                    continue
                status = str(position.get("status") or "OPEN").upper().strip()
                if status not in _ACTIVE_POSITION_STATUSES:
                    continue
                if str(position.get("symbol") or "").upper().strip() == str(symbol).upper().strip():
                    count += 1
            return count
        return 0

    def _risk_per_trade(self, metadata: dict[str, Any]) -> tuple[float, list[str]]:
        flags: list[str] = []
        risk_per_trade = self.config.risk_per_trade
        risk_mode = str(metadata.get("risk_mode") or "").upper().strip()
        if risk_mode == "CONSERVATIVE" or bool(metadata.get("force_conservative_risk")):
            risk_per_trade = self.config.conservative_risk_per_trade
            flags.append("CONSERVATIVE_MODE")

        recent_performance = metadata.get("recent_performance") if isinstance(metadata.get("recent_performance"), dict) else {}
        win_rate = self._coerce_float(
            self._first_not_none(metadata.get("last_20_trades_win_rate"), recent_performance.get("last_20_trades_win_rate"))
        )
        profit_factor = self._coerce_float(
            self._first_not_none(metadata.get("profit_factor"), recent_performance.get("profit_factor"))
        )
        losses_last_10 = self._coerce_int(
            self._first_not_none(metadata.get("last_10_trades_losses"), recent_performance.get("last_10_trades_losses")),
            default=0,
        )
        weak_performance = (
            (win_rate is not None and win_rate < self.config.weak_win_rate_threshold)
            or (profit_factor is not None and profit_factor < self.config.weak_profit_factor_threshold)
        )
        if weak_performance:
            risk_per_trade = min(risk_per_trade, self.config.conservative_risk_per_trade)
            flags.append("WEAK_RECENT_PERFORMANCE")
        if losses_last_10 >= self.config.severe_loss_threshold:
            flags.append("SEVERE_RECENT_LOSSES")

        return min(risk_per_trade, self.config.max_risk_per_trade), flags

    def _apply_broker_limits(self, raw_position_size: float, metadata: dict[str, Any]) -> float | None:
        max_allowed_size = self._coerce_float(
            self._first_not_none(metadata.get("max_allowed_size"), metadata.get("broker_max_allowed_size"))
        )
        min_allowed_size = self._coerce_float(
            self._first_not_none(metadata.get("min_allowed_size"), metadata.get("broker_min_allowed_size"))
        )
        size = raw_position_size
        if max_allowed_size is not None:
            size = min(size, max_allowed_size)

        step = self._size_step(metadata)
        if step is not None and step > 0.0:
            size = math.floor(size / step) * step
            size = round(size, 10)

        if min_allowed_size is not None and size < min_allowed_size:
            return None
        return size if size > 0.0 else None

    def _size_step(self, metadata: dict[str, Any]) -> float | None:
        step = self._coerce_float(
            self._first_not_none(metadata.get("size_step"), metadata.get("broker_size_step"))
        )
        if step is None:
            step = self.config.broker_size_step
        return step if step and step > 0.0 else None

    def _spread_value(
        self,
        current_row: dict[str, Any] | None,
        candidate: StrategyCandidate,
        metadata: dict[str, Any],
    ) -> float:
        value = self._coerce_float(
            self._first_not_none(
                self._value_from_row(current_row, "spread"),
                candidate.indicators.get("spread"),
                metadata.get("spread"),
            )
        )
        return value if value is not None and value > 0.0 else 0.0

    def _exit_plan(
        self,
        *,
        candidate: StrategyCandidate,
        signal: str,
        entry_price: float,
        stop_loss: float,
        take_profit_1: float | None,
        take_profit_2: float | None,
        stop_distance: float,
        spread: float,
        atr_value: float,
        current_row: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return build_exit_plan(
            config=self.config,
            candidate=candidate,
            signal=signal,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            stop_distance=stop_distance,
            spread=spread,
            atr_value=atr_value,
            current_row=current_row,
        )

    def _risk_score(
        self,
        *,
        risk_per_trade: float,
        stop_distance_atr: float,
        performance_flags: list[str],
        position_size: float | None,
    ) -> float:
        stop_score = max(0.0, 1.0 - (abs(stop_distance_atr - 1.25) / 1.75))
        risk_budget_score = max(0.0, 1.0 - (risk_per_trade / self.config.max_risk_per_trade) * 0.5)
        sizing_score = 1.0 if position_size is not None and position_size > 0.0 else 0.0
        performance_score = 0.80 if performance_flags else 1.0
        return round(100.0 * ((stop_score + risk_budget_score + sizing_score + performance_score) / 4.0), 2)

    def _stop_distance(self, signal: str, entry_price: float, stop_loss: float) -> float:
        if signal == "BUY":
            return entry_price - stop_loss
        return stop_loss - entry_price

    def _validate_take_profit(
        self,
        take_profit: float | None,
        signal: str,
        entry_price: float,
        *,
        label: str,
    ) -> float | None | bool:
        del label
        if take_profit is None:
            return None
        value = float(take_profit)
        if signal == "BUY" and value <= entry_price:
            return False
        if signal == "SELL" and value >= entry_price:
            return False
        return value

    def _first_not_none(self, *values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    def _value_from_row(self, row: dict[str, Any] | None, key: str) -> Any:
        if row is None:
            return None
        return row.get(key)

    def _coerce_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            if value != value:
                return None
        except Exception:
            pass
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _coerce_int(self, value: Any, *, default: int = 0) -> int:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _coerce_timestamp(self, value: Any):
        if value is None:
            return None
        try:
            return pd.to_datetime(value, utc=True)
        except (TypeError, ValueError):
            return None