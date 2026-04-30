from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from config import BridgeSettings, RateLimiter

LOGGER = logging.getLogger(__name__)


class AuthenticationError(RuntimeError):
    """Raised when Capital.com session authentication fails."""


@dataclass
class CapitalSessionTokens:
    cst: str
    security_token: str
    created_at: float


class CapitalAuthenticator:
    def __init__(
        self,
        settings: BridgeSettings,
        http: requests.Session | None = None,
        session_rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.settings = settings
        self.http = http or requests.Session()
        self._session_rate_limiter = session_rate_limiter or RateLimiter(1.0)
        self._tokens: CapitalSessionTokens | None = None

    @property
    def tokens(self) -> CapitalSessionTokens | None:
        return self._tokens

    def authenticate(self) -> CapitalSessionTokens:
        self.settings.ensure_credentials()
        self._session_rate_limiter.wait()
        url = f"{self.settings.base_url}/session"
        body: dict[str, Any] = {
            "identifier": self.settings.identifier,
            "password": self.settings.password,
            "encryptedPassword": self.settings.use_encrypted_password,
        }
        headers = {"X-CAP-API-KEY": self.settings.api_key}
        LOGGER.info("Authenticating Capital.com %s session", self.settings.env)
        response = self.http.post(url, json=body, headers=headers, timeout=20)
        if response.status_code >= 400:
            raise AuthenticationError(
                f"Capital.com authentication failed with HTTP {response.status_code}: {response.text}"
            )
        cst = response.headers.get("CST")
        security_token = response.headers.get("X-SECURITY-TOKEN")
        if not cst or not security_token:
            raise AuthenticationError("Authentication response did not include CST and X-SECURITY-TOKEN headers")
        self._tokens = CapitalSessionTokens(cst=cst, security_token=security_token, created_at=time.time())
        LOGGER.info("Authenticated; session tokens stored in memory")
        return self._tokens

    def auth_headers(self) -> dict[str, str]:
        if self._tokens is None:
            self.authenticate()
        assert self._tokens is not None
        return {"CST": self._tokens.cst, "X-SECURITY-TOKEN": self._tokens.security_token}

    def refresh(self) -> CapitalSessionTokens:
        LOGGER.info("Refreshing Capital.com session")
        return self.authenticate()
