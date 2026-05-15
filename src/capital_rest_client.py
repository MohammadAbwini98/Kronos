from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any
from urllib.parse import quote

import orjson
import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from capital_auth import CapitalAuthenticator
from config import (
    BridgeSettings,
    RateLimiter,
    assert_data_only_path,
    load_instrument_settings,
    safe_epic_for_filename,
    validate_price_side,
    validate_resolution,
)
from kronos_mapper import capital_prices_to_kronos_df, save_kronos_csv
from logging_utils import log_event, output_tail, safe_log_dict
from rate_limit_state import (
    RateLimitCooldownError,
    clear_cooldown,
    endpoint_class_for_path,
    ensure_not_cooling_down,
    record_rate_limit,
)

LOGGER = logging.getLogger(__name__)


class CapitalApiError(RuntimeError):
    """Raised for non-recoverable Capital.com API failures."""


class TransientCapitalApiError(CapitalApiError):
    """Raised for retryable Capital.com API failures."""


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError


def save_json(data: Any, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2, default=_json_default))
    return target


def _params_summary(params: dict[str, Any] | None) -> dict[str, Any] | None:
    if params is None:
        return None
    safe = safe_log_dict(params)
    if len(safe) <= 12:
        return safe
    keys = sorted(safe.keys())[:12]
    return {key: safe[key] for key in keys}


