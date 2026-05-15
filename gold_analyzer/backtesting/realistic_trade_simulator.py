from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Iterable

import pandas as pd


TRADE_DIRECTIONS = {"BUY", "SELL", "LONG", "SHORT"}


@dataclass(frozen=True)
class RealisticSimulatorConfig:
    spread: float = 0.0
    slippage: float = 0.0
    same_bar_policy: str = "conservative_sl_first"
    cooldown_bars: int = 0
    daily_max_loss: float | None = None
    initial_equity: float = 10_000.0
    default_time_stop_bars: int = 12


@dataclass(frozen=True)
class TradeSetup:
    signal: str
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float | None = None
    size: float = 1.0
    signal_index: int = 0
    time_stop_bars: int | None = None
    strategy_type: str | None = None
    regime: str | None = None
    timeframe: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulatedTrade:
    signal: str
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float | None
    size: float
    outcome: str
    exit_reason: str
    net_pnl: float
    r_multiple: float
    strategy_type: str | None = None
    regime: str | None = None
    timeframe: str | None = None


@dataclass(frozen=True)
class SimulationResult:
    trades: list[SimulatedTrade]
    blocked: list[dict[str, Any]]
    metrics: dict[str, Any]


class RealisticTradeSimulator:
    """Path-aware trade simulator for TP/SL validation without live execution."""

    def __init__(self, config: RealisticSimulatorConfig | None = None) -> None:
        self.config = config or RealisticSimulatorConfig()

    def run(self, candles: pd.DataFrame, signals: Iterable[TradeSetup | dict[str, Any]]) -> SimulationResult:
        frame = self._prepare_candles(candles)
        trades: list[SimulatedTrade] = []
        blocked: list[dict[str, Any]] = []
        cooldown_until = -1
        daily_loss: dict[Any, float] = {}

        for raw_setup in signals:
            setup = raw_setup if isinstance(raw_setup, TradeSetup) else TradeSetup(**raw_setup)
            direction = _normalize_signal(setup.signal)
            if direction is None:
                blocked.append({"reason": "NON_TRADE_SIGNAL", "signal": setup.signal})
                continue
            if setup.signal_index < cooldown_until:
                blocked.append({"reason": "COOLDOWN_ACTIVE", "signal_index": setup.signal_index})
                continue
            if not self._valid_levels(direction, setup):
                blocked.append({"reason": "INVALID_TRADE_LEVELS", "signal": setup.signal})
                continue
            if self._daily_loss_hit(frame, setup.signal_index, daily_loss):
                blocked.append({"reason": "DAILY_MAX_LOSS_HIT", "signal_index": setup.signal_index})
                continue

            trade = self._simulate_one(frame, setup, direction)
            trades.append(trade)
            if trade.outcome == "LOSS":
                key = pd.Timestamp(frame.iloc[trade.exit_index]["ts"]).date()
                daily_loss[key] = daily_loss.get(key, 0.0) + abs(trade.net_pnl)
                cooldown_until = trade.exit_index + max(0, int(self.config.cooldown_bars))

        return SimulationResult(trades=trades, blocked=blocked, metrics=self.metrics(trades, len(frame)))

    def _simulate_one(self, frame: pd.DataFrame, setup: TradeSetup, direction: str) -> SimulatedTrade:
        entry_index = max(0, min(int(setup.signal_index), len(frame) - 1))
        entry_fill = self._entry_fill(direction, float(setup.entry_price))
        stop = float(setup.stop_loss)
        tp1 = float(setup.take_profit_1)
        tp2 = None if setup.take_profit_2 is None else float(setup.take_profit_2)
        max_bars = int(setup.time_stop_bars or self.config.default_time_stop_bars)
        terminal_index = min(len(frame) - 1, entry_index + max(1, max_bars))
        half_closed = False
        realized_pnl = 0.0
        remaining_size = float(setup.size)
        exit_price = entry_fill
        exit_reason = "TIME_STOP"

        for idx in range(entry_index, terminal_index + 1):
            row = frame.iloc[idx]
            high = float(row["high"])
            low = float(row["low"])
            tp1_hit = high >= tp1 if direction == "BUY" else low <= tp1
            tp2_hit = bool(tp2 is not None and (high >= tp2 if direction == "BUY" else low <= tp2))
            sl_hit = low <= stop if direction == "BUY" else high >= stop

            if sl_hit and (tp1_hit or tp2_hit):
                if self.config.same_bar_policy == "optimistic_tp_first":
                    sl_hit = False
                else:
                    tp1_hit = False
                    tp2_hit = False

            if sl_hit:
                exit_price = self._exit_fill(direction, stop)
                realized_pnl += _pnl(direction, entry_fill, exit_price, remaining_size)
                exit_reason = "STOP_LOSS"
                return self._final_trade(setup, direction, entry_index, idx, entry_fill, exit_price, stop, tp1, tp2, realized_pnl, exit_reason)

            if tp1_hit and not half_closed:
                close_size = remaining_size * 0.5 if tp2 is not None else remaining_size
                exit_price = self._exit_fill(direction, tp1)
                realized_pnl += _pnl(direction, entry_fill, exit_price, close_size)
                remaining_size -= close_size
                half_closed = True
                if remaining_size <= 1e-12:
                    exit_reason = "TAKE_PROFIT_1"
                    return self._final_trade(setup, direction, entry_index, idx, entry_fill, exit_price, stop, tp1, tp2, realized_pnl, exit_reason)
                stop = entry_fill

            if tp2_hit and half_closed and remaining_size > 0.0:
                exit_price = self._exit_fill(direction, float(tp2))
                realized_pnl += _pnl(direction, entry_fill, exit_price, remaining_size)
                exit_reason = "TAKE_PROFIT_2"
                return self._final_trade(setup, direction, entry_index, idx, entry_fill, exit_price, stop, tp1, tp2, realized_pnl, exit_reason)

        final_close = float(frame.iloc[terminal_index]["close"])
        exit_price = self._exit_fill(direction, final_close)
        realized_pnl += _pnl(direction, entry_fill, exit_price, remaining_size)
        return self._final_trade(setup, direction, entry_index, terminal_index, entry_fill, exit_price, stop, tp1, tp2, realized_pnl, exit_reason)

    def _final_trade(
        self,
        setup: TradeSetup,
        direction: str,
        entry_index: int,
        exit_index: int,
        entry_fill: float,
        exit_price: float,
        stop_loss: float,
        tp1: float,
        tp2: float | None,
        pnl: float,
        exit_reason: str,
    ) -> SimulatedTrade:
        risk = abs(float(setup.entry_price) - float(setup.stop_loss)) * max(float(setup.size), 1e-12)
        r_multiple = 0.0 if risk <= 0.0 else pnl / risk
        if pnl > 1e-12:
            outcome = "WIN"
        elif pnl < -1e-12:
            outcome = "LOSS"
        else:
            outcome = "BREAKEVEN"
        return SimulatedTrade(
            signal=direction,
            entry_index=entry_index,
            exit_index=exit_index,
            entry_price=entry_fill,
            exit_price=exit_price,
            stop_loss=stop_loss,
            take_profit_1=tp1,
            take_profit_2=tp2,
            size=float(setup.size),
            outcome=outcome,
            exit_reason=exit_reason,
            net_pnl=pnl,
            r_multiple=r_multiple,
            strategy_type=setup.strategy_type,
            regime=setup.regime,
            timeframe=setup.timeframe,
        )

    def _entry_fill(self, direction: str, price: float) -> float:
        half_spread = float(self.config.spread) / 2.0
        slip = float(self.config.slippage)
        return price + half_spread + slip if direction == "BUY" else price - half_spread - slip

    def _exit_fill(self, direction: str, price: float) -> float:
        half_spread = float(self.config.spread) / 2.0
        slip = float(self.config.slippage)
        return price - half_spread - slip if direction == "BUY" else price + half_spread + slip

    def _daily_loss_hit(self, frame: pd.DataFrame, signal_index: int, daily_loss: dict[Any, float]) -> bool:
        if self.config.daily_max_loss is None:
            return False
        idx = max(0, min(int(signal_index), len(frame) - 1))
        key = pd.Timestamp(frame.iloc[idx]["ts"]).date()
        return daily_loss.get(key, 0.0) >= float(self.config.daily_max_loss)

    @staticmethod
    def _valid_levels(direction: str, setup: TradeSetup) -> bool:
        entry = float(setup.entry_price)
        stop = float(setup.stop_loss)
        tp = float(setup.take_profit_1)
        if direction == "BUY":
            return stop < entry < tp
        return tp < entry < stop

    @staticmethod
    def _prepare_candles(candles: pd.DataFrame) -> pd.DataFrame:
        required = {"open", "high", "low", "close"}
        if candles is None or candles.empty or not required.issubset(candles.columns):
            raise ValueError("candles must contain open/high/low/close rows")
        frame = candles.copy()
        if "ts" not in frame.columns:
            frame["ts"] = pd.RangeIndex(len(frame))
        return frame.reset_index(drop=True)

    @staticmethod
    def metrics(trades: list[SimulatedTrade], candle_count: int = 0) -> dict[str, Any]:
        wins = [trade for trade in trades if trade.outcome == "WIN"]
        losses = [trade for trade in trades if trade.outcome == "LOSS"]
        gross_profit = sum(max(0.0, trade.net_pnl) for trade in trades)
        gross_loss = abs(sum(min(0.0, trade.net_pnl) for trade in trades))
        r_values = [trade.r_multiple for trade in trades]
        return {
            "trade_count": len(trades),
            "signal_frequency": 0.0 if candle_count <= 0 else len(trades) / candle_count,
            "win_rate": None if not trades else len(wins) / len(trades),
            "profit_factor": None if gross_loss <= 0.0 else gross_profit / gross_loss,
            "expectancy": None if not trades else sum(trade.net_pnl for trade in trades) / len(trades),
            "max_drawdown": _max_drawdown([trade.net_pnl for trade in trades]),
            "average_R": None if not r_values else sum(r_values) / len(r_values),
            "median_R": None if not r_values else median(r_values),
            "long_win_rate": _side_win_rate(trades, "BUY"),
            "short_win_rate": _side_win_rate(trades, "SELL"),
            "strategy_type_performance": _group_performance(trades, "strategy_type"),
            "regime_performance": _group_performance(trades, "regime"),
            "timeframe_performance": _group_performance(trades, "timeframe"),
        }


