"""Dashboard adapters for optional AI forecasting views."""

from .api import ai_ensemble, ai_forecast_validation, ai_forecasts, ai_regime, ai_scorer

__all__ = [
	"ai_forecasts",
	"ai_ensemble",
	"ai_regime",
	"ai_scorer",
	"ai_forecast_validation",
]
