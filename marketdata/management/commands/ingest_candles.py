"""
Ingest historical OHLCV candles for seeded instruments via the configured
broker adapter (settings.BROKER_ADAPTER), storing them with source +
timestamp per PRD S19.

Examples:
    python manage.py ingest_candles
    python manage.py ingest_candles --timeframe 1d --days 60
    python manage.py ingest_candles --symbols NSE_EQ_RELIANCE,NSE_EQ_TCS
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from marketdata.models import Instrument
from marketdata.resampling import DERIVED_TIMEFRAMES
from marketdata.services import InstrumentNotMapped, get_adapter, ingest_historical_candles

# Sensible default lookback per timeframe — deep intraday history is a lot of
# rows and a lot of chunked API requests, so shorter timeframes default to a
# shorter window. Always overridable with --days.
DEFAULT_DAYS_BY_TIMEFRAME = {
    "1m": 7,
    "5m": 30,
    "15m": 60,
    "30m": 90,
    "1h": 180,
    "4h": 365,
    "1d": 400,
}


class Command(BaseCommand):
    help = "Ingest historical OHLCV candles for instruments via the active broker adapter."

    def add_arguments(self, parser):
        parser.add_argument(
            "--symbols",
            help="Comma-separated internal_id list (default: all active instruments).",
        )
        parser.add_argument("--timeframe", default="1d", help="1m, 5m, 15m, 30m, 1h, 4h, or 1d (default: 1d)")
        parser.add_argument(
            "--days", type=int, default=None,
            help="How many days of history to fetch (default: sized per timeframe, see DEFAULT_DAYS_BY_TIMEFRAME)",
        )

    def handle(self, *args, **options):
        timeframe = options["timeframe"]
        if timeframe in DERIVED_TIMEFRAMES:
            raise CommandError(
                f"{timeframe!r} is derived from '1d' candles at query time (marketdata/resampling.py) "
                "— it's never ingested directly. Run `ingest_candles --timeframe 1d` instead."
            )

        if options["symbols"]:
            internal_ids = [s.strip() for s in options["symbols"].split(",") if s.strip()]
            instruments = Instrument.objects.filter(internal_id__in=internal_ids)
            missing = set(internal_ids) - set(instruments.values_list("internal_id", flat=True))
            if missing:
                raise CommandError(f"Unknown instrument(s): {', '.join(sorted(missing))}")
        else:
            instruments = Instrument.objects.filter(is_active=True)

        if not instruments:
            raise CommandError("No instruments to ingest. Run `python manage.py seed_instruments` first.")

        days = options["days"] if options["days"] is not None else DEFAULT_DAYS_BY_TIMEFRAME.get(timeframe, 30)
        to_dt = timezone.now()
        from_dt = to_dt - timedelta(days=days)

        adapter = get_adapter()
        self.stdout.write(f"Using adapter: {adapter.__class__.__name__} (source={adapter.broker_name})")
        self.stdout.write(f"Timeframe: {timeframe}, lookback: {days} days")

        total_bars = 0
        for instrument in instruments:
            try:
                count = ingest_historical_candles(instrument, timeframe, from_dt, to_dt, adapter=adapter)
            except InstrumentNotMapped as exc:
                self.stderr.write(self.style.WARNING(f"Skipping {instrument.internal_id}: {exc}"))
                continue
            self.stdout.write(f"  {instrument.internal_id}: {count} bars")
            total_bars += count

        self.stdout.write(self.style.SUCCESS(f"Done. {total_bars} bars ingested across {instruments.count()} instruments."))
