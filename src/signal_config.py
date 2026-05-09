from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any, Mapping


SUPPORTED_BASE_RESOLUTIONS = {
    "MINUTE",
    "MINUTE_5",
    "MINUTE_15",
    "MINUTE_30",
    "HOUR",
    "HOUR_4",
    "DAY",
    "WEEK",
}

SUPPORTED_VALIDATION_TIMEFRAMES = ["MINUTE_15", "MINUTE_30", "HOUR", "HOUR_4"]


@dataclass(frozen=True)
class SignalConfig:
    signal_symbol: str = "ETHUSD"
    signal_resolution: str = "MINUTE_5"
    signal_lookback: int = 512
    signal_pred_len: int = 12
    signal_cost_threshold_pct: float = 0.05
    signal_min_confidence: float = 0.55
    signal_flat_threshold_pct: float = 0.02

    signal_validation_enabled: bool = True
    signal_validation_strict: bool = False
    signal_validation_timeframes: tuple[str, ...] = tuple(SUPPORTED_VALIDATION_TIMEFRAMES)
    signal_require_hour_confirmation: bool = False

    signal_block_on_extreme_volatility: bool = True
    signal_block_on_wide_spread: bool = True
    signal_block_on_low_volume: bool = False
    signal_max_spread_pct: float = 0.08
    signal_min_net_edge_pct: float = 0.05

    signal_score_strong_threshold: float = 85.0
    signal_score_actionable_threshold: float = 70.0
    signal_score_weak_threshold: float = 60.0
    signal_score_watch_threshold: float = 50.0

    signal_atr_extreme_percentile: float = 95.0
    signal_low_volume_zscore: float = -1.0
    signal_low_volume_penalty_points: float = 3.0

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "SIGNAL_SYMBOL": self.signal_symbol,
            "SIGNAL_RESOLUTION": self.signal_resolution,
            "SIGNAL_LOOKBACK": self.signal_lookback,
            "SIGNAL_PRED_LEN": self.signal_pred_len,
            "SIGNAL_COST_THRESHOLD_PCT": self.signal_cost_threshold_pct,
            "SIGNAL_MIN_CONFIDENCE": self.signal_min_confidence,
            "SIGNAL_FLAT_THRESHOLD_PCT": self.signal_flat_threshold_pct,
            "SIGNAL_VALIDATION_ENABLED": self.signal_validation_enabled,
            "SIGNAL_VALIDATION_STRICT": self.signal_validation_strict,
            "SIGNAL_VALIDATION_TIMEFRAMES": list(self.signal_validation_timeframes),
            "SIGNAL_REQUIRE_HOUR_CONFIRMATION": self.signal_require_hour_confirmation,
            "SIGNAL_BLOCK_ON_EXTREME_VOLATILITY": self.signal_block_on_extreme_volatility,
            "SIGNAL_BLOCK_ON_WIDE_SPREAD": self.signal_block_on_wide_spread,
            "SIGNAL_BLOCK_ON_LOW_VOLUME": self.signal_block_on_low_volume,
            "SIGNAL_MAX_SPREAD_PCT": self.signal_max_spread_pct,
            "SIGNAL_MIN_NET_EDGE_PCT": self.signal_min_net_edge_pct,
            "SIGNAL_SCORE_STRONG_THRESHOLD": self.signal_score_strong_threshold,
            "SIGNAL_SCORE_ACTIONABLE_THRESHOLD": self.signal_score_actionable_threshold,
            "SIGNAL_SCORE_WEAK_THRESHOLD": self.signal_score_weak_threshold,
            "SIGNAL_SCORE_WATCH_THRESHOLD": self.signal_score_watch_threshold,
            "SIGNAL_ATR_EXTREME_PERCENTILE": self.signal_atr_extreme_percentile,
            "SIGNAL_LOW_VOLUME_ZSCORE": self.signal_low_volume_zscore,
            "SIGNAL_LOW_VOLUME_PENALTY_POINTS": self.signal_low_volume_penalty_points,
        }
        return payload


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:  # noqa: BLE001
        return default
    if minimum is not None and parsed < minimum:
        return default
    if maximum is not None and parsed > maximum:
        return default
    return parsed


