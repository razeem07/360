"""
Glue between the ORM (Candle queryset) and the pure indicator functions in
indicators.py. This is the only place in marketdata/ that both touches the
database and calls indicators — indicators.py itself stays DB-free and
independently testable.
"""

from dataclasses import dataclass

from . import indicators
from .constants import NIFTY50_INDEX_INTERNAL_ID
from .indicators import Bar
from .models import Candle, Instrument

RELATIVE_STRENGTH_LOOKBACK_DAYS = 20


@dataclass
class StockAnalysis:
    instrument: Instrument
    has_data: bool
    bar_count: int
    latest_close: float | None
    latest_volume: int | None
    rsi14: float | None
    atr14: float | None
    macd_line: float | None
    macd_signal: float | None
    macd_histogram: float | None
    sma20: float | None
    sma50: float | None
    ema50: float | None
    trend: str
    support: list[float]
    resistance: list[float]
    relative_strength: float | None
    relative_strength_note: str | None


def _bars_for(instrument: Instrument, timeframe: str) -> list[Candle]:
    return list(
        Candle.objects.filter(instrument=instrument, timeframe=timeframe).order_by("timestamp")
    )


def _closes(candles: list[Candle]) -> list[float]:
    return [float(c.close) for c in candles]


def _period_return(candles: list[Candle], lookback_days: int) -> float | None:
    if len(candles) < lookback_days + 1:
        return None
    start = candles[-(lookback_days + 1)]
    end = candles[-1]
    if start.close == 0:
        return None
    return float((end.close - start.close) / start.close * 100)


def _relative_strength(instrument: Instrument, candles: list[Candle], timeframe: str) -> tuple[float | None, str | None]:
    if instrument.internal_id == NIFTY50_INDEX_INTERNAL_ID:
        return None, "This is the benchmark index itself."

    stock_return = _period_return(candles, RELATIVE_STRENGTH_LOOKBACK_DAYS)
    if stock_return is None:
        return None, "Not enough history for this stock yet."

    try:
        index_instrument = Instrument.objects.get(internal_id=NIFTY50_INDEX_INTERNAL_ID)
    except Instrument.DoesNotExist:
        return None, "NIFTY 50 index instrument not seeded — run seed_instruments."

    index_candles = _bars_for(index_instrument, timeframe)
    index_return = _period_return(index_candles, RELATIVE_STRENGTH_LOOKBACK_DAYS)
    if index_return is None:
        return None, "NIFTY 50 index has no ingested candles yet — run ingest_candles for it."

    return round(stock_return - index_return, 2), None


def build_stock_analysis(instrument: Instrument, timeframe: str = "1d") -> StockAnalysis:
    candles = _bars_for(instrument, timeframe)

    if not candles:
        return StockAnalysis(
            instrument=instrument, has_data=False, bar_count=0,
            latest_close=None, latest_volume=None, rsi14=None, atr14=None,
            macd_line=None, macd_signal=None, macd_histogram=None,
            sma20=None, sma50=None, ema50=None, trend=indicators.TREND_INSUFFICIENT_DATA,
            support=[], resistance=[], relative_strength=None,
            relative_strength_note="No candles ingested for this instrument yet.",
        )

    closes = _closes(candles)
    bars = [Bar(high=float(c.high), low=float(c.low), close=float(c.close)) for c in candles]

    rsi_series = indicators.rsi(closes)
    atr_series = indicators.atr(bars)
    macd_result = indicators.macd(closes)
    sma20_series = indicators.sma(closes, 20)
    sma50_series = indicators.sma(closes, 50)
    ema50_series = indicators.ema(closes, 50)
    trend = indicators.classify_trend(closes)
    sr = indicators.support_resistance(bars)
    relative_strength, relative_strength_note = _relative_strength(instrument, candles, timeframe)

    return StockAnalysis(
        instrument=instrument,
        has_data=True,
        bar_count=len(candles),
        latest_close=closes[-1],
        latest_volume=candles[-1].volume,
        rsi14=rsi_series[-1],
        atr14=atr_series[-1],
        macd_line=macd_result.macd_line[-1],
        macd_signal=macd_result.signal_line[-1],
        macd_histogram=macd_result.histogram[-1],
        sma20=sma20_series[-1],
        sma50=sma50_series[-1],
        ema50=ema50_series[-1],
        trend=trend,
        support=sr.support,
        resistance=sr.resistance,
        relative_strength=relative_strength,
        relative_strength_note=relative_strength_note,
    )
