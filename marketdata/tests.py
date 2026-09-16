from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import indicators
from .analysis import build_stock_analysis, get_bars
from .broker.stub_adapter import StubAdapter
from .constants import NIFTY50_INDEX_INTERNAL_ID
from .indicators import Bar
from .models import Candle, Instrument, InstrumentBrokerMapping, WatchlistItem
from .resampling import PlainBar, resample
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

    def test_rolling_vwap_equals_average_price_when_volume_constant(self):
        # Equal volume on every bar means VWAP collapses to a plain average
        # of typical price ((h+l+c)/3), since the weights all cancel out.
        bars = [Bar(high=101.0, low=99.0, close=100.0, volume=1000.0) for _ in range(25)]
        result = indicators.rolling_vwap(bars, period=20)
        self.assertIsNone(result[18])
        self.assertAlmostEqual(result[19], 100.0, places=6)

    def test_rolling_vwap_weights_toward_higher_volume_bars(self):
        bars = [Bar(high=101.0, low=99.0, close=100.0, volume=1.0) for _ in range(19)]
        bars.append(Bar(high=111.0, low=109.0, close=110.0, volume=1000.0))  # one huge-volume outlier
        result = indicators.rolling_vwap(bars, period=20)
        self.assertGreater(result[-1], 105)  # pulled well above the flat ~100 baseline

    def test_rolling_vwap_handles_zero_volume_window(self):
        bars = [Bar(high=101.0, low=99.0, close=100.0, volume=0.0) for _ in range(20)]
        result = indicators.rolling_vwap(bars, period=20)
        self.assertIsNone(result[-1])


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


class ResamplingTest(TestCase):
    """resampling.py is pure Python — no DB needed."""

    def _daily(self, day, o, h, l, c, v):
        return PlainBar(timestamp=datetime(2026, 1, day, tzinfo=dt_timezone.utc), open=o, high=h, low=l, close=c, volume=v)

    def test_resample_weekly_aggregates_ohlcv_correctly(self):
        # Mon 5th .. Fri 9th Jan 2026 is one ISO week.
        daily = [
            self._daily(5, 100, 105, 98, 102, 1000),
            self._daily(6, 102, 110, 101, 108, 1100),
            self._daily(7, 108, 109, 103, 104, 1200),
            self._daily(8, 104, 106, 95, 96, 1300),
            self._daily(9, 96, 100, 90, 99, 1400),
        ]
        weekly = resample(daily, "1w")
        self.assertEqual(len(weekly), 1)
        bar = weekly[0]
        self.assertEqual(bar.open, 100)  # first day's open
        self.assertEqual(bar.high, 110)  # max high across the week
        self.assertEqual(bar.low, 90)    # min low across the week
        self.assertEqual(bar.close, 99)  # last day's close
        self.assertEqual(bar.volume, 6000)
        self.assertEqual(bar.timestamp.date().isoformat(), "2026-01-05")  # that week's Monday

    def test_resample_monthly_groups_by_calendar_month(self):
        daily = [
            self._daily(28, 100, 101, 99, 100, 500),
            self._daily(29, 100, 102, 98, 101, 500),
            self._daily(30, 101, 103, 100, 102, 500),
        ]
        monthly = resample(daily, "1mo")
        self.assertEqual(len(monthly), 1)
        self.assertEqual(monthly[0].timestamp.date().isoformat(), "2026-01-01")

    def test_resample_splits_across_period_boundary(self):
        daily = [self._daily(5, 100, 101, 99, 100, 100), self._daily(12, 100, 101, 99, 100, 100)]  # different ISO weeks
        weekly = resample(daily, "1w")
        self.assertEqual(len(weekly), 2)

    def test_resample_rejects_unknown_period(self):
        with self.assertRaises(ValueError):
            resample([], "1y")


