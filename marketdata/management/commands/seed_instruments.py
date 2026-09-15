"""
Seed a handful of NIFTY 50 instruments (plus the NIFTY 50 index itself, used
as the relative-strength benchmark) with their Fyers symbol mapping.
Idempotent — safe to re-run.

Fyers equity symbols follow the documented "EXCHANGE:SYMBOL-SEGMENT" format
(e.g. "NSE:RELIANCE-EQ"), so we construct them directly rather than relying
on the full instrument-master CSV for this small, stable subset.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from marketdata.constants import NIFTY50_INDEX_FYERS_SYMBOL, NIFTY50_INDEX_INTERNAL_ID
from marketdata.models import Instrument, InstrumentBrokerMapping

# A handful of large, liquid NIFTY 50 constituents (PRD S4 market scope).
# (symbol, name, sector)
NIFTY50_SUBSET = [
    ("RELIANCE", "Reliance Industries", "Energy"),
    ("TCS", "Tata Consultancy Services", "IT"),
    ("HDFCBANK", "HDFC Bank", "Financials"),
    ("INFY", "Infosys", "IT"),
    ("ICICIBANK", "ICICI Bank", "Financials"),
    ("HINDUNILVR", "Hindustan Unilever", "FMCG"),
    ("ITC", "ITC", "FMCG"),
    ("SBIN", "State Bank of India", "Financials"),
    ("BHARTIARTL", "Bharti Airtel", "Telecom"),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Financials"),
]

class Command(BaseCommand):
    help = "Seed Instrument + Fyers InstrumentBrokerMapping rows for a handful of NIFTY 50 stocks and the index."

    def handle(self, *args, **options):
        created_count = 0
        with transaction.atomic():
            for symbol, name, sector in NIFTY50_SUBSET:
                internal_id = f"NSE_EQ_{symbol}"
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
                    defaults={"broker_symbol": f"NSE:{symbol}-EQ"},
                )
                created_count += 1
                self.stdout.write(f"  {internal_id} -> fyers:NSE:{symbol}-EQ")

            index_instrument, _ = Instrument.objects.update_or_create(
                internal_id=NIFTY50_INDEX_INTERNAL_ID,
                defaults={
                    "symbol": "NIFTY50",
                    "name": "NIFTY 50 Index",
                    "exchange": "NSE",
                    "segment": "INDEX",
                    "instrument_type": "INDEX",
                    "sector": "",
                },
            )
            InstrumentBrokerMapping.objects.update_or_create(
                instrument=index_instrument,
                broker="fyers",
                defaults={"broker_symbol": NIFTY50_INDEX_FYERS_SYMBOL},
            )
            created_count += 1
            self.stdout.write(f"  {NIFTY50_INDEX_INTERNAL_ID} -> fyers:{NIFTY50_INDEX_FYERS_SYMBOL}")

        self.stdout.write(self.style.SUCCESS(f"Seeded {created_count} instruments."))
