from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from gold_analyzer.backtesting.performance_metrics import summarize_strategy_backtest
from gold_analyzer.strategy_brain.brain import NullStrategyBrain, StrategyBrain
from gold_analyzer.strategy_brain.context import StrategyContext
from gold_analyzer.strategy_brain.risk import RiskDecision, RiskManager


ContextFactory = Callable[[str, str, pd.Timestamp, pd.DataFrame, dict[str, Any]], StrategyContext]


@dataclass(frozen=True)
class BacktestConfig:
    initial_equity: float = 10_000.0
    slippage_spread_fraction: float = 0.25
    min_slippage: float = 0.0
    minimum_trades_for_approval: int = 100
    minimum_win_rate: float = 0.55
    minimum_profit_factor: float = 1.20
    minimum_expectancy: float = 0.0
    epsilon: float = 1e-12


@dataclass
class BacktestTrade:
    symbol: str
    timeframe: str
    signal: str
    strategy_type: str
    regime: str | None
    opened_at: pd.Timestamp
    entry_reference: float
    entry_fill: float
    stop_loss: float
    take_profit_1: float | None
    take_profit_2: float | None
    position_size: float
    stop_distance: float
    active_stop: float
    tp1_fraction: float
    tp2_fraction: float
    risk_details: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    partials: list[dict[str, Any]] = field(default_factory=list)
    remaining_fraction: float = 1.0
    tp1_hit: bool = False
    tp2_hit: bool = False
    breakeven_armed: bool = False
    breakeven_stop: float | None = None
    bars_held: int = 0
    net_pnl: float = 0.0
    closed_at: pd.Timestamp | None = None
    close_reason: str | None = None
    outcome: str | None = None


@dataclass(frozen=True)
class StrategyBacktestResult:
    initial_equity: float
    ending_equity: float
    trades: list[BacktestTrade]
    blocked_candidates: list[dict[str, Any]]
    summary: dict[str, Any]