def _parse_float(value: Any, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        parsed = float(str(value).strip())
    except Exception:  # noqa: BLE001
        return default
    if minimum is not None and parsed < minimum:
        return default
    if maximum is not None and parsed > maximum:
        return default
    return parsed


def _parse_symbol(value: Any, default: str) -> str:
    text = str(value).strip().upper() if value is not None else ""
    if not text:
        return default
    return text[:64]


def _parse_resolution(value: Any, default: str) -> str:
    text = str(value).strip().upper() if value is not None else ""
    if text in SUPPORTED_BASE_RESOLUTIONS:
        return text
    return default


def _parse_timeframes(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, (list, tuple, set)):
        tokens = [str(item).strip().upper() for item in value]
    else:
        tokens = [part.strip().upper() for part in str(value).split(",")]
    clean = [token for token in tokens if token in SUPPORTED_VALIDATION_TIMEFRAMES]
    if not clean:
        return default
    # Preserve the canonical ordering for stable scoring and dashboards.
    ordered = [timeframe for timeframe in SUPPORTED_VALIDATION_TIMEFRAMES if timeframe in clean]
    return tuple(ordered)


def _build_source(
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = dict(environ or os.environ)
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                source[str(key)] = value
    return source


def load_signal_config(
    *,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> SignalConfig:
    source = _build_source(environ=environ, overrides=overrides)

    cfg = SignalConfig(
        signal_symbol=_parse_symbol(source.get("SIGNAL_SYMBOL"), "ETHUSD"),
        signal_resolution=_parse_resolution(source.get("SIGNAL_RESOLUTION"), "MINUTE_5"),
        signal_lookback=_parse_int(source.get("SIGNAL_LOOKBACK"), 512, minimum=50, maximum=4096),
        signal_pred_len=_parse_int(source.get("SIGNAL_PRED_LEN"), 12, minimum=1, maximum=240),
        signal_cost_threshold_pct=_parse_float(
            source.get("SIGNAL_COST_THRESHOLD_PCT"),
            0.05,
            minimum=0.0,
            maximum=5.0,
        ),
        signal_min_confidence=_parse_float(
            source.get("SIGNAL_MIN_CONFIDENCE"),
            0.55,
            minimum=0.0,
            maximum=1.0,
        ),
        signal_flat_threshold_pct=_parse_float(
            source.get("SIGNAL_FLAT_THRESHOLD_PCT"),
            0.02,
            minimum=0.0,
            maximum=5.0,
        ),
        signal_validation_enabled=_parse_bool(source.get("SIGNAL_VALIDATION_ENABLED"), True),
        signal_validation_strict=_parse_bool(source.get("SIGNAL_VALIDATION_STRICT"), False),
        signal_validation_timeframes=_parse_timeframes(
            source.get("SIGNAL_VALIDATION_TIMEFRAMES"),
            tuple(SUPPORTED_VALIDATION_TIMEFRAMES),
        ),
        signal_require_hour_confirmation=_parse_bool(source.get("SIGNAL_REQUIRE_HOUR_CONFIRMATION"), False),
        signal_block_on_extreme_volatility=_parse_bool(source.get("SIGNAL_BLOCK_ON_EXTREME_VOLATILITY"), True),
        signal_block_on_wide_spread=_parse_bool(source.get("SIGNAL_BLOCK_ON_WIDE_SPREAD"), True),
        signal_block_on_low_volume=_parse_bool(source.get("SIGNAL_BLOCK_ON_LOW_VOLUME"), False),
        signal_max_spread_pct=_parse_float(
            source.get("SIGNAL_MAX_SPREAD_PCT"),
            0.08,
            minimum=0.0,
            maximum=5.0,
        ),
        signal_min_net_edge_pct=_parse_float(
            source.get("SIGNAL_MIN_NET_EDGE_PCT"),
            0.05,
            minimum=0.0,
            maximum=5.0,
        ),
        signal_score_strong_threshold=_parse_float(
            source.get("SIGNAL_SCORE_STRONG_THRESHOLD"),
            85.0,
            minimum=0.0,
            maximum=100.0,
        ),
        signal_score_actionable_threshold=_parse_float(
            source.get("SIGNAL_SCORE_ACTIONABLE_THRESHOLD"),
            70.0,
            minimum=0.0,
            maximum=100.0,
        ),
        signal_score_weak_threshold=_parse_float(
            source.get("SIGNAL_SCORE_WEAK_THRESHOLD"),
            60.0,
            minimum=0.0,
            maximum=100.0,
        ),
        signal_score_watch_threshold=_parse_float(
            source.get("SIGNAL_SCORE_WATCH_THRESHOLD"),
            50.0,
            minimum=0.0,
            maximum=100.0,
        ),
        signal_atr_extreme_percentile=_parse_float(
            source.get("SIGNAL_ATR_EXTREME_PERCENTILE"),
            95.0,
            minimum=50.0,
            maximum=100.0,
        ),
        signal_low_volume_zscore=_parse_float(
            source.get("SIGNAL_LOW_VOLUME_ZSCORE"),
            -1.0,
            minimum=-10.0,
            maximum=10.0,
        ),
        signal_low_volume_penalty_points=_parse_float(
            source.get("SIGNAL_LOW_VOLUME_PENALTY_POINTS"),
            3.0,
            minimum=0.0,
            maximum=20.0,
        ),
    )

    # Keep threshold ordering valid even when env input is inconsistent.
    strong = max(cfg.signal_score_strong_threshold, cfg.signal_score_actionable_threshold)
    actionable = min(strong, max(cfg.signal_score_actionable_threshold, cfg.signal_score_weak_threshold))
    weak = min(actionable, max(cfg.signal_score_weak_threshold, cfg.signal_score_watch_threshold))
    watch = min(weak, cfg.signal_score_watch_threshold)

    return SignalConfig(
        **{
            **cfg.__dict__,
            "signal_score_strong_threshold": strong,
            "signal_score_actionable_threshold": actionable,
            "signal_score_weak_threshold": weak,
            "signal_score_watch_threshold": watch,
        }
    )


def add_signal_cli_overrides(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--signal-validation-enabled", default=None, help="Override SIGNAL_VALIDATION_ENABLED with true/false.")
    parser.add_argument("--signal-validation-strict", default=None, help="Override SIGNAL_VALIDATION_STRICT with true/false.")
    parser.add_argument("--signal-validation-timeframes", default=None, help="Comma-separated validation timeframes.")
    parser.add_argument("--signal-cost-threshold-pct", type=float, default=None)
    parser.add_argument("--signal-min-confidence", type=float, default=None)
    parser.add_argument("--signal-min-net-edge-pct", type=float, default=None)
    parser.add_argument("--signal-max-spread-pct", type=float, default=None)
    parser.add_argument("--signal-block-on-low-volume", default=None, help="Override SIGNAL_BLOCK_ON_LOW_VOLUME with true/false.")
    parser.add_argument("--signal-low-volume-penalty-points", type=float, default=None)
    parser.add_argument("--signal-require-hour-confirmation", default=None, help="Override SIGNAL_REQUIRE_HOUR_CONFIRMATION with true/false.")
    return parser


def signal_overrides_from_args(args: argparse.Namespace | None) -> dict[str, Any]:
    if args is None:
        return {}
    raw = {
        "SIGNAL_VALIDATION_ENABLED": getattr(args, "signal_validation_enabled", None),
        "SIGNAL_VALIDATION_STRICT": getattr(args, "signal_validation_strict", None),
        "SIGNAL_VALIDATION_TIMEFRAMES": getattr(args, "signal_validation_timeframes", None),
        "SIGNAL_COST_THRESHOLD_PCT": getattr(args, "signal_cost_threshold_pct", None),
        "SIGNAL_MIN_CONFIDENCE": getattr(args, "signal_min_confidence", None),
        "SIGNAL_MIN_NET_EDGE_PCT": getattr(args, "signal_min_net_edge_pct", None),
        "SIGNAL_MAX_SPREAD_PCT": getattr(args, "signal_max_spread_pct", None),
        "SIGNAL_BLOCK_ON_LOW_VOLUME": getattr(args, "signal_block_on_low_volume", None),
        "SIGNAL_LOW_VOLUME_PENALTY_POINTS": getattr(args, "signal_low_volume_penalty_points", None),
        "SIGNAL_REQUIRE_HOUR_CONFIRMATION": getattr(args, "signal_require_hour_confirmation", None),
    }
    return {key: value for key, value in raw.items() if value is not None}
