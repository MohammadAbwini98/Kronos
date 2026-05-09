from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import DEMO_BASE_URL, ConfigError, TradeExecutionSettings
from trade_execution import (
    CapitalAccount,
    CapitalMarketInfo,
    CapitalTradingApiError,
    CapitalTradingClient,
    ExecutionCandidate,
    MarketNotTradeableError,
    TradeExecutionPolicy,
    TradeExecutionQueueService,
    TradeExecutionRepository,
    TradeExecutionService,
    TradeLifecycleReconciliationService,
    TradeValidationError,
)


class _Response:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = text
        self.content = b"{}" if payload is not None else b""

    def json(self):
        return self._payload


class _Http:
    def __init__(self, responses=None, auth_headers=None):
        self.responses = list(responses or [])
        self.auth_calls = 0
        self.requests = []
        self.auth_headers = auth_headers or {"CST": "cst-1", "X-SECURITY-TOKEN": "sec-1"}

    def post(self, url, json=None, headers=None, timeout=None):
        self.auth_calls += 1
        self.requests.append(("POST", url, json, headers))
        return _Response(200, {"ok": True}, self.auth_headers)

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.requests.append((method, url, json, headers))
        if self.responses:
            return self.responses.pop(0)
        return _Response(200, {})


class _Repo:
    def __init__(self):
        self.existing = None
        self.open_count = 0
        self.daily_count = 0
        self.loss = Decimal("0")

    def get_trade_by_signal(self, signal_id):
        return self.existing

    def open_trade_count(self, account):
        return self.open_count

    def daily_trade_count(self, account):
        return self.daily_count

    def daily_loss(self, account):
        return self.loss


class _ExecutionRepo(_Repo):
    def __init__(self):
        super().__init__()
        self.trade_id = 99
        self.updated_trades = []
        self.attempts = []
        self.events = []

    def upsert_candidate(self, candidate):
        return 7

    def save_account_snapshot(self, account, *, open_positions=0):
        self.open_positions = open_positions

    def insert_or_get_pending_trade(self, candidate, candidate_id, plan):
        return self.trade_id

    def get_trade_by_id(self, trade_id):
        return {
            "id": trade_id,
            "signal_id": "sig-1",
            "deal_id": "deal-1",
            "symbol": "ETHUSD",
            "epic": "ETHUSD",
            "requested_size": Decimal("0.05"),
            "executed_size": Decimal("0.05"),
            "created_at": datetime(2026, 5, 8, 20, 0, tzinfo=timezone.utc),
            "opened_at": datetime(2026, 5, 8, 20, 1, tzinfo=timezone.utc),
        }

    def update_trade(self, trade_id, **fields):
        self.updated_trades.append((trade_id, fields))

    def insert_attempt(self, **fields):
        self.attempts.append(fields)

    def insert_event(self, **fields):
        self.events.append(fields)


class _ReconciliationRepo:
    def __init__(self, trades):
        self.trades = trades
        self.updated_trades = []

    def reconciliation_trades(self):
        return self.trades

    def update_trade(self, trade_id, **fields):
        self.updated_trades.append((trade_id, fields))


class _Client:
    is_demo_environment = True

    def __init__(self):
        self.account = CapitalAccount(
            account_id="acc-1",
            account_name="DEMOAI",
            status="ENABLED",
            is_demo=True,
            preferred=True,
        )
        self.market = CapitalMarketInfo(
            epic="ETHUSD",
            symbol="ETHUSD",
            instrument_name="Ethereum",
            currency="USD",
            tradeable=True,
            bid=Decimal("2999.95"),
            offer=Decimal("3000.05"),
            decimal_places=2,
            min_deal_size=Decimal("0.01"),
            min_size_increment=Decimal("0.01"),
            min_stop_or_profit_distance=Decimal("0"),
            min_stop_or_profit_distance_unit="",
        )

    def ensure_demo_ready(self):
        return self.account

    def get_market_info(self, epic):
        return self.market

    def get_open_positions(self):
        return []

    def get_transaction_history(self, **kwargs):
        return []

    def get_activity_history(self, **kwargs):
        return []


