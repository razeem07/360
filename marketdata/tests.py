from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import indicators
from .analysis import build_stock_analysis
from .broker.stub_adapter import StubAdapter
from .constants import NIFTY50_INDEX_INTERNAL_ID
from .indicators import Bar
from .models import Candle, Instrument, InstrumentBrokerMapping
from .services import (
    InstrumentNotMapped,
    get_adapter,
    ingest_historical_candles,
    resolve_broker_symbol,
)


@override_settings(BROKER_ADAPTER="marketdata.broker.stub_adapter.StubAdapter")
class BrokerAbstractionAcceptanceTest(TestCase):
    """
    CLAUDE.md rule 1 / PRD S7 acceptance check: swapping the adapter must be
    a settings change only — no code outside marketdata/ or execution/
    should need touching. This test proves the swap by pointing
    BROKER_ADAPTER at StubAdapter and running a full ingestion through the
    same service functions the Fyers-backed path uses.
    """

    def test_get_adapter_honours_settings(self):
        adapter = get_adapter()
        self.assertIsInstance(adapter, StubAdapter)

    def test_ingestion_works_end_to_end_with_stub_adapter(self):
        instrument = Instrument.objects.create(
            internal_id="NSE_EQ_TEST",
            symbol="TEST",
            name="Test Co",
            exchange="NSE",
        )
        InstrumentBrokerMapping.objects.create(
            instrument=instrument, broker="stub", broker_symbol="NSE:TEST-EQ"
        )

        to_dt = timezone.now()
        from_dt = to_dt - timedelta(days=5)
        count = ingest_historical_candles(instrument, "1d", from_dt, to_dt)

        self.assertGreater(count, 0)
        self.assertEqual(Candle.objects.filter(instrument=instrument, source="stub").count(), count)

    def test_unmapped_instrument_raises_clear_error(self):
        instrument = Instrument.objects.create(
            internal_id="NSE_EQ_UNMAPPED", symbol="UNMAPPED", name="Unmapped Co", exchange="NSE"
        )
        with self.assertRaises(InstrumentNotMapped):
            resolve_broker_symbol(instrument, "stub")


class CandleModelTest(TestCase):
    def test_duplicate_bar_same_source_is_rejected(self):
        instrument = Instrument.objects.create(
            internal_id="NSE_EQ_DUP", symbol="DUP", name="Dup Co", exchange="NSE"
        )
        ts = timezone.now()
        Candle.objects.create(
            instrument=instrument, timeframe="1d", timestamp=ts,
            open=1, high=2, low=0, close=1, volume=100, source="fyers",
        )
        with self.assertRaises(Exception):
            Candle.objects.create(
                instrument=instrument, timeframe="1d", timestamp=ts,
                open=1, high=2, low=0, close=1, volume=100, source="fyers",
            )


class IndicatorsTest(TestCase):
    """indicators.py is pure Python — no DB, no Django app registry needed."""

    def test_sma_basic(self):
        closes = [1, 2, 3, 4, 5]
        result = indicators.sma(closes, 3)
        self.assertEqual(result, [None, None, 2, 3, 4])

    def test_ema_warms_up_then_tracks_trend(self):
        closes = [float(x) for x in range(1, 30)]
        result = indicators.ema(closes, 5)
        self.assertIsNone(result[0])
        self.assertIsNotNone(result[-1])
        self.assertGreater(result[-1], result[10])

    def test_rsi_is_100_for_strictly_increasing_series(self):
        closes = [float(x) for x in range(1, 30)]
        result = indicators.rsi(closes, 14)
        self.assertEqual(result[-1], 100)

    def test_rsi_is_0_for_strictly_decreasing_series(self):
        closes = [float(x) for x in range(30, 1, -1)]
        result = indicators.rsi(closes, 14)
        self.assertEqual(result[-1], 0)

    def test_atr_is_zero_for_flat_series(self):
        bars = [Bar(high=100.0, low=100.0, close=100.0) for _ in range(20)]
        result = indicators.atr(bars, 14)
        self.assertEqual(result[-1], 0)

    def test_macd_lengths_match_input(self):
        closes = [float(x) for x in range(1, 60)]
        result = indicators.macd(closes)
        self.assertEqual(len(result.macd_line), len(closes))
        self.assertEqual(len(result.signal_line), len(closes))
        self.assertEqual(len(result.histogram), len(closes))

    def test_support_resistance_finds_obvious_pivot(self):
        # A clean V-shape: pivot low in the middle.
        closes = list(range(20, 0, -1)) + list(range(1, 21))
        bars = [Bar(high=c + 1, low=c - 1, close=c) for c in closes]
        result = indicators.support_resistance(bars, window=3, lookback=len(bars))
        self.assertTrue(any(s <= 1 for s in result.support))

    def test_classify_trend_insufficient_data(self):
        self.assertEqual(indicators.classify_trend([1.0, 2.0, 3.0]), indicators.TREND_INSUFFICIENT_DATA)

    def test_classify_trend_uptrend(self):
        closes = [float(x) for x in range(1, 100)]
        self.assertEqual(indicators.classify_trend(closes), indicators.TREND_UP)

    def test_classify_trend_downtrend(self):
        closes = [float(x) for x in range(100, 1, -1)]
        self.assertEqual(indicators.classify_trend(closes), indicators.TREND_DOWN)