class CapitalRestClient:
    def __init__(
        self,
        settings: BridgeSettings,
        authenticator: CapitalAuthenticator | None = None,
        http: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.http = http or requests.Session()
        self.authenticator = authenticator or CapitalAuthenticator(settings, self.http)
        self._rate_limiter = RateLimiter(0.11)

    def authenticate(self) -> None:
        self.authenticator.authenticate()

    @retry(
        retry=retry_if_exception_type(TransientCapitalApiError),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> Any:
        assert_data_only_path(path)
        endpoint_class = endpoint_class_for_path(path)
        ensure_not_cooling_down(endpoint_class)
        url = f"{self.settings.base_url}{path}"
        request_started = time.perf_counter()
        log_event(
            LOGGER,
            logging.INFO,
            "capital.rest.request.start",
            method=method,
            path=path,
            endpoint_class=endpoint_class,
            params_summary=_params_summary(params),
        )
        self._rate_limiter.wait()
        response = self.http.request(
            method=method,
            url=url,
            params=params,
            headers=self.authenticator.auth_headers(),
            timeout=30,
        )
        if response.status_code in {401, 403}:
            log_event(
                LOGGER,
                logging.WARNING,
                "capital.rest.request.retry_auth",
                method=method,
                path=path,
                endpoint_class=endpoint_class,
                status_code=response.status_code,
            )
            self.authenticator.refresh()
            self._rate_limiter.wait()
            response = self.http.request(
                method=method,
                url=url,
                params=params,
                headers=self.authenticator.auth_headers(),
                timeout=30,
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                retry_after_seconds = int(retry_after) if retry_after else 60
            except ValueError:
                retry_after_seconds = 60
            try:
                record_rate_limit(
                    endpoint_class,
                    error=response.text,
                    status_code=429,
                    retry_after_seconds=retry_after_seconds,
                )
            except Exception:  # noqa: BLE001
                LOGGER.debug("Unable to persist Capital.com cooldown state", exc_info=True)
            log_event(
                LOGGER,
                logging.WARNING,
                "capital.rest.request.rate_limited",
                method=method,
                path=path,
                endpoint_class=endpoint_class,
                status_code=429,
                retry_after_seconds=retry_after_seconds,
                duration_ms=int((time.perf_counter() - request_started) * 1000),
                response_size_bytes=len(response.content or b""),
                output_tail=output_tail(response.text),
            )
            log_event(
                LOGGER,
                logging.WARNING,
                "capital.rest.request.cooldown",
                endpoint_class=endpoint_class,
                retry_after_seconds=retry_after_seconds,
            )
            raise RateLimitCooldownError(
                f"Capital.com endpoint class {endpoint_class} entered COOLDOWN after HTTP 429: {response.text}"
            )
        if response.status_code in {408, 425, 500, 502, 503, 504}:
            log_event(
                LOGGER,
                logging.WARNING,
                "capital.rest.request.transient_error",
                method=method,
                path=path,
                endpoint_class=endpoint_class,
                status_code=response.status_code,
                duration_ms=int((time.perf_counter() - request_started) * 1000),
                response_size_bytes=len(response.content or b""),
                output_tail=output_tail(response.text),
            )
            raise TransientCapitalApiError(f"Transient Capital.com HTTP {response.status_code}: {response.text}")
        if response.status_code >= 400:
            log_event(
                LOGGER,
                logging.ERROR,
                "capital.rest.request.error",
                method=method,
                path=path,
                endpoint_class=endpoint_class,
                status_code=response.status_code,
                duration_ms=int((time.perf_counter() - request_started) * 1000),
                response_size_bytes=len(response.content or b""),
                output_tail=output_tail(response.text),
            )
            raise CapitalApiError(f"Capital.com HTTP {response.status_code} for {path}: {response.text}")
        clear_cooldown(endpoint_class)
        log_event(
            LOGGER,
            logging.INFO,
            "capital.rest.request.success",
            method=method,
            path=path,
            endpoint_class=endpoint_class,
            status_code=response.status_code,
            duration_ms=int((time.perf_counter() - request_started) * 1000),
            response_size_bytes=len(response.content or b""),
            params_summary=_params_summary(params),
        )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            log_event(
                LOGGER,
                logging.ERROR,
                "capital.rest.response.non_json",
                method=method,
                path=path,
                endpoint_class=endpoint_class,
                status_code=response.status_code,
                duration_ms=int((time.perf_counter() - request_started) * 1000),
                response_size_bytes=len(response.content or b""),
            )
            raise CapitalApiError(f"Capital.com returned non-JSON response for {path}") from exc

    def ping(self) -> Any:
        return self._request("GET", "/ping")

    def search_markets(self, search_term: str) -> dict[str, Any]:
        return self._request("GET", "/markets", params={"searchTerm": search_term})

    def get_market_details(self, epic: str) -> dict[str, Any]:
        return self._request("GET", f"/markets/{quote(epic, safe='')}")

    def save_market_details(self, epic: str) -> Path:
        details = self.get_market_details(epic)
        path = self.settings.output_dir / f"market_details_{safe_epic_for_filename(epic)}.json"
        return save_json(details, path)

    def resolve_market(self, market: str | None = None, explicit_epic: str | None = None, streaming: bool = False) -> dict[str, Any]:
        if explicit_epic:
            details = self.get_market_details(explicit_epic)
            instrument = details.get("instrument", {})
            LOGGER.info("Selected explicit epic %s (%s)", explicit_epic, instrument.get("name", "unknown instrument"))
            return {"epic": explicit_epic, "instrumentName": instrument.get("name", ""), "details": details}

        if self.settings.default_epic:
            details = self.get_market_details(self.settings.default_epic)
            instrument = details.get("instrument", {})
            LOGGER.info(
                "Selected CAPITAL_DEFAULT_EPIC %s (%s)",
                self.settings.default_epic,
                instrument.get("name", "unknown instrument"),
            )
            return {"epic": self.settings.default_epic, "instrumentName": instrument.get("name", ""), "details": details}

        requested = market or self.settings.default_market_search
        instrument = load_instrument_settings()
        search_terms = []
        for term in (
            requested,
            self.settings.default_market_search,
            instrument.provider_symbol,
            instrument.display_symbol,
            instrument.name,
            instrument.base_asset,
        ):
            if term and term not in search_terms:
                search_terms.append(term)

        candidates: list[dict[str, Any]] = []
        for term in search_terms:
            result = self.search_markets(term)
            markets = result.get("markets") or result.get("marketDetails") or []
            if isinstance(markets, list):
                candidates.extend(markets)
            if candidates:
                break

        if not candidates:
            raise CapitalApiError(f"No Capital.com markets found for {requested!r}")

        selected = self._select_best_market(candidates, streaming=streaming, requested=requested)
        epic = selected.get("epic")
        if not epic:
            raise CapitalApiError("Selected market did not include an epic")
        name = selected.get("instrumentName") or selected.get("name") or selected.get("instrument", {}).get("name", "")
        LOGGER.info("Selected epic %s (%s)", epic, name)
        return {"epic": epic, "instrumentName": name, "searchResult": selected}

    @staticmethod
    def _normalize_market_token(value: Any) -> str:
        text = str(value or "").lower()
        return "".join(ch for ch in text if ch.isalnum())

    @staticmethod
    def _select_best_market(candidates: list[dict[str, Any]], streaming: bool, requested: str | None = None) -> dict[str, Any]:
        instrument = load_instrument_settings()
        keywords = tuple(
            token.lower()
            for token in (
                instrument.display_symbol,
                instrument.provider_symbol,
                instrument.name,
                instrument.base_asset,
            )
            if token
        )
        requested_norm = CapitalRestClient._normalize_market_token(requested)

        def score(market: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
            epic_raw = str(market.get("epic", ""))
            name_raw = str(market.get("instrumentName") or market.get("name") or "")
            epic = epic_raw.lower()
            name = name_raw.lower()
            status = str(market.get("marketStatus", "")).upper()
            stream_ok = bool(market.get("streamingPricesAvailable"))
            text = f"{epic} {name}"
            match_score = max((20 if kw in text else 0 for kw in keywords), default=0)
            requested_score = 0
            if requested_norm:
                epic_norm = CapitalRestClient._normalize_market_token(epic_raw)
                name_norm = CapitalRestClient._normalize_market_token(name_raw)
                if epic_norm == requested_norm:
                    requested_score += 300
                elif requested_norm in epic_norm:
                    requested_score += 100
                if name_norm == requested_norm:
                    requested_score += 220
                elif requested_norm in name_norm:
                    requested_score += 80
            stream_score = 10 if (not streaming or stream_ok) else 0
            status_score = 5 if status == "TRADEABLE" else (2 if status != "CLOSED" else 0)
            length_score = 0
            if requested_norm:
                epic_norm = CapitalRestClient._normalize_market_token(epic_raw)
                length_score = -abs(len(epic_norm) - len(requested_norm))
            return (requested_score, match_score, stream_score, status_score, length_score, epic)

        sorted_candidates = sorted(candidates, key=score, reverse=True)
        selected = sorted_candidates[0]
        if streaming and not selected.get("streamingPricesAvailable"):
            LOGGER.warning("Best matching market does not advertise streamingPricesAvailable=true")
        return selected

    def get_historical_prices(
        self,
        epic: str,
        resolution: str,
        max_points: int | None = 512,
        from_utc: str | None = None,
        to_utc: str | None = None,
        price_side: str | None = None,
        save_outputs: bool = True,
        min_rows: int = 50,
    ) -> pd.DataFrame:
        resolution = validate_resolution(resolution)
        side = validate_price_side(price_side or self.settings.default_price_side)
        params: dict[str, Any] = {"resolution": resolution}
        if max_points is not None:
            if max_points <= 0 or max_points > 1000:
                raise CapitalApiError("max_points must be between 1 and 1000")
            params["max"] = max_points
        if from_utc:
            params["from"] = from_utc
        if to_utc:
            params["to"] = to_utc
        raw = self._request("GET", f"/prices/{quote(epic, safe='')}", params=params)
        if save_outputs:
            save_json(raw, self.settings.output_dir / f"capital_raw_prices_{safe_epic_for_filename(epic)}_{resolution}.json")
        df = capital_prices_to_kronos_df(raw, side, min_rows=min_rows)
        if save_outputs:
            save_kronos_csv(
                df,
                self.settings.output_dir / f"kronos_input_{safe_epic_for_filename(epic)}_{resolution}.csv",
                min_rows=min_rows,
            )
        return df

    def get_client_sentiment(self, epic_or_market_id: str) -> dict[str, Any]:
        return self._request("GET", f"/clientsentiment/{quote(epic_or_market_id, safe='')}")

    def get_client_sentiment_batch(self, market_ids: list[str]) -> dict[str, Any]:
        if not market_ids:
            raise CapitalApiError("market_ids cannot be empty")
        return self._request("GET", "/clientsentiment", params={"marketIds": ",".join(market_ids)})

    def save_client_sentiment(self, epic_or_market_id: str) -> Path:
        try:
            sentiment = self.get_client_sentiment(epic_or_market_id)
        except CapitalApiError:
            sentiment = self.get_client_sentiment_batch([epic_or_market_id])
        path = self.settings.output_dir / f"client_sentiment_{safe_epic_for_filename(epic_or_market_id)}.json"
        return save_json(sentiment, path)