class _PositionsClient(_Client):
    def __init__(self, positions):
        super().__init__()
        self.positions = positions

    def get_open_positions(self):
        return self.positions


class _TransactionClient(_Client):
    def __init__(self, transactions):
        super().__init__()
        self.transactions = transactions
        self.transaction_requests = []

    def get_transaction_history(self, **kwargs):
        self.transaction_requests.append(kwargs)
        return self.transactions


def _settings(**overrides):
    payload = dict(
        api_base_url=DEMO_BASE_URL,
        api_key="key",
        identifier="user",
        password="pass",
        demo_account_name="DEMOAI",
        auto_execute_signals=True,
        default_trade_size=0.05,
        max_concurrent_open_trades=2,
        max_daily_trades=5,
        max_daily_loss=100,
        min_confidence=0.55,
        capital_eth_epic="ETHUSD",
    )
    payload.update(overrides)
    return TradeExecutionSettings(**payload)


def _candidate(**overrides):
    payload = dict(
        signal_id="sig-1",
        run_id="run-1",
        source_model="Kronos",
        symbol="ETHUSD",
        epic="ETHUSD",
        timeframe="MINUTE_5",
        direction="BUY",
        recommended_entry=Decimal("3000"),
        stop_loss=Decimal("2990"),
        take_profit=Decimal("3020"),
        confidence=Decimal("0.75"),
        generated_at_utc=datetime.now(timezone.utc),
        metadata={"raw_signal": "LONG"},
    )
    payload.update(overrides)
    return ExecutionCandidate(**payload)


class CapitalTradingClientTests(unittest.TestCase):
    def test_authenticates_and_stores_session_tokens(self):
        http = _Http()
        client = CapitalTradingClient(_settings(), http=http)

        cst, security = client.authenticate()

        self.assertEqual("cst-1", cst)
        self.assertEqual("sec-1", security)
        self.assertEqual(1, http.auth_calls)

    def test_blocks_non_demo_base_url(self):
        with self.assertRaises(ConfigError):
            CapitalTradingClient(_settings(api_base_url="https://api-capital.backend-capital.com/api/v1"))

    def test_resolves_configured_demo_account(self):
        http = _Http(
            responses=[
                _Response(200, {"accounts": [{"accountId": "acc-1", "accountName": "DEMOAI", "status": "ENABLED", "preferred": True, "isDemo": True}]}),
            ]
        )
        client = CapitalTradingClient(_settings(), http=http)

        account = client.ensure_demo_ready()

        self.assertEqual("DEMOAI", account.account_name)
        self.assertTrue(account.is_demo)

    def test_resolves_demo_api_account_when_provider_omits_demo_flag(self):
        http = _Http(
            responses=[
                _Response(200, {"accounts": [{"accountId": "acc-1", "accountName": "DEMOAI", "status": "ENABLED", "preferred": True, "accountType": "CFD"}]}),
            ]
        )
        client = CapitalTradingClient(_settings(), http=http)

        account = client.ensure_demo_ready()

        self.assertEqual("DEMOAI", account.account_name)
        self.assertTrue(account.is_demo)

    def test_retries_401_after_reauth(self):
        http = _Http(
            responses=[
                _Response(401, text="expired"),
                _Response(200, {"accounts": [{"accountId": "acc-1", "accountName": "DEMOAI", "status": "ENABLED", "preferred": True, "isDemo": True}]}),
            ]
        )
        client = CapitalTradingClient(_settings(), http=http)

        account = client.ensure_demo_ready()

        self.assertEqual("DEMOAI", account.account_name)
        self.assertEqual(2, http.auth_calls)

    def test_submits_position_and_confirms_deal(self):
        http = _Http(
            responses=[
                _Response(200, {"dealReference": "ref-1"}),
                _Response(200, {"dealStatus": "ACCEPTED", "dealId": "deal-1", "level": 3001, "size": 0.05}),
            ]
        )
        client = CapitalTradingClient(_settings(), http=http)
        plan = type("Plan", (), {"candidate": _candidate(), "size": Decimal("0.05"), "stop_level": Decimal("2990"), "profit_level": Decimal("3020")})()

        opened = client.place_position(plan)
        confirm = client.confirm_deal(opened["dealReference"])

        self.assertEqual("ref-1", opened["dealReference"])
        self.assertEqual("deal-1", confirm["dealId"])
        self.assertEqual("POST", http.requests[-2][0])
        self.assertIn("/positions", http.requests[-2][1])
        self.assertIn("/confirms/ref-1", http.requests[-1][1])

    def test_fetches_trade_transaction_history(self):
        http = _Http(
            responses=[
                _Response(200, {"accounts": [{"accountId": "acc-1", "accountName": "DEMOAI", "status": "ENABLED", "preferred": True, "isDemo": True}]}),
                _Response(200, {"transactions": [{"transactionType": "TRADE", "reference": "tx-1"}]}),
            ]
        )
        client = CapitalTradingClient(_settings(), http=http)

        rows = client.get_transaction_history(transaction_type="TRADE", last_period_seconds=3600)

        self.assertEqual("tx-1", rows[0]["reference"])
        self.assertIn("/history/transactions?", http.requests[-1][1])
        self.assertIn("lastPeriod=3600", http.requests[-1][1])
        self.assertIn("type=TRADE", http.requests[-1][1])


