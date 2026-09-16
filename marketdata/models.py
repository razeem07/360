from django.db import models


class Instrument(models.Model):
    """
    One tradable instrument, identified by an internal ID stable across
    brokers (CLAUDE.md rule 2 / PRD §7). Strategies, backtests, and
    paper-trading records must reference this, never a broker symbol.
    """

    internal_id = models.CharField(max_length=64, unique=True)
    symbol = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    exchange = models.CharField(max_length=16)
    segment = models.CharField(max_length=16, default="EQ")
    instrument_type = models.CharField(max_length=16, default="EQUITY")
    sector = models.CharField(max_length=64, blank=True)
    lot_size = models.PositiveIntegerField(default=1)
    tick_size = models.DecimalField(max_digits=10, decimal_places=4, default="0.05")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["symbol"]

    def __str__(self):
        return self.internal_id


class InstrumentBrokerMapping(models.Model):
    """
    Maps one Instrument to its symbol at a specific broker. Only adapters in
    marketdata/broker/ and execution/ should ever read broker_symbol.
    """

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="broker_mappings")
    broker = models.CharField(max_length=32)
    broker_symbol = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["broker", "broker_symbol"], name="uniq_broker_symbol"),
            models.UniqueConstraint(fields=["instrument", "broker"], name="uniq_instrument_per_broker"),
        ]

    def __str__(self):
        return f"{self.instrument.internal_id} -> {self.broker}:{self.broker_symbol}"


class Candle(models.Model):
    """
    One OHLCV bar. `source` and `timestamp` are always recorded together
    (PRD §19) so every bar's provenance is traceable.
    """

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="candles")
    timeframe = models.CharField(max_length=8)  # e.g. "1m", "5m", "15m", "1d"
    timestamp = models.DateTimeField()  # bar open time, timezone-aware
    open = models.DecimalField(max_digits=14, decimal_places=4)
    high = models.DecimalField(max_digits=14, decimal_places=4)
    low = models.DecimalField(max_digits=14, decimal_places=4)
    close = models.DecimalField(max_digits=14, decimal_places=4)
    volume = models.BigIntegerField(default=0)
    source = models.CharField(max_length=32)  # e.g. "fyers"
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "timeframe", "timestamp", "source"],
                name="uniq_candle_bar",
            ),
        ]
        indexes = [
            models.Index(fields=["instrument", "timeframe", "timestamp"]),
        ]
        ordering = ["timestamp"]

    def __str__(self):
        return f"{self.instrument.internal_id} {self.timeframe} {self.timestamp.isoformat()}"


class WatchlistItem(models.Model):
    """
    One instrument on the (single-user — this is a personal-use app per PRD
    §1/§3, not multi-tenant) watchlist shown on the Stock Analysis page.
    """

    instrument = models.OneToOneField(Instrument, on_delete=models.CASCADE, related_name="watchlist_entry")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["instrument__symbol"]

    def __str__(self):
        return self.instrument.internal_id
