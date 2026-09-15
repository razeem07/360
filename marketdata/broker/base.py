"""
Broker abstraction — the internal interface every broker adapter implements.

CLAUDE.md rule 1 / PRD §7: all broker/data calls go through this interface.
No broker SDK, symbol format, response schema, or order-type code may leak
outside `marketdata/` and `execution/`. Callers outside this package work
only with the internal types defined here (CandleBar, Tick, InstrumentInfo,
...), never with a broker's raw payloads.

Acceptance check: swapping FyersAdapter for StubAdapter must not require
touching any file outside marketdata/ and execution/.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class CandleBar:
    """One OHLCV bar in the internal format, timezone-aware."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class Tick:
    """One live tick in the internal format."""

    timestamp: datetime
    last_price: Decimal
    volume: int | None = None


@dataclass(frozen=True)
class InstrumentInfo:
    """One row of a broker's instrument master, in the internal format."""

    broker_symbol: str
    name: str
    exchange: str
    segment: str
    instrument_type: str
    lot_size: int = 1
    tick_size: Decimal = Decimal("0.05")


class BrokerAdapter(ABC):
    """
    Internal broker interface (PRD §7). Every method takes/returns internal
    types only — a concrete adapter is responsible for translating to and
    from its broker's own symbol format, response schema, and order-type
    codes entirely within its own module.
    """

    #: Short identifier for this broker, used as InstrumentBrokerMapping.broker
    #: and Candle.source so ingested data is traceable to where it came from
    #: (see PRD "Data & Reliability Requirements"). Every adapter must set this.
    broker_name: str

    # -- Market data -------------------------------------------------------

    @abstractmethod
    def get_historical_candles(
        self, broker_symbol: str, interval: str, from_dt: datetime, to_dt: datetime
    ) -> list[CandleBar]:
        """Return historical OHLCV bars for one broker symbol and interval."""
        raise NotImplementedError

    @abstractmethod
    def get_live_quote(self, broker_symbol: str) -> Tick:
        """Return the latest tick for one broker symbol."""
        raise NotImplementedError

    @abstractmethod
    def subscribe_ticks(self, broker_symbols: list[str], on_tick):
        """Subscribe to live ticks; `on_tick(broker_symbol, Tick)` is called per tick."""
        raise NotImplementedError

    @abstractmethod
    def get_instrument_master(self) -> list[InstrumentInfo]:
        """Return the broker's full instrument list in the internal format."""
        raise NotImplementedError

    # -- Execution (Phase 3+) -----------------------------------------------
    # Present in the interface now per PRD §7 so every adapter implements the
    # same shape, but must not be called from anywhere before Phase 3
    # (CLAUDE.md rule 5).

    @abstractmethod
    def place_order(self, order):
        raise NotImplementedError

    @abstractmethod
    def modify_order(self, order_id: str, **changes):
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str):
        raise NotImplementedError

    @abstractmethod
    def get_positions(self):
        raise NotImplementedError

    @abstractmethod
    def get_holdings(self):
        raise NotImplementedError

    @abstractmethod
    def get_order_status(self, order_id: str):
        raise NotImplementedError
