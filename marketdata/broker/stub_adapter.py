"""
Stub adapter returning fixed sample data — no network calls, no SDK.

Exists to exercise the broker-abstraction acceptance check (CLAUDE.md rule 1
/ PRD §7): pointing BROKER_ADAPTER at this class instead of FyersAdapter must
not require touching anything outside marketdata/ and execution/.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from .base import BrokerAdapter, CandleBar, InstrumentInfo, Tick


class StubAdapter(BrokerAdapter):
    broker_name = "stub"

    def get_historical_candles(
        self, broker_symbol: str, interval: str, from_dt: datetime, to_dt: datetime
    ) -> list[CandleBar]:
        bars = []
        ts = from_dt
        price = Decimal("100.00")
        while ts < to_dt:
            bars.append(
                CandleBar(
                    timestamp=timezone.make_aware(ts, timezone.utc) if timezone.is_naive(ts) else ts,
                    open=price,
                    high=price + Decimal("1.0"),
                    low=price - Decimal("1.0"),
                    close=price + Decimal("0.5"),
                    volume=1000,
                )
            )
            ts += timedelta(days=1)
            price += Decimal("0.5")
        return bars

    def get_live_quote(self, broker_symbol: str) -> Tick:
        return Tick(timestamp=timezone.now(), last_price=Decimal("100.00"), volume=0)

    def subscribe_ticks(self, broker_symbols: list[str], on_tick):
        raise NotImplementedError("StubAdapter does not simulate live ticks.")

    def get_instrument_master(self) -> list[InstrumentInfo]:
        return [
            InstrumentInfo(
                broker_symbol="NSE:SAMPLE-EQ",
                name="Sample Instrument",
                exchange="NSE",
                segment="CM",
                instrument_type="EQ",
                lot_size=1,
                tick_size=Decimal("0.05"),
            )
        ]

    def place_order(self, order):
        raise NotImplementedError

    def modify_order(self, order_id: str, **changes):
        raise NotImplementedError

    def cancel_order(self, order_id: str):
        raise NotImplementedError

    def get_positions(self):
        return []

    def get_holdings(self):
        return []

    def get_order_status(self, order_id: str):
        raise NotImplementedError
