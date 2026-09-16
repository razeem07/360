from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from rest_framework.response import Response
from rest_framework.views import APIView

from . import indicators
from .analysis import build_stock_analysis, get_bars
from .models import Instrument, WatchlistItem
from .resampling import DERIVED_TIMEFRAMES

# Ordered short -> long; also drives the timeframe tabs in the template.
AVAILABLE_TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d", "1w", "1mo"]
TIMEFRAME_LABELS = {
    "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H",
    "1d": "Daily", "1w": "Weekly", "1mo": "Monthly",
}
DEFAULT_TIMEFRAME = "1d"

# Timeframes coarse enough that one bar per calendar day (at most) is
# guaranteed — safe to key by date string for lightweight-charts. Anything
# finer needs a real UNIX timestamp or same-day bars collide.
_DATE_KEYED_TIMEFRAMES = {"1d", "1w", "1mo"}


def _chart_time(timestamp, timeframe):
    if timeframe in _DATE_KEYED_TIMEFRAMES:
        return timestamp.strftime("%Y-%m-%d")
    return int(timestamp.timestamp())


class StockAnalysisView(LoginRequiredMixin, View):
    login_url = "core:login"

    def get(self, request):
        instruments = Instrument.objects.filter(is_active=True)
        symbol = request.GET.get("symbol")
        timeframe = request.GET.get("timeframe", DEFAULT_TIMEFRAME)
        if timeframe not in AVAILABLE_TIMEFRAMES:
            timeframe = DEFAULT_TIMEFRAME

        instrument = None
        if symbol:
            instrument = instruments.filter(internal_id=symbol).first()
        if instrument is None:
            watchlisted = instruments.filter(watchlist_entry__isnull=False).first()
            instrument = watchlisted or instruments.first()

        watchlist_ids = set(WatchlistItem.objects.values_list("instrument__internal_id", flat=True))

        context = {
            "instruments": instruments,
            "selected_instrument": instrument,
            "timeframe": timeframe,
            "ingest_timeframe": "1d" if timeframe in DERIVED_TIMEFRAMES else timeframe,
            "available_timeframes": [(tf, TIMEFRAME_LABELS[tf]) for tf in AVAILABLE_TIMEFRAMES],
            "watchlist": instruments.filter(internal_id__in=watchlist_ids),
            "watchlist_ids_json": sorted(watchlist_ids),
            "all_instruments_json": [
                {"internal_id": i.internal_id, "symbol": i.symbol, "name": i.name}
                for i in instruments
            ],
        }
        if instrument is not None:
            context["analysis"] = build_stock_analysis(instrument, timeframe)

        return render(request, "marketdata/stock_analysis.html", context)


class WatchlistToggleView(LoginRequiredMixin, View):
    """
    Add/remove one instrument from the (single-user) watchlist. Plain
    Django view + JsonResponse rather than DRF — this is a simple toggle,
    not a resource collection worth an APIView (CandleDataAPIView, which
    actually shapes chart data, is the one place DRF earns its keep here).
    """

    login_url = "core:login"

    def post(self, request):
        internal_id = request.POST.get("internal_id")
        instrument = get_object_or_404(Instrument, internal_id=internal_id)

        existing = WatchlistItem.objects.filter(instrument=instrument).first()
        if existing:
            existing.delete()
            return JsonResponse({"internal_id": internal_id, "watchlisted": False})

        WatchlistItem.objects.create(instrument=instrument)
        return JsonResponse({"internal_id": internal_id, "watchlisted": True})


class CandleDataAPIView(APIView):
    """
    Chart data endpoint (PRD §5's example of where DRF is genuinely needed).
    Returns OHLCV shaped for lightweight-charts' candlestick series.
    Auth is enforced by REST_FRAMEWORK's default IsAuthenticated permission
    (config/settings.py) — a redirect-to-login mixin would be wrong here
    since this returns JSON, not HTML.
    """

    def get(self, request, internal_id):
        instrument = get_object_or_404(Instrument, internal_id=internal_id)
        timeframe = request.GET.get("timeframe", DEFAULT_TIMEFRAME)
        if timeframe not in AVAILABLE_TIMEFRAMES:
            timeframe = DEFAULT_TIMEFRAME

        candles = get_bars(instrument, timeframe)  # shared with build_stock_analysis()
        times = [_chart_time(c.timestamp, timeframe) for c in candles]
        closes = [c.close for c in candles]
        indicator_bars = [
            indicators.Bar(high=c.high, low=c.low, close=c.close, volume=c.volume) for c in candles
        ]

        bars = [
            {"time": t, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
            for t, c in zip(times, candles)
        ]

        def series(values):
            return [{"time": t, "value": v} for t, v in zip(times, values) if v is not None]

        # Overlay series for the chart — reuses the same indicators.py
        # functions build_stock_analysis() uses, so the chart and the stats
        # panel can never disagree with each other.
        return Response({
            "instrument": instrument.internal_id,
            "timeframe": timeframe,
            "bars": bars,
            "sma20": series(indicators.sma(closes, 20)),
            "ema50": series(indicators.ema(closes, 50)),
            "ema200": series(indicators.ema(closes, 200)),
            "vwap20": series(indicators.rolling_vwap(indicator_bars, 20)),
        })
