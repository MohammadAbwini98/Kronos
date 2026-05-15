from __future__ import annotations

import sys
from pathlib import Path


def ensure_legacy_src_path() -> None:
    """Allow new package code to reuse the existing ``src`` modules lazily."""

    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if src.exists():
        src_text = str(src)
        if src_text not in sys.path:
            sys.path.insert(0, src_text)
