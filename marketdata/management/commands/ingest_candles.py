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
from marketdata.services import InstrumentNotMapped, get_adapter, ingest_historical_candles


class Command(BaseCommand):
    help = "Ingest historical OHLCV candles for instruments via the active broker adapter."

    def add_arguments(self, parser):
        parser.add_argument(
            "--symbols",
            help="Comma-separated internal_id list (default: all active instruments).",
        )
        parser.add_argument("--timeframe", default="1d", help="e.g. 1m, 5m, 15m, 1d (default: 1d)")
        parser.add_argument("--days", type=int, default=30, help="How many days of history to fetch (default: 30)")

    def handle(self, *args, **options):
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

        to_dt = timezone.now()
        from_dt = to_dt - timedelta(days=options["days"])
        timeframe = options["timeframe"]

        adapter = get_adapter()
        self.stdout.write(f"Using adapter: {adapter.__class__.__name__} (source={adapter.broker_name})")

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
