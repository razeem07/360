"""
Market-data service layer: resolves internal Instruments to broker symbols
and orchestrates ingestion through whichever BrokerAdapter is configured.

This is the only place that bridges Django models (Instrument, Candle) with
the broker abstraction — it never imports a broker SDK itself (only the
adapter classes in marketdata/broker/ do that), and it's the reason
strategies/backtesting/etc. never need to know a broker symbol exists.
"""

import logging
from datetime import datetime
from importlib import import_module

from django.conf import settings
from django.db import transaction

from .broker.base import BrokerAdapter
from .models import Candle, Instrument, InstrumentBrokerMapping

logger = logging.getLogger(__name__)


def get_adapter() -> BrokerAdapter:
    """
    Instantiate the broker adapter named by settings.BROKER_ADAPTER.

    This indirection is what makes the acceptance check in CLAUDE.md rule 1
    possible: pointing BROKER_ADAPTER at a different adapter class is the
    only change needed to swap brokers.
    """
    dotted_path = settings.BROKER_ADAPTER
    module_path, class_name = dotted_path.rsplit(".", 1)
    adapter_cls = getattr(import_module(module_path), class_name)
    return adapter_cls()


class InstrumentNotMapped(Exception):
    """Raised when an Instrument has no broker_symbol mapping for the active broker."""


def resolve_broker_symbol(instrument: Instrument, broker_name: str) -> str:
    try:
        mapping = instrument.broker_mappings.get(broker=broker_name)
    except InstrumentBrokerMapping.DoesNotExist as exc:
        raise InstrumentNotMapped(
            f"{instrument.internal_id} has no {broker_name} symbol mapping."
        ) from exc
    return mapping.broker_symbol


def ingest_historical_candles(
    instrument: Instrument,
    timeframe: str,
    from_dt: datetime,
    to_dt: datetime,
    adapter: BrokerAdapter | None = None,
) -> int:
    """
    Fetch historical OHLCV bars for one instrument and upsert them as Candle
    rows tagged with the adapter's broker_name as `source` (PRD S19).
    Returns the number of bars written or updated.
    """
    adapter = adapter or get_adapter()
    broker_symbol = resolve_broker_symbol(instrument, adapter.broker_name)

    bars = adapter.get_historical_candles(broker_symbol, timeframe, from_dt, to_dt)

    written = 0
    with transaction.atomic():
        for bar in bars:
            _, created = Candle.objects.update_or_create(
                instrument=instrument,
                timeframe=timeframe,
                timestamp=bar.timestamp,
                source=adapter.broker_name,
                defaults={
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                },
            )
            written += 1

    logger.info(
        "Ingested %d bars for %s [%s] %s..%s from %s",
        written, instrument.internal_id, timeframe, from_dt.date(), to_dt.date(), adapter.broker_name,
    )
    return written
