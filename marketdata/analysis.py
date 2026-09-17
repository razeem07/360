"""
Glue between the ORM (Candle queryset) and the pure indicator functions in
indicators.py. This is the only place in marketdata/ that both touches the
database and calls indicators — indicators.py itself stays DB-free and
independently testable.

get_bars() is the single place that decides whether a timeframe is queried
directly or resampled from daily candles (marketdata/resampling.py) — both
build_stock_analysis() (the stats panel) and CandleDataAPIView (the chart)
call it, so they can never disagree about what a "weekly bar" is.
"""

from dataclasses import dataclass

from . import indicators
from .constants import NIFTY50_INDEX_INTERNAL_ID
from .indicators import Bar
from .models import Candle, Instrument
from .resampling import DERIVED_TIMEFRAMES, PlainBar, resample

RELATIVE_STRENGTH_LOOKBACK_DAYS = 20

# Timeframes coarse enough that one bar per calendar day (at most) is
# guaranteed — safe to key by date string for lightweight-charts. Anything
# finer needs a real UNIX timestamp or same-day bars collide. Shared by
# every chart-shaping consumer (marketdata's own candle API, strategies'
# signal-preview markers, ...) so a strategy's entry/exit markers always
# land on the exact same time key as the candle they fired on.
DATE_KEYED_TIMEFRAMES = {"1d", "1w", "1mo"}


def chart_time(timestamp, timeframe: str):
    if timeframe in DATE_KEYED_TIMEFRAMES:
        return timestamp.strftime("%Y-%m-%d")
    return int(timestamp.timestamp())


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
    ema200: float | None
    vwap20: float | None
    trend: str
    support: list[float]
    resistance: list[float]
    relative_strength: float | None
    relative_strength_note: str | None


def _to_plain_bar(c: Candle) -> PlainBar:
    return PlainBar(
        timestamp=c.timestamp, open=float(c.open), high=float(c.high),
        low=float(c.low), close=float(c.close), volume=c.volume,
    )


def get_bars(instrument: Instrument, timeframe: str) -> list[PlainBar]:
    """
    The single entry point for "give me this instrument's bars at this
    timeframe" — resamples from '1d' for derived timeframes (weekly/
    monthly), otherwise queries Candle directly at the requested timeframe.
    """
    if timeframe in DERIVED_TIMEFRAMES:
        daily = Candle.objects.filter(instrument=instrument, timeframe="1d").order_by("timestamp")
        return resample([_to_plain_bar(c) for c in daily], timeframe)

    candles = Candle.objects.filter(instrument=instrument, timeframe=timeframe).order_by("timestamp")
    return [_to_plain_bar(c) for c in candles]


def _closes(bars: list[PlainBar]) -> list[float]:
    return [b.close for b in bars]


def _period_return(bars: list[PlainBar], lookback_periods: int) -> float | None:
    if len(bars) < lookback_periods + 1:
        return None
    start = bars[-(lookback_periods + 1)]
    end = bars[-1]
    if start.close == 0:
        return None
    return (end.close - start.close) / start.close * 100


def _relative_strength(instrument: Instrument, bars: list[PlainBar], timeframe: str) -> tuple[float | None, str | None]:
    if instrument.internal_id == NIFTY50_INDEX_INTERNAL_ID:
        return None, "This is the benchmark index itself."

    stock_return = _period_return(bars, RELATIVE_STRENGTH_LOOKBACK_DAYS)
    if stock_return is None:
        return None, "Not enough history for this stock yet."

    try:
        index_instrument = Instrument.objects.get(internal_id=NIFTY50_INDEX_INTERNAL_ID)
    except Instrument.DoesNotExist:
        return None, "NIFTY 50 index instrument not seeded — run seed_instruments."

    index_bars = get_bars(index_instrument, timeframe)
    index_return = _period_return(index_bars, RELATIVE_STRENGTH_LOOKBACK_DAYS)
    if index_return is None:
        return None, "NIFTY 50 index has no ingested candles yet — run ingest_candles for it."

    return round(stock_return - index_return, 2), None


def build_stock_analysis(instrument: Instrument, timeframe: str = "1d") -> StockAnalysis:
    candles = get_bars(instrument, timeframe)

    if not candles:
        return StockAnalysis(
            instrument=instrument, has_data=False, bar_count=0,
            latest_close=None, latest_volume=None, rsi14=None, atr14=None,
            macd_line=None, macd_signal=None, macd_histogram=None,
            sma20=None, sma50=None, ema50=None, ema200=None, vwap20=None, trend=indicators.TREND_INSUFFICIENT_DATA,
            support=[], resistance=[], relative_strength=None,
            relative_strength_note="No candles ingested for this instrument yet.",
        )

    closes = _closes(candles)
    bars = [
        Bar(high=c.high, low=c.low, close=c.close, volume=c.volume)
        for c in candles
    ]

    rsi_series = indicators.rsi(closes)
    atr_series = indicators.atr(bars)
    macd_result = indicators.macd(closes)
    sma20_series = indicators.sma(closes, 20)
    sma50_series = indicators.sma(closes, 50)
    ema50_series = indicators.ema(closes, 50)
    ema200_series = indicators.ema(closes, 200)
    vwap20_series = indicators.rolling_vwap(bars, 20)
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
        ema200=ema200_series[-1],
        vwap20=vwap20_series[-1],
        trend=trend,
        support=sr.support,
        resistance=sr.resistance,
        relative_strength=relative_strength,
        relative_strength_note=relative_strength_note,
    )
