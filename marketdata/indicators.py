"""
Technical indicators — pure functions only. No Django/ORM/broker imports, so
these are testable in complete isolation (PRD §10 lists "indicators" as part
of marketdata/'s job, alongside the candle aggregator, for the same reason).

Every series-returning function returns a list the same length as its input,
padded with None for the warm-up period where there isn't enough history to
compute a real value yet — never silently substituting a wrong number
(PRD §19).
"""

from dataclasses import dataclass
from typing import NamedTuple

# Plain floats only (not Decimal) — EMA's smoothing factor is a float, and
# mixing Decimal with float arithmetic raises TypeError. Fine for descriptive
# TA stats; unlike the fee model (CLAUDE.md rule 4), precision loss here has
# no money consequence. Callers pulling from the DB convert Decimal -> float
# at the boundary (see analysis.py).
Number = float


class Bar(NamedTuple):
    """Minimal OHLC(V) bar for indicators that need more than the close price."""

    high: Number
    low: Number
    close: Number
    volume: Number = 0.0


def sma(closes: list[Number], period: int) -> list[Number | None]:
    out: list[Number | None] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        out[i] = sum(window) / period
    return out


def ema(closes: list[Number], period: int) -> list[Number | None]:
    out: list[Number | None] = [None] * len(closes)
    if len(closes) < period:
        return out
    k = 2 / (period + 1)
    seed = sum(closes[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(closes)):
        prev = closes[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: list[Number], period: int = 14) -> list[Number | None]:
    """Wilder's RSI."""
    out: list[Number | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return out

    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = _rsi_from_averages(avg_gain, avg_loss)

    return out


def _rsi_from_averages(avg_gain: Number, avg_loss: Number) -> Number:
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


@dataclass(frozen=True)
class MACDResult:
    macd_line: list[Number | None]
    signal_line: list[Number | None]
    histogram: list[Number | None]


def macd(closes: list[Number], fast: int = 12, slow: int = 26, signal: int = 9) -> MACDResult:
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    macd_line: list[Number | None] = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(ema_fast, ema_slow)
    ]

    # EMA of the MACD line itself, skipping the leading Nones.
    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    signal_line: list[Number | None] = [None] * len(closes)
    if first_valid is not None:
        valid_values = [v for v in macd_line if v is not None]
        signal_on_valid = ema(valid_values, signal)
        for offset, value in enumerate(signal_on_valid):
            signal_line[first_valid + offset] = value

    histogram: list[Number | None] = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(macd_line, signal_line)
    ]

    return MACDResult(macd_line=macd_line, signal_line=signal_line, histogram=histogram)


def atr(bars: list[Bar], period: int = 14) -> list[Number | None]:
    """Wilder's ATR — needs high/low/close, not just close."""
    out: list[Number | None] = [None] * len(bars)
    if len(bars) < period + 1:
        return out

    true_ranges = []
    for i in range(1, len(bars)):
        high, low, prev_close = bars[i].high, bars[i].low, bars[i - 1].close
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    avg_tr = sum(true_ranges[:period]) / period
    out[period] = avg_tr
    for i in range(period, len(true_ranges)):
        avg_tr = (avg_tr * (period - 1) + true_ranges[i]) / period
        out[i + 1] = avg_tr

    return out


@dataclass(frozen=True)
class SupportResistance:
    support: list[Number]
    resistance: list[Number]


def support_resistance(bars: list[Bar], window: int = 5, lookback: int = 60, max_levels: int = 3) -> SupportResistance:
    """
    Fractal-style pivots: a bar is a pivot high/low if its high/low is the
    most extreme within `window` bars on each side. Returns the most recent
    `max_levels` of each, nearest-first.
    """
    recent = bars[-lookback:] if lookback else bars
    pivot_highs, pivot_lows = [], []

    for i in range(window, len(recent) - window):
        segment = recent[i - window : i + window + 1]
        if recent[i].high == max(b.high for b in segment):
            pivot_highs.append(recent[i].high)
        if recent[i].low == min(b.low for b in segment):
            pivot_lows.append(recent[i].low)

    return SupportResistance(
        support=list(reversed(pivot_lows[-max_levels:])),
        resistance=list(reversed(pivot_highs[-max_levels:])),
    )


def rolling_vwap(bars: list[Bar], period: int = 20) -> list[Number | None]:
    """
    Rolling N-bar volume-weighted average price, using typical price
    (high+low+close)/3. NOTE: classic VWAP resets every session and needs
    intraday bars — we only ingest daily candles today, so this is a
    rolling window over daily bars, not a true session VWAP. Labelled
    "Rolling VWAP" everywhere it's shown so it isn't mistaken for the
    intraday version.
    """
    out: list[Number | None] = [None] * len(bars)
    for i in range(period - 1, len(bars)):
        window = bars[i - period + 1 : i + 1]
        total_volume = sum(b.volume for b in window)
        if total_volume == 0:
            continue
        weighted_sum = sum(((b.high + b.low + b.close) / 3) * b.volume for b in window)
        out[i] = weighted_sum / total_volume
    return out


TREND_UP = "uptrend"
TREND_DOWN = "downtrend"
TREND_SIDEWAYS = "sideways"
TREND_INSUFFICIENT_DATA = "insufficient_data"


def classify_trend(closes: list[Number], fast_period: int = 20, slow_period: int = 50) -> str:
    """
    Deterministic rule, not AI (PRD §24: AI is never authoritative — this
    isn't AI at all, just a documented rule): compares the latest fast/slow
    SMA and the current close against them.
    """
    if len(closes) < slow_period:
        return TREND_INSUFFICIENT_DATA

    fast_sma = sma(closes, fast_period)[-1]
    slow_sma = sma(closes, slow_period)[-1]
    last_close = closes[-1]

    if fast_sma is None or slow_sma is None:
        return TREND_INSUFFICIENT_DATA

    if last_close > fast_sma > slow_sma:
        return TREND_UP
    if last_close < fast_sma < slow_sma:
        return TREND_DOWN
    return TREND_SIDEWAYS