class StockAnalysisTest(TestCase):
    def _seed_candles(self, instrument, days=60, start_price=100.0, step=1.0, source="stub"):
        base = timezone.now() - timedelta(days=days)
        price = start_price
        for i in range(days):
            ts = base + timedelta(days=i)
            Candle.objects.create(
                instrument=instrument, timeframe="1d", timestamp=ts,
                open=price, high=price + 1, low=price - 1, close=price,
                volume=1000, source=source,
            )
            price += step

    def test_no_data_returns_clear_empty_state(self):
        instrument = Instrument.objects.create(internal_id="NSE_EQ_EMPTY", symbol="EMPTY", name="Empty Co", exchange="NSE")
        result = build_stock_analysis(instrument)
        self.assertFalse(result.has_data)
        self.assertIsNone(result.latest_close)

    def test_relative_strength_notes_missing_index(self):
        instrument = Instrument.objects.create(internal_id="NSE_EQ_RS", symbol="RS", name="RS Co", exchange="NSE")
        self._seed_candles(instrument)
        result = build_stock_analysis(instrument)
        self.assertTrue(result.has_data)
        self.assertIsNone(result.relative_strength)
        self.assertIn("NIFTY 50 index", result.relative_strength_note)

    def test_relative_strength_computed_against_index(self):
        instrument = Instrument.objects.create(internal_id="NSE_EQ_RS2", symbol="RS2", name="RS2 Co", exchange="NSE")
        index = Instrument.objects.create(internal_id=NIFTY50_INDEX_INTERNAL_ID, symbol="NIFTY50", name="NIFTY 50 Index", exchange="NSE")
        self._seed_candles(instrument, step=2.0)  # stock outperforms
        self._seed_candles(index, step=1.0)

        result = build_stock_analysis(instrument)
        self.assertIsNotNone(result.relative_strength)
        self.assertGreater(result.relative_strength, 0)


class StockAnalysisViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tester", password="testpass123")
        self.client.force_login(self.user)
        self.instrument = Instrument.objects.create(
            internal_id="NSE_EQ_VIEWTEST", symbol="VIEWTEST", name="View Test Co", exchange="NSE",
        )
        base = timezone.now() - timedelta(days=10)
        for i in range(10):
            Candle.objects.create(
                instrument=self.instrument, timeframe="1d", timestamp=base + timedelta(days=i),
                open=100, high=101, low=99, close=100 + i, volume=500, source="stub",
            )

    def test_stock_analysis_page_renders(self):
        response = self.client.get(reverse("marketdata:stock_analysis"), {"symbol": self.instrument.internal_id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "VIEWTEST")

    def test_stock_analysis_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("marketdata:stock_analysis"))
        self.assertEqual(response.status_code, 302)

    def test_candle_api_returns_bars_and_overlays(self):
        url = reverse("marketdata:candle_api", kwargs={"internal_id": self.instrument.internal_id})
        response = self.client.get(url, {"timeframe": "1d"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["bars"]), 10)
        self.assertIn("sma20", data)
        self.assertIn("ema50", data)

    def test_candle_api_requires_auth(self):
        self.client.logout()
        url = reverse("marketdata:candle_api", kwargs={"internal_id": self.instrument.internal_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
