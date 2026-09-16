"""
Seed equity instruments (plus reference indices) with their Fyers symbol
mapping. Idempotent — safe to re-run.

Constituents come from NSE's own published index CSV (marketdata/
nse_index_list.py), not a hand-typed list — that list went stale in
practice (missed the Tata Motors demerger and the Zomato->Eternal rename).
Fetching it live means every re-seed reflects NSE's current index
membership automatically.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from marketdata.constants import (
    BANKNIFTY_INDEX_FYERS_SYMBOL,
    BANKNIFTY_INDEX_INTERNAL_ID,
    NIFTY50_INDEX_FYERS_SYMBOL,
    NIFTY50_INDEX_INTERNAL_ID,
)
from marketdata.models import Instrument, InstrumentBrokerMapping
from marketdata.nse_index_list import fetch_index_constituents

# (internal_id, symbol, name, fyers_symbol) — indices, not equities, so they
# aren't in the NSE_CM instrument master and can't be cross-checked the same
# way; verified empirically instead (successfully ingesting candles for it).
INDICES = [
    (NIFTY50_INDEX_INTERNAL_ID, "NIFTY50", "NIFTY 50 Index", NIFTY50_INDEX_FYERS_SYMBOL),
    (BANKNIFTY_INDEX_INTERNAL_ID, "BANKNIFTY", "NIFTY Bank Index", BANKNIFTY_INDEX_FYERS_SYMBOL),
]


class Command(BaseCommand):
    help = "Seed Instrument + Fyers InstrumentBrokerMapping rows from NSE's official index constituent list."

    def add_arguments(self, parser):
        parser.add_argument(
            "--index-slug", default="nifty200",
            help="NSE index slug to seed constituents from, e.g. nifty50, nifty100, nifty200, nifty500 (default: nifty200)",
        )
        parser.add_argument(
            "--skip-verify",
            action="store_true",
            help="Skip cross-checking symbols against Fyers' instrument master (faster, no network call).",
        )

    def handle(self, *args, **options):
        try:
            constituents = fetch_index_constituents(options["index_slug"])
        except Exception as exc:
            raise CommandError(
                f"Could not fetch NSE's {options['index_slug']!r} constituent list: {exc}"
            ) from exc
        self.stdout.write(f"Fetched {len(constituents)} constituents for {options['index_slug']} from NSE.")

        known_fyers_symbols = None
        if not options["skip_verify"]:
            known_fyers_symbols = self._fetch_known_fyers_symbols()

        created_count = 0
        unverified = []
        with transaction.atomic():
            for row in constituents:
                symbol, name, sector = row["symbol"], row["name"], row["sector"]
                internal_id = f"NSE_EQ_{symbol}"
                broker_symbol = f"NSE:{symbol}-EQ"

                if known_fyers_symbols is not None and broker_symbol not in known_fyers_symbols:
                    unverified.append(broker_symbol)

                instrument, _ = Instrument.objects.update_or_create(
                    internal_id=internal_id,
                    defaults={
                        "symbol": symbol,
                        "name": name,
                        "exchange": "NSE",
                        "segment": "EQ",
                        "instrument_type": "EQUITY",
                        "sector": sector,
                    },
                )
                InstrumentBrokerMapping.objects.update_or_create(
                    instrument=instrument,
                    broker="fyers",
                    defaults={"broker_symbol": broker_symbol},
                )
                created_count += 1
                self.stdout.write(f"  {internal_id} -> fyers:{broker_symbol}")

            for internal_id, symbol, name, fyers_symbol in INDICES:
                index_instrument, _ = Instrument.objects.update_or_create(
                    internal_id=internal_id,
                    defaults={
                        "symbol": symbol,
                        "name": name,
                        "exchange": "NSE",
                        "segment": "INDEX",
                        "instrument_type": "INDEX",
                        "sector": "",
                    },
                )
                InstrumentBrokerMapping.objects.update_or_create(
                    instrument=index_instrument,
                    broker="fyers",
                    defaults={"broker_symbol": fyers_symbol},
                )
                created_count += 1
                self.stdout.write(f"  {internal_id} -> fyers:{fyers_symbol}")

        if unverified:
            self.stderr.write(self.style.WARNING(
                f"\n{len(unverified)} symbol(s) not found in Fyers' current instrument master "
                f"(possibly delisted, renamed, or a Fyers-side naming difference — verify manually): "
                f"{', '.join(unverified)}"
            ))

        self.stdout.write(self.style.SUCCESS(f"Seeded {created_count} instruments."))

    def _fetch_known_fyers_symbols(self) -> set[str] | None:
        from marketdata.services import get_adapter

        try:
            master = get_adapter().get_instrument_master()
        except Exception as exc:  # not configured, network hiccup, etc. — don't block seeding on it
            self.stderr.write(self.style.WARNING(
                f"Could not verify against the broker instrument master ({exc}); "
                "seeding without verification. Re-run without --skip-verify once the adapter is configured."
            ))
            return None
        return {info.broker_symbol for info in master}
