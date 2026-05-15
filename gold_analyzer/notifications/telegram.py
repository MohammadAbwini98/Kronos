from __future__ import annotations

import os
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class TelegramMessageResult:
    ok: bool
    detail: str


class TelegramNotifier:
    def __init__(self, *, bot_token: str | None = None, chat_id: str | None = None, timeout_seconds: int = 8) -> None:
        self.bot_token = bot_token if bot_token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")
        self.timeout_seconds = max(1, int(timeout_seconds))

    def send(self, text: str) -> TelegramMessageResult:
        if not self.bot_token or not self.chat_id:
            return TelegramMessageResult(ok=False, detail="Telegram credentials are not configured.")
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            response = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": str(text)},
                timeout=self.timeout_seconds,
            )
            if response.ok:
                return TelegramMessageResult(ok=True, detail="sent")
            return TelegramMessageResult(ok=False, detail=f"http_{response.status_code}")
        except Exception as exc:  # noqa: BLE001
            return TelegramMessageResult(ok=False, detail=str(exc))
