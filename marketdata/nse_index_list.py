"""
Fetch NSE's own published index-constituent CSVs. This is NOT broker data —
it's index membership metadata used only by seed_instruments, so it doesn't
go through the BrokerAdapter interface (CLAUDE.md rule 1 is about price/
order flow; this is reference data for our own seeding tool, from a
different source than Fyers entirely).

Replaces the earlier hand-typed "best-known" constituent list, which went
stale in practice (missed the Tata Motors demerger and the Zomato->Eternal
rename) — NSE's own CSV is authoritative and self-updating on every re-seed.
"""

import csv
import logging

import requests

logger = logging.getLogger(__name__)

# NSE blocks requests with no browser-like User-Agent.
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_URL_TEMPLATE = "https://archives.nseindia.com/content/indices/ind_{slug}list.csv"


def fetch_index_constituents(index_slug: str) -> list[dict]:
    """
    index_slug: NSE's own slug, e.g. "nifty50", "nifty100", "nifty200",
    "nifty500" — matches the archives.nseindia.com CSV filename exactly.
    Returns [{"symbol", "name", "sector"}], one per constituent.
    """
    url = _URL_TEMPLATE.format(slug=index_slug)
    response = requests.get(url, headers=_HEADERS, timeout=30)
    response.raise_for_status()

    reader = csv.DictReader(response.text.splitlines())
    constituents = []
    for row in reader:
        try:
            constituents.append({
                "symbol": row["Symbol"].strip(),
                "name": row["Company Name"].strip(),
                "sector": row["Industry"].strip(),
            })
        except KeyError as exc:
            raise ValueError(f"Unexpected NSE CSV columns for {index_slug!r}: {reader.fieldnames}") from exc

    if not constituents:
        raise ValueError(f"NSE returned an empty constituent list for {index_slug!r} — check the slug is correct.")

    return constituents