class TradeExecutionPolicyTests(unittest.TestCase):
    def test_maps_long_and_short_to_buy_sell(self):
        long_candidate = TradeExecutionRepository._candidate_from_row(
            {"signal_id": "l", "run_id": "l", "signal": "LONG", "symbol": "ETHUSD", "epic": "ETHUSD", "resolution": "MINUTE_5"}
        )
        short_candidate = TradeExecutionRepository._candidate_from_row(
            {"signal_id": "s", "run_id": "s", "signal": "SHORT", "symbol": "ETHUSD", "epic": "ETHUSD", "resolution": "MINUTE_5"}
        )
        held_up_candidate = TradeExecutionRepository._candidate_from_row(
            {"signal_id": "h", "run_id": "h", "signal": "HOLD", "direction": "UP", "symbol": "ETHUSD", "epic": "ETHUSD", "resolution": "MINUTE_5"}
        )

        self.assertEqual("BUY", long_candidate.direction)
        self.assertEqual("SELL", short_candidate.direction)
        self.assertEqual("NO_TRADE", held_up_candidate.direction)
        self.assertFalse(held_up_candidate.is_actionable)

    def test_ignores_hold_and_no_trade(self):
        queue = TradeExecutionQueueService(settings=_settings(), repository=_Repo(), service=object())
        result = queue.enqueue(_candidate(direction="NO_TRADE", metadata={"raw_signal": "NO_TRADE"}))

        self.assertFalse(result["accepted"])
        self.assertEqual("SKIPPED", result["status"])

    def test_ignores_hold_even_when_direction_points_up(self):
        queue = TradeExecutionQueueService(settings=_settings(), repository=_Repo(), service=object())
        result = queue.enqueue(_candidate(direction="BUY", metadata={"raw_signal": "HOLD"}))

        self.assertFalse(result["accepted"])
        self.assertEqual("SKIPPED", result["status"])
        self.assertEqual("NonActionableSignal", result["failure_reason"])

    def test_allows_validation_hold_status_for_demo_execution(self):
        policy = TradeExecutionPolicy(_settings(), _Client(), _Repo())

        plan = policy.evaluate(_candidate(metadata={"raw_signal": "LONG", "validation_status": "HOLD"}))

        self.assertEqual("BUY", plan.candidate.direction)
        self.assertIn("did not block demo execution", plan.validation_note)

    def test_rejects_stale_signal(self):
        policy = TradeExecutionPolicy(_settings(), _Client(), _Repo())

        with self.assertRaises(TradeValidationError):
            policy.evaluate(_candidate(generated_at_utc=datetime.now(timezone.utc) - timedelta(hours=2)))

    def test_allows_low_confidence_signal_for_demo_execution(self):
        policy = TradeExecutionPolicy(_settings(), _Client(), _Repo())

        plan = policy.evaluate(_candidate(confidence=Decimal("0.2")))

        self.assertEqual("BUY", plan.candidate.direction)
        self.assertIn("confidence 0.2 did not block", plan.validation_note)

    def test_derives_levels_when_stored_sl_tp_do_not_match_execution_side(self):
        policy = TradeExecutionPolicy(_settings(), _Client(), _Repo())

        plan = policy.evaluate(_candidate(stop_loss=Decimal("3010"), take_profit=Decimal("2990")))

        self.assertLess(plan.stop_level, plan.market_entry)
        self.assertGreater(plan.profit_level, plan.market_entry)

    def test_force_market_execution_reanchors_valid_original_levels(self):
        client = _Client()
        client.market = CapitalMarketInfo(
            epic="ETHUSD",
            symbol="ETHUSD",
            instrument_name="Ethereum",
            currency="USD",
            tradeable=True,
            bid=Decimal("3020"),
            offer=Decimal("3021"),
            decimal_places=2,
            min_deal_size=Decimal("0.01"),
            min_size_increment=Decimal("0.01"),
            min_stop_or_profit_distance=Decimal("0"),
            min_stop_or_profit_distance_unit="",
        )
        policy = TradeExecutionPolicy(_settings(price_tolerance=100), client, _Repo())
        candidate = _candidate(
            direction="SELL",
            recommended_entry=Decimal("3000"),
            stop_loss=Decimal("3010"),
            take_profit=Decimal("2980"),
            metadata={"raw_signal": "SHORT"},
        )

        plan = policy.evaluate(candidate, force_market_execution=True)

        self.assertEqual(Decimal("3030.00"), plan.stop_level)
        self.assertEqual(Decimal("3000.00"), plan.profit_level)
        self.assertTrue(plan.candidate.metadata["manual_force_market_execution"])

    def test_price_tolerance_does_not_block_market_submission(self):
        policy = TradeExecutionPolicy(_settings(price_tolerance=Decimal("0.01")), _Client(), _Repo())

        plan = policy.evaluate(_candidate())

        self.assertEqual(Decimal("3000.05"), plan.candidate.recommended_entry)
        self.assertEqual("3000", plan.candidate.metadata["original_recommended_entry"])

    def test_rejects_directional_hold_with_flat_levels(self):
        policy = TradeExecutionPolicy(_settings(), _Client(), _Repo())
        candidate = _candidate(
            direction="BUY",
            stop_loss=Decimal("3000"),
            take_profit=Decimal("3000"),
            metadata={
                "raw_signal": "HOLD",
                "validation_status": "BLOCKED",
                "expected_move_pct": Decimal("0.2"),
                "cost_threshold_pct": Decimal("0.05"),
            },
        )

        with self.assertRaises(TradeValidationError):
            policy.evaluate(candidate)

    def test_sell_stop_level_respects_percentage_minimum_against_offer(self):
        client = _Client()
        client.market = CapitalMarketInfo(
            epic="ETHUSD",
            symbol="ETHUSD",
            instrument_name="Ethereum",
            currency="USD",
            tradeable=True,
            bid=Decimal("2315.46"),
            offer=Decimal("2317.19"),
            decimal_places=2,
            min_deal_size=Decimal("0.001"),
            min_size_increment=Decimal("0.001"),
            min_stop_or_profit_distance=Decimal("0.01"),
            min_stop_or_profit_distance_unit="PERCENTAGE",
        )
        policy = TradeExecutionPolicy(_settings(price_tolerance=0.1), client, _Repo())
        candidate = _candidate(
            direction="SELL",
            recommended_entry=Decimal("2315.46"),
            stop_loss=Decimal("2316.62"),
            take_profit=Decimal("2314.30"),
            metadata={"raw_signal": "SHORT"},
        )

        plan = policy.evaluate(candidate)

        self.assertGreaterEqual(plan.stop_level, Decimal("2317.52"))
        self.assertEqual(Decimal("2314.30"), plan.profit_level)
        self.assertTrue(plan.candidate.metadata["broker_level_boundary_adjusted"])

    def test_blocks_duplicate_signal_execution(self):
        repo = _Repo()
        repo.existing = {"id": 1, "status": "OPEN"}
        policy = TradeExecutionPolicy(_settings(), _Client(), repo)

        with self.assertRaises(TradeValidationError):
            policy.evaluate(_candidate())

    def test_market_closed_is_retryable_not_terminal_validation(self):
        client = _Client()
        client.market = CapitalMarketInfo(
            epic="ETHUSD",
            symbol="ETHUSD",
            instrument_name="Ethereum",
            currency="USD",
            tradeable=False,
            bid=Decimal("2308.28"),
            offer=Decimal("2310.03"),
            decimal_places=2,
            min_deal_size=Decimal("0.001"),
            min_size_increment=Decimal("0.001"),
            min_stop_or_profit_distance=Decimal("0.01"),
            min_stop_or_profit_distance_unit="PERCENTAGE",
            market_status="CLOSED",
        )
        policy = TradeExecutionPolicy(_settings(), client, _Repo())

        with self.assertRaises(MarketNotTradeableError):
            policy.evaluate(_candidate())


