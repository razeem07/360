"""
Resample daily bars into weekly/monthly bars. Pure function, no ORM/broker
imports — same philosophy as indicators.py — because no broker adapter
provides weekly/monthly history directly; every "1w"/"1mo" chart is derived
from already-ingested "1d" candles, for any broker.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timezone as dt_timezone
from typing import Literal

# Timeframes handled by resampling daily candles rather than fetching from a
# broker. Referenced by fyers_adapter.py (to reject them at the API-call
# boundary) and by analysis.py (to route bar-fetching here instead of the DB).
DERIVED_TIMEFRAMES = {"1w", "1mo"}


@dataclass(frozen=True)
class PlainBar:
    """Broker-agnostic, ORM-agnostic OHLCV bar — the common shape real
    Candle rows and resampled synthetic bars both get adapted into."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


def _period_key(d: date, period: Literal["1w", "1mo"]) -> tuple:
    if period == "1w":
        iso = d.isocalendar()
        return (iso[0], iso[1])  # (ISO year, ISO week)
    return (d.year, d.month)


def _period_start(d: date, period: Literal["1w", "1mo"]) -> date:
    if period == "1w":
        return date.fromisocalendar(*d.isocalendar()[:2], 1)  # that ISO week's Monday
    return d.replace(day=1)


def resample(bars: list[PlainBar], period: Literal["1w", "1mo"]) -> list[PlainBar]:
    """
    Group daily bars (must already be sorted ascending by timestamp) into
    weekly/monthly bars: open=first bar's open, high=max high, low=min low,
    close=last bar's close, volume=sum volume. Each output bar's timestamp
    is the period's start date (the ISO week's Monday, or the 1st of the
    month) — a deterministic, documented convention rather than an
    unlabelled choice.
    """
    if period not in DERIVED_TIMEFRAMES:
        raise ValueError(f"Unsupported resample period {period!r}; supported: {sorted(DERIVED_TIMEFRAMES)}")

    out: list[PlainBar] = []
    current_key = None
    group: list[PlainBar] = []

    def flush():
        if not group:
            return
        out.append(
            PlainBar(
                timestamp=datetime.combine(_period_start(group[0].timestamp.date(), period), time.min, tzinfo=dt_timezone.utc),
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
            )
        )

    for bar in bars:
        key = _period_key(bar.timestamp.date(), period)
        if key != current_key:
            flush()
            group = []
            current_key = key
        group.append(bar)
    flush()

    return out
