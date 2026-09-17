import json
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from marketdata.models import Candle, Instrument
from marketdata.resampling import PlainBar

from .models import Strategy, StrategyVersion
from .rules import RuleError, evaluate_ruleset


def _bar(day, close, high=None, low=None, volume=1000):
    return PlainBar(
        timestamp=datetime(2026, 1, 1, tzinfo=dt_timezone.utc) + timedelta(days=day),
        open=close, high=high if high is not None else close + 1,
        low=low if low is not None else close - 1, close=close, volume=volume,
    )


class RuleEngineTest(TestCase):
    """strategies/rules.py is pure Python — no DB needed."""

    def test_simple_comparison_against_fixed_value(self):
        bars = [_bar(i, close) for i, close in enumerate([10, 20, 30, 5])]
        ruleset = {"all": [{"left": {"indicator": "close"}, "operator": "<", "right": {"value": 15}}]}
        self.assertEqual(evaluate_ruleset(ruleset, bars), [True, False, False, True])

    def test_all_combinator_requires_every_condition(self):
        bars = [_bar(i, close, volume=vol) for i, (close, vol) in enumerate([(10, 100), (10, 500), (5, 500)])]
        ruleset = {"all": [
            {"left": {"indicator": "close"}, "operator": "<", "right": {"value": 20}},
            {"left": {"indicator": "volume"}, "operator": ">", "right": {"value": 200}},
        ]}
        self.assertEqual(evaluate_ruleset(ruleset, bars), [False, True, True])

    def test_any_combinator_needs_one_condition(self):
        bars = [_bar(i, close) for i, close in enumerate([100, 5, 100])]
        ruleset = {"any": [{"left": {"indicator": "close"}, "operator": "<", "right": {"value": 10}}]}
        self.assertEqual(evaluate_ruleset(ruleset, bars), [False, True, False])

    def test_crosses_above(self):
        # A rising close crossing above a flat threshold of 50.
        bars = [_bar(i, close) for i, close in enumerate([40, 45, 55, 60])]
        ruleset = {"all": [{"left": {"indicator": "close"}, "operator": "crosses_above", "right": {"value": 50}}]}
        self.assertEqual(evaluate_ruleset(ruleset, bars), [False, False, True, False])

    def test_crosses_below(self):
        bars = [_bar(i, close) for i, close in enumerate([60, 55, 45, 40])]
        ruleset = {"all": [{"left": {"indicator": "close"}, "operator": "crosses_below", "right": {"value": 50}}]}
        self.assertEqual(evaluate_ruleset(ruleset, bars), [False, False, True, False])

    def test_two_indicators_compared_directly(self):
        closes = [float(x) for x in list(range(1, 25)) + list(range(24, 0, -1))]  # rise then fall
        bars = [_bar(i, c) for i, c in enumerate(closes)]
        ruleset = {"all": [{"left": {"indicator": "ema", "params": {"period": 3}}, "operator": ">",
                             "right": {"indicator": "ema", "params": {"period": 10}}}]}
        result = evaluate_ruleset(ruleset, bars)
        # Fast EMA should be above slow EMA while rising, and eventually flip false once it turns down.
        self.assertTrue(any(result))
        self.assertFalse(all(result))

    def test_warmup_period_is_false_not_error(self):
        bars = [_bar(i, 10 + i) for i in range(5)]  # only 5 bars, way under RSI's 14+1 warm-up
        ruleset = {"all": [{"left": {"indicator": "rsi"}, "operator": "<", "right": {"value": 30}}]}
        result = evaluate_ruleset(ruleset, bars)
        self.assertEqual(result, [False] * 5)

    def test_missing_combinator_key_raises(self):
        with self.assertRaises(RuleError):
            evaluate_ruleset({"conditions": []}, [_bar(0, 10)])

    def test_unsupported_operator_raises(self):
        bars = [_bar(0, 10)]
        ruleset = {"all": [{"left": {"indicator": "close"}, "operator": "~=", "right": {"value": 1}}]}
        with self.assertRaises(RuleError):
            evaluate_ruleset(ruleset, bars)

    def test_unsupported_indicator_raises(self):
        bars = [_bar(0, 10)]
        ruleset = {"all": [{"left": {"indicator": "nonsense"}, "operator": "<", "right": {"value": 1}}]}
        with self.assertRaises(RuleError):
            evaluate_ruleset(ruleset, bars)

    def test_empty_bars_returns_empty(self):
        self.assertEqual(evaluate_ruleset({"all": [{"left": {"indicator": "close"}, "operator": "<", "right": {"value": 1}}]}, []), [])


