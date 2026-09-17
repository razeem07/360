"""
ORM glue between StrategyVersion and the pure rule engine (rules.py) — the
only place in strategies/ that touches the database, mirroring how
marketdata/analysis.py is the only place indicators.py touches Candle rows.
"""

from dataclasses import dataclass

from marketdata.analysis import chart_time, get_bars
from marketdata.models import Instrument

from . import rules
from .models import StrategyVersion


@dataclass
class SignalPreview:
    bar_count: int
    entry_times: list
    exit_times: list


def build_signal_preview(version: StrategyVersion, instrument: Instrument, timeframe: str) -> SignalPreview:
    bars = get_bars(instrument, timeframe)  # same real-vs-resampled routing Stock Analysis uses

    if not bars:
        return SignalPreview(bar_count=0, entry_times=[], exit_times=[])

    entry_hits = rules.evaluate_ruleset(version.entry_rules, bars)
    exit_hits = rules.evaluate_ruleset(version.exit_rules, bars)

    # chart_time() matches how marketdata's candle API keys its "time"
    # field for the same timeframe, so these markers land on the exact bar
    # they fired on instead of drifting on intraday charts.
    entry_times = [chart_time(b.timestamp, timeframe) for b, hit in zip(bars, entry_hits) if hit]
    exit_times = [chart_time(b.timestamp, timeframe) for b, hit in zip(bars, exit_hits) if hit]

    return SignalPreview(bar_count=len(bars), entry_times=entry_times, exit_times=exit_times)