class TradeExecutionServiceTests(unittest.TestCase):
    def test_persists_broker_execution_failure_on_trade_row(self):
        class FailingClient(_Client):
            def place_position(self, plan):
                raise CapitalTradingApiError(
                    'Capital.com HTTP 400 for /positions: {"errorCode":"error.invalid.stoploss.minvalue: 2317.42"}',
                    status_code=400,
                    payload='{"errorCode":"error.invalid.stoploss.minvalue: 2317.42"}',
                )

        repo = _ExecutionRepo()
        service = TradeExecutionService(_settings(max_concurrent_open_trades=2), client=FailingClient(), repository=repo)

        result = service.execute(_candidate(direction="SELL", stop_loss=Decimal("3010"), take_profit=Decimal("2980")))

        self.assertFalse(result.success)
        self.assertEqual("FAILED", result.status)
        self.assertEqual("BrokerExecutionFailed", result.failure_reason)
        self.assertEqual(repo.trade_id, result.executed_trade_id)
        self.assertTrue(any(fields.get("status") == "FAILED" for _, fields in repo.updated_trades))
        self.assertTrue(any(fields.get("stage") == "place_position" and not fields.get("success") for fields in repo.attempts))
        self.assertTrue(any(fields.get("event_type") == "broker_execution_failed" for fields in repo.events))

    def test_market_not_tradeable_requests_queue_retry_without_failed_trade_row(self):
        client = _Client()
        client.market = CapitalMarketInfo(
            epic="ETHUSD",
            symbol="ETHUSD",
            instrument_name="Ethereum",
            currency="USD",
            tradeable=False,
            bid=Decimal("2308.28"),
            offer=Decimal("2310.03"),
            decimal_places=2,
            min_deal_size=Decimal("0.001"),
            min_size_increment=Decimal("0.001"),
            min_stop_or_profit_distance=Decimal("0.01"),
            min_stop_or_profit_distance_unit="PERCENTAGE",
            market_status="CLOSED",
        )
        repo = _ExecutionRepo()
        service = TradeExecutionService(_settings(), client=client, repository=repo)

        result = service.execute(_candidate())

        self.assertFalse(result.success)
        self.assertTrue(result.retry_requested)
        self.assertEqual("QUEUED", result.status)
        self.assertEqual("MarketNotTradeableError", result.failure_reason)
        self.assertFalse(repo.updated_trades)
        self.assertTrue(any(fields.get("event_type") == "execution_retry_requested" for fields in repo.events))

    def test_respects_max_concurrent_open_trades(self):
        repo = _Repo()
        repo.open_count = 2
        policy = TradeExecutionPolicy(_settings(max_concurrent_open_trades=2), _Client(), repo)

        with self.assertRaises(TradeValidationError):
            policy.evaluate(_candidate())

    def test_fetches_transaction_reference_for_executed_trade_deal_id(self):
        repo = _ExecutionRepo()
        client = _TransactionClient(
            [
                {
                    "transactionType": "TRADE",
                    "instrumentName": "ETHUSD",
                    "dealId": "deal-1",
                    "reference": "tx-123",
                    "size": "0.05",
                    "dateUtc": "2026-05-08T20:01:30",
                    "status": "PROCESSED",
                }
            ]
        )
        service = TradeExecutionService(_settings(), client=client, repository=repo)

        result = service.fetch_transaction_reference(executed_trade_id=99)

        self.assertTrue(result["success"])
        self.assertEqual("tx-123", result["transaction_id"])
        self.assertTrue(client.transaction_requests)
        self.assertTrue(any(event.get("event_type") == "transaction_history_lookup" for event in repo.events))

    def test_enriches_executed_trades_with_transaction_reference(self):
        repo = _ExecutionRepo()
        client = _TransactionClient([])
        service = TradeExecutionService(_settings(), client=client, repository=repo)
        trades = [
            {
                "id": 99,
                "signal_id": "sig-1",
                "deal_id": "deal-1",
                "symbol": "ETHUSD",
                "epic": "ETHUSD",
                "requested_size": Decimal("0.05"),
                "executed_size": Decimal("0.05"),
                "opened_at": datetime(2026, 5, 8, 20, 1, tzinfo=timezone.utc),
            }
        ]

        enriched = service.enrich_transaction_references(
            trades,
            transactions=[
                {
                    "transactionType": "TRADE",
                    "instrumentName": "ETHUSD",
                    "dealId": "deal-1",
                    "reference": "tx-123",
                    "size": "0.05",
                    "dateUtc": "2026-05-08T20:01:30",
                }
            ],
        )

        self.assertEqual("tx-123", enriched[0]["transaction_id"])
        self.assertEqual("FOUND", enriched[0]["transaction_lookup_status"])
        self.assertNotIn("transaction_id", trades[0])

    def test_automatic_transaction_enrichment_does_not_infer_unmatched_deal_id(self):
        repo = _ExecutionRepo()
        client = _TransactionClient([])
        service = TradeExecutionService(_settings(), client=client, repository=repo)
        enriched = service.enrich_transaction_references(
            [
                {
                    "id": 99,
                    "signal_id": "sig-1",
                    "deal_id": "deal-1",
                    "symbol": "ETHUSD",
                    "epic": "ETHUSD",
                    "requested_size": Decimal("0.05"),
                    "executed_size": Decimal("0.05"),
                    "opened_at": datetime(2026, 5, 8, 20, 1, tzinfo=timezone.utc),
                }
            ],
            transactions=[
                {
                    "transactionType": "TRADE",
                    "instrumentName": "ETHUSD",
                    "dealId": "different-deal",
                    "reference": "tx-wrong",
                    "size": "0.05",
                    "dateUtc": "2026-05-08T20:01:30",
                }
            ],
        )

        self.assertIsNone(enriched[0]["transaction_id"])
        self.assertEqual("NOT_FOUND", enriched[0]["transaction_lookup_status"])

    def test_enriches_closed_trade_loss_from_stop_loss_activity(self):
        service = TradeExecutionService(_settings(), client=_Client(), repository=_ExecutionRepo())

        enriched = service.enrich_trade_outcomes(
            [
                {
                    "id": 99,
                    "status": "CLOSED",
                    "deal_id": "deal-1",
                    "direction": "BUY",
                    "stop_loss": Decimal("2990"),
                    "take_profit": Decimal("3020"),
                }
            ],
            activities=[
                {
                    "dealId": "deal-1",
                    "source": "SL",
                    "type": "POSITION",
                    "status": "ACCEPTED",
                    "dateUTC": "2026-05-08T20:05:30",
                    "details": {"level": 2990, "stopLevel": 2990, "profitLevel": 3020, "openPrice": 3000},
                }
            ],
        )

        self.assertEqual("LOSS", enriched[0]["trade_outcome"])
        self.assertEqual("SL", enriched[0]["trade_close_source"])

    def test_enriches_closed_trade_win_from_profit_level_match(self):
        service = TradeExecutionService(_settings(), client=_Client(), repository=_ExecutionRepo())

        enriched = service.enrich_trade_outcomes(
            [
                {
                    "id": 99,
                    "status": "CLOSED",
                    "deal_id": "deal-1",
                    "direction": "SELL",
                    "stop_loss": Decimal("3020"),
                    "take_profit": Decimal("2980"),
                }
            ],
            activities=[
                {
                    "dealId": "deal-1",
                    "source": "SYSTEM",
                    "type": "POSITION",
                    "status": "ACCEPTED",
                    "dateUTC": "2026-05-08T20:05:30",
                    "details": {"level": 2980, "stopLevel": 3020, "profitLevel": 2980, "openPrice": 3000},
                }
            ],
        )

        self.assertEqual("WIN", enriched[0]["trade_outcome"])
        self.assertIn("take-profit", enriched[0]["trade_outcome_reason"])

    def test_open_trade_outcome_stays_open(self):
        service = TradeExecutionService(_settings(), client=_Client(), repository=_ExecutionRepo())

        enriched = service.enrich_trade_outcomes([{"id": 99, "status": "OPEN", "deal_id": "deal-1"}], activities=[])

        self.assertEqual("OPEN", enriched[0]["trade_outcome"])


