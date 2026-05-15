from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _lines(path: str) -> list[str]:
    return [
        line.strip()
        for line in (ROOT / path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_requirements_files_follow_ai_stack_order_and_scope() -> None:
    plan_order = [
        "base.txt",
        "ml.txt",
        "foundation-models.txt",
        "dev.txt",
    ]
    assert all((ROOT / "requirements" / name).exists() for name in plan_order)
    assert _lines("requirements.txt") == ["-r requirements/base.txt"]
    assert _lines("requirements-dev.txt") == ["-r requirements/base.txt", "-r requirements/dev.txt"]


def test_optional_heavy_dependencies_are_not_in_base_requirements() -> None:
    base = "\n".join(_lines("requirements/base.txt")).lower()
    for package in ["lightgbm", "catboost", "optuna", "torch", "transformers", "accelerate", "safetensors", "arch"]:
        assert package not in base


def test_ml_and_foundation_requirements_match_plan_groups() -> None:
    ml = "\n".join(_lines("requirements/ml.txt")).lower()
    foundation = "\n".join(_lines("requirements/foundation-models.txt")).lower()

    for package in ["scikit-learn", "joblib", "lightgbm", "catboost", "optuna", "arch"]:
        assert package in ml
    for package in ["torch", "transformers", "accelerate", "safetensors"]:
        assert package in foundation
