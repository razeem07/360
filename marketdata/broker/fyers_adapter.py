"""
Fyers API v3 adapter — the ONLY place in this codebase allowed to import the
Fyers SDK, know Fyers symbol formats, or parse Fyers response payloads
(CLAUDE.md rule 1).

Auth: Fyers access tokens are short-lived (roughly one trading day). Generate
one with `python manage.py fyers_login` and put it in FYERS_ACCESS_TOKEN in
.env; this adapter never performs the interactive login flow itself.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from fyers_apiv3 import fyersModel

from .base import BrokerAdapter, CandleBar, InstrumentInfo, Tick

logger = logging.getLogger(__name__)

# Internal interval -> Fyers "resolution" code, and the max days per request
# Fyers accepts for that resolution (intraday history is capped; daily is not
# capped the same way, but we still chunk generously to be safe).
_RESOLUTION_MAP = {
    "1m": ("1", 100),
    "5m": ("5", 100),
    "15m": ("15", 100),
    "30m": ("30", 100),
    "60m": ("60", 100),
    "1d": ("D", 366),
}

# Fyers publishes a per-exchange symbol master CSV. We only need NSE Capital
# Market (equities) for Phase 1's NIFTY 50 scope (PRD §4).
_SYMBOL_MASTER_URL = "https://public.fyers.in/sym_details/NSE_CM.csv"


class FyersAdapter(BrokerAdapter):
    """BrokerAdapter implementation backed by Fyers API v3."""

    broker_name = "fyers"

    def __init__(self):
        if not settings.FYERS_CLIENT_ID or not settings.FYERS_ACCESS_TOKEN:
            raise RuntimeError(
                "FYERS_CLIENT_ID / FYERS_ACCESS_TOKEN are not configured. "
                "Set them in .env (see .env.example); run `python manage.py "
                "fyers_login` to obtain a token."
            )
        self._client = fyersModel.FyersModel(
            client_id=settings.FYERS_CLIENT_ID,
            token=settings.FYERS_ACCESS_TOKEN,
            is_async=False,
            log_path="",
        )

    # -- Market data ---------------------------------------------------

    def get_historical_candles(
        self, broker_symbol: str, interval: str, from_dt: datetime, to_dt: datetime
    ) -> list[CandleBar]:
        if interval not in _RESOLUTION_MAP:
            raise ValueError(f"Unsupported interval {interval!r}; supported: {sorted(_RESOLUTION_MAP)}")
        resolution, chunk_days = _RESOLUTION_MAP[interval]

        bars: list[CandleBar] = []
        chunk_start = from_dt
        while chunk_start < to_dt:
            chunk_end = min(chunk_start + timedelta(days=chunk_days), to_dt)
            payload = {
                "symbol": broker_symbol,
                "resolution": resolution,
                "date_format": "1",
                "range_from": chunk_start.strftime("%Y-%m-%d"),
                "range_to": chunk_end.strftime("%Y-%m-%d"),
                "cont_flag": "1",
            }
            response = self._client.history(data=payload)
            if response.get("s") != "ok":
                logger.warning(
                    "Fyers history request failed for %s [%s..%s]: %s",
                    broker_symbol, payload["range_from"], payload["range_to"], response,
                )
                chunk_start = chunk_end
                continue

            for row in response.get("candles", []):
                bar = self._parse_candle_row(row)
                if bar is not None:
                    bars.append(bar)
            chunk_start = chunk_end

        return bars

    @staticmethod
    def _parse_candle_row(row) -> CandleBar | None:
        # Fyers candle row: [epoch_seconds, open, high, low, close, volume]
        try:
            ts_epoch, o, h, l, c, v = row
            return CandleBar(
                timestamp=_from_epoch(ts_epoch),
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(l)),
                close=Decimal(str(c)),
                volume=int(v),
            )
        except (ValueError, TypeError, InvalidOperation, IndexError) as exc:
            logger.warning("Skipping malformed Fyers candle row %r: %s", row, exc)
            return None

    def get_live_quote(self, broker_symbol: str) -> Tick:
        raise NotImplementedError("Live quotes land with the Phase 1 live-chart milestone (PRD §8).")

    def subscribe_ticks(self, broker_symbols: list[str], on_tick):
        raise NotImplementedError("Tick subscription lands with the Phase 1 live-chart milestone (PRD §8).")

    def get_instrument_master(self) -> list[InstrumentInfo]:
        response = requests.get(_SYMBOL_MASTER_URL, timeout=30)
        response.raise_for_status()

        instruments: list[InstrumentInfo] = []
        skipped = 0
        for line in response.text.splitlines():
            if not line.strip():
                continue
            fields = line.split(",")
            info = self._parse_master_row(fields)
            if info is None:
                skipped += 1
                continue
            instruments.append(info)

        if skipped:
            logger.warning("Skipped %d malformed rows in Fyers instrument master.", skipped)
        return instruments

    @staticmethod
    def _parse_master_row(fields: list[str]) -> InstrumentInfo | None:
        # Column layout per Fyers symbol-master docs. We only trust the
        # fields we're confident about (symbol ticker, description, lot
        # size, tick size); exchange/segment/type are derived from the
        # symbol ticker itself rather than the less-documented numeric
        # exchange/segment codes, to stay robust to schema drift.
        try:
            description = fields[1].strip()
            lot_size = int(fields[3])
            tick_size = Decimal(fields[4])
            broker_symbol = fields[9].strip()
        except (IndexError, ValueError, InvalidOperation):
            return None

        if ":" not in broker_symbol or "-" not in broker_symbol:
            return None
        exchange, rest = broker_symbol.split(":", 1)
        instrument_type = rest.rsplit("-", 1)[-1] if "-" in rest else "EQ"

        return InstrumentInfo(
            broker_symbol=broker_symbol,
            name=description,
            exchange=exchange,
            segment="CM",
            instrument_type=instrument_type,
            lot_size=lot_size,
            tick_size=tick_size,
        )

    # -- Execution (Phase 3+, not implemented before then — CLAUDE.md rule 5) --

    def place_order(self, order):
        raise NotImplementedError("Order placement is out of scope before Phase 3 (CLAUDE.md rule 5).")

    def modify_order(self, order_id: str, **changes):
        raise NotImplementedError("Order placement is out of scope before Phase 3 (CLAUDE.md rule 5).")

    def cancel_order(self, order_id: str):
        raise NotImplementedError("Order placement is out of scope before Phase 3 (CLAUDE.md rule 5).")

    def get_positions(self):
        raise NotImplementedError("Broker position sync is out of scope before Phase 3 (CLAUDE.md rule 5).")

    def get_holdings(self):
        raise NotImplementedError("Broker holdings sync is out of scope before Phase 3 (CLAUDE.md rule 5).")

    def get_order_status(self, order_id: str):
        raise NotImplementedError("Order tracking is out of scope before Phase 3 (CLAUDE.md rule 5).")


def _from_epoch(epoch_seconds: int) -> datetime:
    from django.utils import timezone

    return timezone.make_aware(datetime.utcfromtimestamp(epoch_seconds), timezone.utc)
