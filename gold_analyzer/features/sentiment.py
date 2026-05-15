from __future__ import annotations

import pandas as pd


def add_sentiment_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "sentiment" in out.columns:
        out["sentiment_delta"] = pd.to_numeric(out["sentiment"], errors="coerce").diff().fillna(0.0)
    else:
        out["sentiment_delta"] = 0.0
    return out
