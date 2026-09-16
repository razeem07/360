"""Shared identifiers used across marketdata/ (seeding, analysis, ingestion)."""

# The NIFTY 50 index — used as the relative-strength benchmark in analysis.py.
NIFTY50_INDEX_INTERNAL_ID = "NSE_INDEX_NIFTY50"
NIFTY50_INDEX_FYERS_SYMBOL = "NSE:NIFTY50-INDEX"

# BANK NIFTY — in PRD S4's market scope alongside NIFTY 50, watchable/
# chartable like any other instrument (not used as a benchmark anywhere).
BANKNIFTY_INDEX_INTERNAL_ID = "NSE_INDEX_BANKNIFTY"
BANKNIFTY_INDEX_FYERS_SYMBOL = "NSE:NIFTYBANK-INDEX"
