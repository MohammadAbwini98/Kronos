from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KRONOS_MODEL_ROOT = ROOT / "KRONOS-MODEL"

for candidate in (ROOT, KRONOS_MODEL_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)