class TradeLifecycleReconciliationServiceTests(unittest.TestCase):
    def test_reopens_recent_closed_trade_when_matching_position_has_related_deal_id(self):
        repo = _ReconciliationRepo(
            [
                {
                    "id": 58,
                    "signal_id": "sig-58",
                    "status": "CLOSED",
                    "deal_id": "confirm-deal",
                    "deal_reference": "order-ref",
                    "epic": "ETHUSD",
                    "direction": "SELL",
                    "requested_size": Decimal("0.05"),
                    "executed_size": Decimal("0.05"),
                    "recommended_entry": Decimal("2312.58"),
                    "actual_entry": Decimal("2312.48"),
                    "stop_loss": Decimal("2314.67"),
                    "take_profit": Decimal("2311.42"),
                    "opened_at": None,
                }
            ]
        )
        client = _PositionsClient(
            [
                {
                    "position": {
                        "dealId": "platform-position-deal",
                        "direction": "SELL",
                        "size": 0.05,
                        "level": 2312.48,
                        "stopLevel": 2314.67,
                        "profitLevel": 2311.42,
                    },
                    "market": {"epic": "ETHUSD"},
                }
            ]
        )
        service = TradeLifecycleReconciliationService(_settings(price_tolerance=0.1), client=client, repository=repo)

        updated = service.run_once()

        self.assertEqual(1, updated)
        self.assertEqual(58, repo.updated_trades[0][0])
        self.assertEqual("OPEN", repo.updated_trades[0][1]["status"])
        self.assertEqual("platform-position-deal", repo.updated_trades[0][1]["deal_id"])


if __name__ == "__main__":
    unittest.main()
