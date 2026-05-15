from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_PATHS = [
    ROOT / "README.md",
    ROOT / "config.example.yaml",
    ROOT / ".env.example",
    ROOT / "docs",
]

ASSIGNMENT_RE = re.compile(
    r"(?im)^\s*(?P<key>"
    r"CAPITAL_API_KEY|CAPITAL_EMAIL|CAPITAL_IDENTIFIER|CAPITAL_PASSWORD|CAPITAL_ACCOUNT_ID|"
    r"TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID|DB_URL|POSTGRES_DSN|DB_PASSWORD|EMAIL_SMTP_PASS"
    r")[ \t]*[:=][ \t]*(?P<value>[^ \t\r\n#]*)"
)
URL_SECRET_RE = re.compile(r"(?i)(postgres(?:ql)?://[^@\s]+:[^@\s]+@|bot\d{7,}:[A-Za-z0-9_-]{20,})")
LOCAL_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\Users\\(?!<|YOUR_|example|user)[^\s)`'\"]+")

SAFE_VALUES = {
    "",
    "''",
    '""',
    "<placeholder>",
    "<your-value>",
    "<your-secret>",
    "changeme",
    "example",
    "localhost",
}


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for path in SCAN_PATHS:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(
                child
                for child in path.rglob("*")
                if child.is_file() and child.suffix.lower() in {".md", ".txt", ".yaml", ".yml", ".env", ""}
            )
    return sorted(set(files))


def _looks_secret(value: str) -> bool:
    value = value.strip().strip("'\"")
    if value.lower() in SAFE_VALUES:
        return False
    if value.startswith("${") or value.startswith("<"):
        return False
    if value.upper().endswith("_ENV"):
        return False
    if value.startswith("http://localhost") or value.startswith("https://demo-api-capital.backend-capital.com"):
        return False
    if len(value) >= 12:
        return True
    return bool(re.search(r"\d{5,}|[A-Za-z0-9_-]{16,}", value))


def main() -> int:
    findings: list[str] = []
    for path in _iter_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT)
        for match in ASSIGNMENT_RE.finditer(text):
            value = match.group("value")
            if _looks_secret(value):
                findings.append(f"{rel}: real-looking value for {match.group('key')}")
        if URL_SECRET_RE.search(text):
            findings.append(f"{rel}: real-looking credential URL/token")
        if LOCAL_PATH_RE.search(text):
            findings.append(f"{rel}: local absolute user path")

    if findings:
        print("Secret scan failed:")
        for finding in findings:
            print(f" - {finding}")
        return 1
    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