class StrategyBrainBacktester:
    def __init__(
        self,
        *,
        brain: StrategyBrain | None = None,
        risk_manager: RiskManager | None = None,
        config: BacktestConfig | None = None,
        context_factory: ContextFactory | None = None,
    ) -> None:
        self.brain = brain or NullStrategyBrain()
        self.risk_manager = risk_manager or RiskManager()
        self.config = config or BacktestConfig()
        self.context_factory = context_factory

    def run(
        self,
        candles: pd.DataFrame,
        *,
        symbol: str = "GOLD",
        timeframe: str = "5m",
        metadata: dict[str, Any] | None = None,
    ) -> StrategyBacktestResult:
        frame = self._normalize_candles(candles)
        equity = float(self.config.initial_equity)
        blocked_candidates: list[dict[str, Any]] = []
        closed_trades: list[BacktestTrade] = []
        open_trade: BacktestTrade | None = None
        daily_losses: dict[pd.Timestamp.date, float] = defaultdict(float)
        consecutive_losses = 0
        last_loss_at: pd.Timestamp | None = None
        base_metadata = dict(metadata or {})

        for index in range(len(frame)):
            row = frame.iloc[index]
            current_ts = pd.to_datetime(row["ts"], utc=True)

            if open_trade is not None:
                self._advance_trade(open_trade, row=row, current_ts=current_ts)
                if open_trade.closed_at is not None:
                    equity += open_trade.net_pnl
                    if open_trade.outcome == "LOSS":
                        daily_losses[current_ts.date()] += abs(open_trade.net_pnl)
                        consecutive_losses += 1
                        last_loss_at = current_ts
                    else:
                        consecutive_losses = 0
                    closed_trades.append(open_trade)
                    open_trade = None

            prefix = frame.iloc[: index + 1].copy()
            runtime_metadata = dict(base_metadata)
            runtime_metadata.update(
                {
                    "account_equity": equity,
                    "daily_loss": daily_losses[current_ts.date()],
                    "consecutive_losses": consecutive_losses,
                    "last_loss_utc": last_loss_at.isoformat() if last_loss_at is not None else None,
                    "spread": self._coerce_float(row.get("spread")) or 0.0,
                    "open_positions": [] if open_trade is None else [{"symbol": symbol, "status": "OPEN"}],
                }
            )

            if open_trade is not None:
                continue

            context = self._build_context(
                symbol=symbol,
                timeframe=timeframe,
                now_utc=current_ts,
                candles=prefix,
                metadata=runtime_metadata,
            )
            candidate = self.brain.generate_candidate(context)
            if candidate is None:
                continue

            risk = self.risk_manager.evaluate(candidate, context)
            if not risk.approved:
                blocked_candidates.append(
                    {
                        "computed_at": current_ts,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "signal": candidate.signal,
                        "strategy_type": candidate.strategy_type,
                        "regime": candidate.regime,
                        "reason": risk.reason,
                        "blocked_by": list(risk.blocked_by),
                        "details": dict(risk.details),
                    }
                )
                continue

            open_trade = self._open_trade(
                symbol=symbol,
                timeframe=timeframe,
                candidate=candidate,
                risk=risk,
                row=row,
                current_ts=current_ts,
            )

        if open_trade is not None:
            last_row = frame.iloc[-1]
            current_ts = pd.to_datetime(last_row["ts"], utc=True)
            self._close_trade(
                open_trade,
                reference_price=float(last_row["close"]),
                current_ts=current_ts,
                reason="END_OF_DATA",
                spread=self._spread(last_row),
                slippage=self._slippage(self._spread(last_row)),
            )
            equity += open_trade.net_pnl
            if open_trade.outcome == "LOSS":
                daily_losses[current_ts.date()] += abs(open_trade.net_pnl)
            closed_trades.append(open_trade)

        summary = self._summary(closed_trades, initial_equity=self.config.initial_equity, ending_equity=equity)
        return StrategyBacktestResult(
            initial_equity=self.config.initial_equity,
            ending_equity=equity,
            trades=closed_trades,
            blocked_candidates=blocked_candidates,
            summary=summary,
        )

    def _build_context(
        self,
        *,
        symbol: str,
        timeframe: str,
        now_utc: pd.Timestamp,
        candles: pd.DataFrame,
        metadata: dict[str, Any],
    ) -> StrategyContext:
        if self.context_factory is not None:
            return self.context_factory(symbol, timeframe, now_utc, candles, metadata)
        return StrategyContext(
            symbol=symbol,
            timeframe=timeframe,
            now_utc=now_utc,
            candles=candles,
            metadata=metadata,
        )

    def _normalize_candles(self, candles: pd.DataFrame) -> pd.DataFrame:
        frame = candles.copy()
        if "ts" not in frame.columns and "timestamps" in frame.columns:
            frame = frame.rename(columns={"timestamps": "ts"})
        required = {"ts", "open", "high", "low", "close"}
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError("Backtest candles missing required columns: " + ", ".join(missing))

        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        frame = frame.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)
        if "spread" not in frame.columns:
            frame["spread"] = 0.0
        return frame

    def _open_trade(
        self,
        *,
        symbol: str,
        timeframe: str,
        candidate,
        risk: RiskDecision,
        row: pd.Series,
        current_ts: pd.Timestamp,
    ) -> BacktestTrade:
        spread = self._spread(row)
        slippage = self._slippage(spread)
        entry_reference = float(candidate.entry_price)
        stop_loss = float(candidate.stop_loss)
        risk_details = dict(risk.details or {})
        take_profit_split = dict(risk_details.get("take_profit_split") or {})
        breakeven_plan = dict((risk_details.get("exit_plan") or {}).get("breakeven") or {})
        entry_fill = self._fill_price(
            signal=candidate.signal,
            reference_price=entry_reference,
            spread=spread,
            slippage=slippage,
            is_entry=True,
        )
        return BacktestTrade(
            symbol=symbol,
            timeframe=timeframe,
            signal=str(candidate.signal),
            strategy_type=str(candidate.strategy_type),
            regime=candidate.regime,
            opened_at=current_ts,
            entry_reference=entry_reference,
            entry_fill=entry_fill,
            stop_loss=stop_loss,
            take_profit_1=self._coerce_float(candidate.take_profit_1),
            take_profit_2=self._coerce_float(candidate.take_profit_2),
            position_size=float(risk.position_size or candidate.position_size or 0.0),
            stop_distance=abs(entry_reference - stop_loss),
            active_stop=stop_loss,
            tp1_fraction=float(take_profit_split.get("tp1_fraction", 0.60)),
            tp2_fraction=float(take_profit_split.get("tp2_fraction", 0.40)),
            risk_details=risk_details,
            metadata=dict(candidate.metadata),
            breakeven_stop=self._coerce_float(breakeven_plan.get("new_stop")),
        )

    def _advance_trade(self, trade: BacktestTrade, *, row: pd.Series, current_ts: pd.Timestamp) -> None:
        if trade.closed_at is not None:
            return

        trade.bars_held += 1
        spread = self._spread(row)
        slippage = self._slippage(spread)
        high = float(row["high"])
        low = float(row["low"])

        if trade.signal == "BUY":
            if (not trade.tp1_hit) and trade.take_profit_1 is not None and high >= trade.take_profit_1:
                self._exit_fraction(trade, fraction=trade.tp1_fraction, reference_price=trade.take_profit_1, reason="TP1", spread=spread, slippage=slippage)
                trade.tp1_hit = True
                self._arm_breakeven(trade)
            if (not trade.breakeven_armed) and high >= (trade.entry_reference + trade.stop_distance):
                self._arm_breakeven(trade)
            if trade.remaining_fraction > self.config.epsilon and trade.take_profit_2 is not None and high >= trade.take_profit_2:
                trade.tp2_hit = True
                self._close_trade(trade, reference_price=trade.take_profit_2, current_ts=current_ts, reason="TP2", spread=spread, slippage=slippage)
                return
            if trade.remaining_fraction > self.config.epsilon and low <= trade.active_stop:
                reason = "BREAKEVEN_STOP" if trade.breakeven_armed and trade.active_stop > trade.stop_loss else "STOP_LOSS"
                self._close_trade(trade, reference_price=trade.active_stop, current_ts=current_ts, reason=reason, spread=spread, slippage=slippage)
                return
        else:
            if (not trade.tp1_hit) and trade.take_profit_1 is not None and low <= trade.take_profit_1:
                self._exit_fraction(trade, fraction=trade.tp1_fraction, reference_price=trade.take_profit_1, reason="TP1", spread=spread, slippage=slippage)
                trade.tp1_hit = True
                self._arm_breakeven(trade)
            if (not trade.breakeven_armed) and low <= (trade.entry_reference - trade.stop_distance):
                self._arm_breakeven(trade)
            if trade.remaining_fraction > self.config.epsilon and trade.take_profit_2 is not None and low <= trade.take_profit_2:
                trade.tp2_hit = True
                self._close_trade(trade, reference_price=trade.take_profit_2, current_ts=current_ts, reason="TP2", spread=spread, slippage=slippage)
                return
            if trade.remaining_fraction > self.config.epsilon and high >= trade.active_stop:
                reason = "BREAKEVEN_STOP" if trade.breakeven_armed and trade.active_stop < trade.stop_loss else "STOP_LOSS"
                self._close_trade(trade, reference_price=trade.active_stop, current_ts=current_ts, reason=reason, spread=spread, slippage=slippage)
                return

    def _arm_breakeven(self, trade: BacktestTrade) -> None:
        trade.breakeven_armed = True
        if trade.breakeven_stop is None:
            return
        if trade.signal == "BUY":
            trade.active_stop = max(trade.active_stop, trade.breakeven_stop)
        else:
            trade.active_stop = min(trade.active_stop, trade.breakeven_stop)

    def _exit_fraction(
        self,
        trade: BacktestTrade,
        *,
        fraction: float,
        reference_price: float,
        reason: str,
        spread: float,
        slippage: float,
    ) -> None:
        fraction_to_close = min(max(fraction, 0.0), trade.remaining_fraction)
        if fraction_to_close <= self.config.epsilon:
            return

        exit_fill = self._fill_price(
            signal=trade.signal,
            reference_price=reference_price,
            spread=spread,
            slippage=slippage,
            is_entry=False,
        )
        size_closed = trade.position_size * fraction_to_close
        pnl = self._pnl(trade.signal, trade.entry_fill, exit_fill, size_closed)
        trade.net_pnl += pnl
        trade.remaining_fraction -= fraction_to_close
        trade.partials.append(
            {
                "reason": reason,
                "fraction": fraction_to_close,
                "reference_price": reference_price,
                "fill_price": exit_fill,
                "pnl": pnl,
            }
        )

    def _close_trade(
        self,
        trade: BacktestTrade,
        *,
        reference_price: float,
        current_ts: pd.Timestamp,
        reason: str,
        spread: float,
        slippage: float,
    ) -> None:
        if trade.closed_at is not None:
            return

        self._exit_fraction(
            trade,
            fraction=trade.remaining_fraction,
            reference_price=reference_price,
            reason=reason,
            spread=spread,
            slippage=slippage,
        )
        trade.closed_at = current_ts
        trade.close_reason = reason
        if trade.net_pnl > self.config.epsilon:
            trade.outcome = "WIN"
        elif trade.net_pnl < -self.config.epsilon:
            trade.outcome = "LOSS"
        else:
            trade.outcome = "BREAKEVEN"

    def _summary(self, trades: list[BacktestTrade], *, initial_equity: float, ending_equity: float) -> dict[str, Any]:
        return summarize_strategy_backtest(
            trades,
            initial_equity=initial_equity,
            ending_equity=ending_equity,
            minimum_trades_for_approval=self.config.minimum_trades_for_approval,
            minimum_win_rate=self.config.minimum_win_rate,
            minimum_profit_factor=self.config.minimum_profit_factor,
            minimum_expectancy=self.config.minimum_expectancy,
            epsilon=self.config.epsilon,
        )

    def _spread(self, row: pd.Series) -> float:
        return self._coerce_float(row.get("spread")) or 0.0

    def _slippage(self, spread: float) -> float:
        return max(spread * self.config.slippage_spread_fraction, self.config.min_slippage)

    def _fill_price(
        self,
        *,
        signal: str,
        reference_price: float,
        spread: float,
        slippage: float,
        is_entry: bool,
    ) -> float:
        half_spread = spread / 2.0
        signal_value = str(signal).upper().strip()
        if signal_value == "BUY":
            return reference_price + half_spread + slippage if is_entry else reference_price - half_spread - slippage
        return reference_price - half_spread - slippage if is_entry else reference_price + half_spread + slippage

    def _pnl(self, signal: str, entry_fill: float, exit_fill: float, size: float) -> float:
        if str(signal).upper().strip() == "BUY":
            return (exit_fill - entry_fill) * size
        return (entry_fill - exit_fill) * size

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


__all__ = [
    "BacktestConfig",
    "BacktestTrade",
    "StrategyBacktestResult",
    "StrategyBrainBacktester",
]