class GetBarsTest(TestCase):
    """get_bars() is the shared real-vs-derived routing used by both the
    stats panel and the chart API — test the routing itself here."""

    def setUp(self):
        self.instrument = Instrument.objects.create(
            internal_id="NSE_EQ_GETBARS", symbol="GETBARS", name="GetBars Co", exchange="NSE",
        )
        base = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=20)
        for i in range(20):
            Candle.objects.create(
                instrument=self.instrument, timeframe="1d", timestamp=base + timedelta(days=i),
                open=100, high=101, low=99, close=100 + i, volume=100, source="stub",
            )

    def test_direct_timeframe_returns_stored_candles(self):
        bars = get_bars(self.instrument, "1d")
        self.assertEqual(len(bars), 20)

    def test_derived_timeframe_resamples_from_daily(self):
        bars = get_bars(self.instrument, "1w")
        self.assertGreater(len(bars), 0)
        self.assertLess(len(bars), 20)  # fewer weekly bars than daily bars

    def test_derived_timeframe_with_no_daily_data_is_empty(self):
        empty_instrument = Instrument.objects.create(
            internal_id="NSE_EQ_NODATA", symbol="NODATA", name="No Data Co", exchange="NSE",
        )
        self.assertEqual(get_bars(empty_instrument, "1w"), [])


class FyersAdapterRetryTest(TestCase):
    """Confirms the 429 retry/backoff added after hitting real rate limits
    during Milestone 2 testing actually retries instead of giving up."""

    @override_settings(FYERS_CLIENT_ID="test-id", FYERS_ACCESS_TOKEN="test-token")
    @patch("marketdata.broker.fyers_adapter.time.sleep")  # don't actually wait in tests
    @patch("marketdata.broker.fyers_adapter.fyersModel.FyersModel")
    def test_retries_on_429_then_succeeds(self, mock_fyers_model, mock_sleep):
        from marketdata.broker.fyers_adapter import FyersAdapter

        mock_client = MagicMock()
        mock_client.history.side_effect = [
            {"s": "error", "code": 429, "message": "request limit reached"},
            {"s": "error", "code": 429, "message": "request limit reached"},
            {"s": "ok", "candles": [[1735689600, 100, 101, 99, 100.5, 1000]]},
        ]
        mock_fyers_model.return_value = mock_client

        adapter = FyersAdapter()
        bars = adapter.get_historical_candles(
            "NSE:TEST-EQ", "1d",
            datetime(2025, 1, 1, tzinfo=dt_timezone.utc), datetime(2025, 1, 2, tzinfo=dt_timezone.utc),
        )

        self.assertEqual(mock_client.history.call_count, 3)
        self.assertEqual(len(bars), 1)

    @override_settings(FYERS_CLIENT_ID="test-id", FYERS_ACCESS_TOKEN="test-token")
    @patch("marketdata.broker.fyers_adapter.fyersModel.FyersModel")
    def test_derived_timeframe_raises_clear_error(self, mock_fyers_model):
        from marketdata.broker.fyers_adapter import FyersAdapter

        adapter = FyersAdapter()
        with self.assertRaises(ValueError):
            adapter.get_historical_candles(
                "NSE:TEST-EQ", "1w",
                datetime(2025, 1, 1, tzinfo=dt_timezone.utc), datetime(2025, 1, 2, tzinfo=dt_timezone.utc),
            )


class WatchlistToggleViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tester2", password="testpass123")
        self.client.force_login(self.user)
        self.instrument = Instrument.objects.create(
            internal_id="NSE_EQ_WATCH", symbol="WATCH", name="Watch Co", exchange="NSE",
        )

    def test_toggle_adds_then_removes(self):
        url = reverse("marketdata:watchlist_toggle")

        response = self.client.post(url, {"internal_id": self.instrument.internal_id})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["watchlisted"])
        self.assertTrue(WatchlistItem.objects.filter(instrument=self.instrument).exists())

        response = self.client.post(url, {"internal_id": self.instrument.internal_id})
        self.assertFalse(response.json()["watchlisted"])
        self.assertFalse(WatchlistItem.objects.filter(instrument=self.instrument).exists())

    def test_toggle_requires_login(self):
        self.client.logout()
        response = self.client.post(reverse("marketdata:watchlist_toggle"), {"internal_id": self.instrument.internal_id})
        self.assertEqual(response.status_code, 302)