class StrategyModelTest(TestCase):
    def test_latest_version_property(self):
        strategy = Strategy.objects.create(name="Test Strat", category="custom")
        v1 = StrategyVersion.objects.create(
            strategy=strategy, version_number=1,
            entry_rules={"all": []}, exit_rules={"all": []},
            stop_loss={"type": "pct", "value": 2}, target={"type": "pct", "value": 4},
            position_sizing={"type": "fixed_pct", "value": 10},
        )
        self.assertEqual(strategy.latest_version, v1)

        v2 = StrategyVersion.objects.create(
            strategy=strategy, version_number=2,
            entry_rules={"all": []}, exit_rules={"all": []},
            stop_loss={"type": "pct", "value": 3}, target={"type": "pct", "value": 5},
            position_sizing={"type": "fixed_pct", "value": 10},
        )
        self.assertEqual(strategy.latest_version, v2)

    def test_duplicate_version_number_rejected(self):
        strategy = Strategy.objects.create(name="Dup Test", category="custom")
        StrategyVersion.objects.create(
            strategy=strategy, version_number=1, entry_rules={"all": []}, exit_rules={"all": []},
            stop_loss={"type": "pct", "value": 2}, target={"type": "pct", "value": 4},
            position_sizing={"type": "fixed_pct", "value": 10},
        )
        with self.assertRaises(Exception):
            StrategyVersion.objects.create(
                strategy=strategy, version_number=1, entry_rules={"all": []}, exit_rules={"all": []},
                stop_loss={"type": "pct", "value": 2}, target={"type": "pct", "value": 4},
                position_sizing={"type": "fixed_pct", "value": 10},
            )


class StrategyViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="stratuser", password="testpass123")
        self.client.force_login(self.user)

    def _post_data(self, **overrides):
        data = {
            "name": "My Strategy", "category": "momentum",
            "entry_rules_json": json.dumps({"all": [{"left": {"indicator": "rsi"}, "operator": "<", "right": {"value": 30}}]}),
            "exit_rules_json": json.dumps({"all": [{"left": {"indicator": "rsi"}, "operator": ">", "right": {"value": 70}}]}),
            "stop_loss_type": "pct", "stop_loss_value": "2",
            "target_type": "pct", "target_value": "4",
            "position_sizing_type": "fixed_pct", "position_sizing_value": "10",
            "max_positions": "1", "max_capital_pct": "100",
            "max_risk_per_trade_pct": "1", "min_risk_reward": "1",
        }
        data.update(overrides)
        return data

    def test_list_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("strategies:list"))
        self.assertEqual(response.status_code, 302)

    def test_create_strategy(self):
        response = self.client.post(reverse("strategies:create"), self._post_data())
        self.assertEqual(response.status_code, 302)
        strategy = Strategy.objects.get(name="My Strategy")
        self.assertEqual(strategy.latest_version.version_number, 1)
        self.assertEqual(strategy.latest_version.entry_rules["all"][0]["left"]["indicator"], "rsi")

    def test_edit_unlocked_version_updates_in_place(self):
        self.client.post(reverse("strategies:create"), self._post_data())
        strategy = Strategy.objects.get(name="My Strategy")

        self.client.post(reverse("strategies:edit", kwargs={"strategy_id": strategy.id}), self._post_data(notes="updated"))
        strategy.refresh_from_db()
        self.assertEqual(strategy.versions.count(), 1)
        self.assertEqual(strategy.latest_version.notes, "updated")

    def test_edit_locked_version_creates_new_version(self):
        self.client.post(reverse("strategies:create"), self._post_data())
        strategy = Strategy.objects.get(name="My Strategy")
        version = strategy.latest_version
        version.is_locked = True
        version.save()

        self.client.post(reverse("strategies:edit", kwargs={"strategy_id": strategy.id}), self._post_data(notes="v2 notes"))
        self.assertEqual(strategy.versions.count(), 2)
        self.assertEqual(strategy.latest_version.version_number, 2)
        self.assertEqual(strategy.latest_version.notes, "v2 notes")
        self.assertTrue(StrategyVersion.objects.get(strategy=strategy, version_number=1).is_locked)

    def test_duplicate_creates_new_strategy_with_unique_name(self):
        self.client.post(reverse("strategies:create"), self._post_data())
        strategy = Strategy.objects.get(name="My Strategy")

        response = self.client.post(reverse("strategies:duplicate", kwargs={"strategy_id": strategy.id}))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Strategy.objects.filter(name="My Strategy (copy)").exists())

    def test_set_status_active_then_archived(self):
        self.client.post(reverse("strategies:create"), self._post_data())
        strategy = Strategy.objects.get(name="My Strategy")

        self.client.post(reverse("strategies:set_status", kwargs={"strategy_id": strategy.id, "new_status": "active"}))
        strategy.refresh_from_db()
        self.assertEqual(strategy.status, "active")

        self.client.post(reverse("strategies:set_status", kwargs={"strategy_id": strategy.id, "new_status": "archived"}))
        strategy.refresh_from_db()
        self.assertEqual(strategy.status, "archived")

    def test_preview_api_returns_signals(self):
        self.client.post(reverse("strategies:create"), self._post_data())
        strategy = Strategy.objects.get(name="My Strategy")

        instrument = Instrument.objects.create(internal_id="NSE_EQ_PREVTEST", symbol="PREVTEST", name="Preview Test", exchange="NSE")
        base = timezone.now() - timedelta(days=30)
        for i in range(30):
            Candle.objects.create(
                instrument=instrument, timeframe="1d", timestamp=base + timedelta(days=i),
                open=100, high=101, low=99, close=100 - i if i < 15 else 100 - 15 + i, volume=500, source="stub",
            )

        url = reverse("strategies:preview_api", kwargs={"strategy_id": strategy.id})
        response = self.client.get(url, {"symbol": instrument.internal_id, "timeframe": "1d"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("entry_times", data)
        self.assertIn("exit_times", data)

    def test_malformed_rules_json_returns_clear_error(self):
        response = self.client.post(reverse("strategies:create"), self._post_data(entry_rules_json="not json"))
        self.assertEqual(response.status_code, 400)

    def test_detail_page_falls_back_when_symbol_param_does_not_match(self):
        # Regression: a corrupted/stale ?symbol= (e.g. from the M&M
        # unescaped-query-string bug) must fall back to the first
        # instrument instead of crashing with selected_instrument=None.
        self.client.post(reverse("strategies:create"), self._post_data())
        strategy = Strategy.objects.get(name="My Strategy")
        Instrument.objects.create(internal_id="NSE_EQ_FALLBACKTEST", symbol="FALLBACKTEST", name="Fallback Co", exchange="NSE")

        url = reverse("strategies:detail", kwargs={"strategy_id": strategy.id})
        response = self.client.get(url, {"symbol": "NSE_EQ_DOES_NOT_EXIST"})
        self.assertEqual(response.status_code, 200)

    def test_detail_page_handles_symbol_with_ampersand(self):
        self.client.post(reverse("strategies:create"), self._post_data())
        strategy = Strategy.objects.get(name="My Strategy")
        Instrument.objects.create(internal_id="NSE_EQ_M&M", symbol="M&M", name="Mahindra & Mahindra", exchange="NSE")

        url = reverse("strategies:detail", kwargs={"strategy_id": strategy.id})
        response = self.client.get(url, {"symbol": "NSE_EQ_M&M"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "symbol=NSE_EQ_M%26M&timeframe=")