def _normalize_signal(signal: Any) -> str | None:
    text = str(signal or "").upper().strip()
    if text in {"BUY", "LONG"}:
        return "BUY"
    if text in {"SELL", "SHORT"}:
        return "SELL"
    return None


def _pnl(direction: str, entry: float, exit_price: float, size: float) -> float:
    if direction == "BUY":
        return (float(exit_price) - float(entry)) * float(size)
    return (float(entry) - float(exit_price)) * float(size)


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _side_win_rate(trades: list[SimulatedTrade], side: str) -> float | None:
    side_trades = [trade for trade in trades if trade.signal == side]
    if not side_trades:
        return None
    return len([trade for trade in side_trades if trade.outcome == "WIN"]) / len(side_trades)


def _group_performance(trades: list[SimulatedTrade], attr: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[SimulatedTrade]] = {}
    for trade in trades:
        key = str(getattr(trade, attr) or "UNKNOWN")
        groups.setdefault(key, []).append(trade)
    return {
        key: {
            "trade_count": len(rows),
            "win_rate": len([trade for trade in rows if trade.outcome == "WIN"]) / len(rows),
            "net_pnl": sum(trade.net_pnl for trade in rows),
            "average_R": sum(trade.r_multiple for trade in rows) / len(rows),
        }
        for key, rows in groups.items()
    }


__all__ = [
    "RealisticSimulatorConfig",
    "RealisticTradeSimulator",
    "SimulatedTrade",
    "SimulationResult",
    "TradeSetup",
]
