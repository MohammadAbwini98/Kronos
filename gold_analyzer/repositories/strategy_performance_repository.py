from __future__ import annotations

from statistics import pstdev
from typing import Any

from psycopg.types.json import Jsonb

from gold_analyzer.db.repositories._base import Repository
from gold_analyzer.repositories._json_safe import finite_or_none, int_or_none, sanitize_json


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS strategy_performance (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    strategy_type TEXT,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lookback_trades INTEGER,
    win_rate DOUBLE PRECISION,
    profit_factor DOUBLE PRECISION,
    expectancy DOUBLE PRECISION,
    avg_win DOUBLE PRECISION,
    avg_loss DOUBLE PRECISION,
    max_drawdown DOUBLE PRECISION,
    sharpe DOUBLE PRECISION,
    details_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_strategy_performance_symbol_tf_time
    ON strategy_performance(symbol, timeframe, evaluated_at DESC);
"""


class StrategyPerformanceRepository(Repository):
    CREATE_TABLE_SQL = CREATE_TABLE_SQL

    @classmethod
    def creation_sql(cls) -> str:
        return cls.CREATE_TABLE_SQL

    def ensure_tables(self) -> None:
        with self.connect() as conn:
            conn.execute(self.CREATE_TABLE_SQL)

    def save_summary(self, summary: dict[str, Any]) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO strategy_performance(
                    symbol, timeframe, strategy_type, lookback_trades,
                    win_rate, profit_factor, expectancy, avg_win, avg_loss,
                    max_drawdown, sharpe, details_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    summary["symbol"],
                    summary["timeframe"],
                    summary.get("strategy_type"),
                    int_or_none(summary.get("lookback_trades")),
                    finite_or_none(summary.get("win_rate")),
                    finite_or_none(summary.get("profit_factor")),
                    finite_or_none(summary.get("expectancy")),
                    finite_or_none(summary.get("avg_win")),
                    finite_or_none(summary.get("avg_loss")),
                    finite_or_none(summary.get("max_drawdown")),
                    finite_or_none(summary.get("sharpe")),
                    Jsonb(sanitize_json(summary.get("details") or summary.get("details_json") or {})),
                ),
            ).fetchone()
        return int(row["id"] if isinstance(row, dict) else row[0])

    def list_latest(self, *, symbol: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM strategy_performance
                WHERE (%s::text IS NULL OR symbol = %s)
                  AND (%s::text IS NULL OR timeframe = %s)
                ORDER BY evaluated_at DESC, id DESC
                LIMIT %s
                """,
                (symbol, symbol, timeframe, timeframe, max(1, int(limit))),
            ).fetchall()
        return {"rows": [dict(row) for row in rows]}

    def executed_trade_summary(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
        minimum_trades_for_approval: int = 100,
        minimum_win_rate: float = 0.55,
        minimum_profit_factor: float = 1.20,
        minimum_expectancy: float = 0.0,
    ) -> dict[str, Any] | None:
        """Build a strategy-performance snapshot from finalized demo executions.

        Strategy Brain performance can be empty during rollout even though the
        execution table already contains the most decision-relevant feedback.
        This keeps the dashboard honest by exposing those outcomes with the same
        approval gates used by backtests.
        """

        symbol_value = str(symbol or "").strip().upper() or None
        timeframe_value = _normalize_timeframe(timeframe)
        timeframe_aliases = _timeframe_aliases(timeframe_value)

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol, epic, timeframe, final_outcome, net_pnl, closed_at, updated_at, created_at
                FROM executed_trades
                WHERE status = 'CLOSED'
                  AND final_outcome IN ('WIN', 'LOSS', 'BREAKEVEN')
                  AND net_pnl IS NOT NULL
                  AND (%s::text IS NULL OR UPPER(symbol) = %s OR UPPER(epic) = %s)
                  AND (%s::text[] IS NULL OR UPPER(timeframe) = ANY(%s::text[]))
                ORDER BY COALESCE(closed_at, updated_at, created_at), id
                """,
                (
                    symbol_value,
                    symbol_value,
                    symbol_value,
                    timeframe_aliases,
                    timeframe_aliases,
                ),
            ).fetchall()

        trades = [dict(row) for row in rows]
        if not trades:
            return None

        wins = [float(row["net_pnl"]) for row in trades if str(row.get("final_outcome") or "").upper() == "WIN"]
        losses = [float(row["net_pnl"]) for row in trades if str(row.get("final_outcome") or "").upper() == "LOSS"]
        breakevens = [float(row["net_pnl"]) for row in trades if str(row.get("final_outcome") or "").upper() == "BREAKEVEN"]
        pnls = [float(row["net_pnl"]) for row in trades]
        win_loss_count = len(wins) + len(losses)
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        win_rate = None if win_loss_count == 0 else len(wins) / win_loss_count
        profit_factor = None if gross_loss <= 1e-12 else gross_profit / gross_loss
        expectancy = None if not pnls else sum(pnls) / len(pnls)
        max_drawdown = _max_drawdown(pnls)
        sharpe = _simple_sharpe(pnls)

        gates = [
            _gate("minimum_trades", len(pnls), minimum_trades_for_approval, len(pnls) >= minimum_trades_for_approval),
            _gate("minimum_win_rate", win_rate, minimum_win_rate, (win_rate or 0.0) >= minimum_win_rate),
            _gate("minimum_profit_factor", profit_factor, minimum_profit_factor, (profit_factor or 0.0) >= minimum_profit_factor),
            _gate("minimum_expectancy", expectancy, minimum_expectancy, (expectancy or 0.0) > minimum_expectancy),
        ]
        approved_for_paper = all(gate["status"] == "PASS" for gate in gates)
        first_trade = trades[0].get("closed_at") or trades[0].get("updated_at") or trades[0].get("created_at")
        last_trade = trades[-1].get("closed_at") or trades[-1].get("updated_at") or trades[-1].get("created_at")

        return {
            "symbol": symbol_value or str(trades[-1].get("symbol") or trades[-1].get("epic") or "UNKNOWN").upper(),
            "timeframe": timeframe_value or _normalize_timeframe(trades[-1].get("timeframe")) or str(trades[-1].get("timeframe") or "UNKNOWN"),
            "strategy_type": "executed_trade_proxy",
            "lookback_trades": len(pnls),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "avg_win": None if not wins else sum(wins) / len(wins),
            "avg_loss": None if not losses else sum(losses) / len(losses),
            "max_drawdown": max_drawdown,
            "sharpe": sharpe,
            "details": {
                "source": "executed_trades",
                "metric_definition": "Closed demo executions with final_outcome in WIN/LOSS/BREAKEVEN and net_pnl present.",
                "wins": len(wins),
                "losses": len(losses),
                "breakevens": len(breakevens),
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "total_net_pnl": sum(pnls),
                "first_trade_at": first_trade,
                "last_trade_at": last_trade,
                "approved_for_paper": approved_for_paper,
                "approval_gates": gates,
                "minimums": {
                    "minimum_trades_for_approval": minimum_trades_for_approval,
                    "minimum_win_rate": minimum_win_rate,
                    "minimum_profit_factor": minimum_profit_factor,
                    "minimum_expectancy": minimum_expectancy,
                },
            },
        }


def _normalize_timeframe(value: object) -> str | None:
    text = str(value or "").strip()
    raw = text.upper().replace("-", "").replace("_", "").replace(" ", "")
    aliases = {
        "1M": "1m",
        "M1": "1m",
        "MINUTE": "1m",
        "MINUTE1": "1m",
        "5M": "5m",
        "M5": "5m",
        "MINUTE5": "5m",
        "15M": "15m",
        "M15": "15m",
        "MINUTE15": "15m",
        "30M": "30m",
        "M30": "30m",
        "MINUTE30": "30m",
        "1H": "1h",
        "H1": "1h",
        "HOUR": "1h",
        "4H": "4h",
        "H4": "4h",
        "HOUR4": "4h",
        "1D": "1d",
        "D": "1d",
        "DAY": "1d",
    }
    if not raw:
        return None
    return aliases.get(raw, text.lower())


def _timeframe_aliases(value: str | None) -> list[str] | None:
    if not value:
        return None
    aliases = {
        "1m": ["1M", "M1", "MINUTE"],
        "5m": ["5M", "M5", "MINUTE_5"],
        "15m": ["15M", "M15", "MINUTE_15"],
        "30m": ["30M", "M30", "MINUTE_30"],
        "1h": ["1H", "H1", "HOUR"],
        "4h": ["4H", "H4", "HOUR_4"],
        "1d": ["1D", "D", "DAY"],
    }
    return sorted({value.upper(), *(aliases.get(value, []))})


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    return max_drawdown


def _simple_sharpe(pnls: list[float]) -> float | None:
    if len(pnls) < 2:
        return None
    volatility = pstdev(pnls)
    if volatility <= 1e-12:
        return None
    return (sum(pnls) / len(pnls)) / volatility


def _gate(name: str, metric_value: float | int | None, threshold_value: float | int, passed: bool) -> dict[str, Any]:
    return {
        "gate_name": name,
        "status": "PASS" if passed else "FAIL",
        "metric_value": metric_value,
        "threshold_value": threshold_value,
    }
