from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.views import View
from rest_framework.response import Response
from rest_framework.views import APIView

from . import indicators
from .analysis import build_stock_analysis
from .models import Candle, Instrument

# Only daily candles are ingested by default today; extending this list is a
# one-line change once intraday data has actually been ingested (avoids
# offering a timeframe the chart can only show empty for — PRD §17).
AVAILABLE_TIMEFRAMES = ["1d"]
DEFAULT_TIMEFRAME = "1d"


class StockAnalysisView(LoginRequiredMixin, View):
    login_url = "core:login"

    def get(self, request):
        instruments = Instrument.objects.filter(is_active=True)
        symbol = request.GET.get("symbol")
        instrument = None
        if symbol:
            instrument = instruments.filter(internal_id=symbol).first()
        if instrument is None:
            instrument = instruments.first()

        context = {
            "instruments": instruments,
            "selected_instrument": instrument,
            "timeframe": DEFAULT_TIMEFRAME,
        }
        if instrument is not None:
            context["analysis"] = build_stock_analysis(instrument, DEFAULT_TIMEFRAME)

        return render(request, "marketdata/stock_analysis.html", context)


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

        candles = list(Candle.objects.filter(instrument=instrument, timeframe=timeframe).order_by("timestamp"))
        times = [c.timestamp.strftime("%Y-%m-%d") for c in candles]
        closes = [float(c.close) for c in candles]

        bars = [
            {"time": t, "open": float(c.open), "high": float(c.high), "low": float(c.low), "close": float(c.close), "volume": c.volume}
            for t, c in zip(times, candles)
        ]
        # Overlay series for the chart — reuses the same indicators.py
        # functions build_stock_analysis() uses, so the chart and the stats
        # panel can never disagree with each other.
        sma20 = [
            {"time": t, "value": v} for t, v in zip(times, indicators.sma(closes, 20)) if v is not None
        ]
        ema50 = [
            {"time": t, "value": v} for t, v in zip(times, indicators.ema(closes, 50)) if v is not None
        ]

        return Response({
            "instrument": instrument.internal_id,
            "timeframe": timeframe,
            "bars": bars,
            "sma20": sma20,
            "ema50": ema50,
        })
