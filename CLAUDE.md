# Project Instructions — AI Trading Automation Platform

Full spec: see `docs/PRD.md`. This file holds only the rules that must never be violated while coding — read it every session; read the PRD when you need scope/detail on a specific feature.

## Stack (locked — do not switch without being told)
- Backend: Python + Django, Django REST Framework where an API is needed
- Frontend: Django templates + HTML/CSS + vanilla JS. Optional: htmx / Alpine.js for interactivity. **No React** — the developer has no React experience and this is a single-user dashboard, not a component-heavy SPA.
- Charting: TradingView `lightweight-charts` (plain JS), embedded directly in templates
- DB: PostgreSQL (SQLite OK for early local dev)
- Background jobs: Celery + Redis
- Live data push (server → browser): Django Channels (ASGI), Redis as channel layer — reuses the Celery Redis instance
- Broker/data API: **Fyers** for development. Zerodha Kite Connect is a possible future production target — see the broker-abstraction rule below, which exists specifically to make that switch cheap.

## Hard rules

1. **Broker abstraction is mandatory.** All broker/data calls go through one internal interface (`get_historical_candles`, `get_live_quote`/`subscribe_ticks`, `place_order`/`modify_order`/`cancel_order`, `get_positions`/`get_holdings`/`get_order_status`, `get_instrument_master`). Only `marketdata/` and `execution/` may import a broker SDK. Never let a broker's symbol format, response schema, or order-type codes leak into `strategies/`, `backtesting/`, `papertrading/`, or `risk/`.
2. **One internal instrument ID.** Strategies/backtests/paper-trading reference instruments by an internal ID, never a broker's raw symbol. Adapters translate at the boundary only.
3. **No strategy logic in views or templates.** `strategies/`, `risk/`, `ai/` are plain, independently unit-testable Python.
4. **Fee model is mandatory in every backtest that's used for a decision.** Fees/STT/GST/stamp-duty/slippage live in a dated, versioned config (not a single constant) — a backtest spanning years must apply the rate in force on each trade's date. A zero-fee backtest is only ever a labeled "gross, pre-cost" diagnostic, never the number used to judge a strategy.
5. **No real-money capability anywhere before Phase 3.** Phase 1–2 must have zero code path that can place a live order, even for testing. Explicit mode flag: `BACKTEST` / `PAPER` / `LIVE`, defaulting to non-live.
6. **Kill switch and audit log exist before the first live order** — not added afterward. Required both by internal risk rules and (from April 2026) by SEBI's algo-trading framework.
7. **Build phases in order.** Don't start Phase 2 (alerts) until Phase 1 is complete per the PRD's acceptance criteria; don't start Phase 3 (broker execution) until alerts have run reliably; don't start Phase 4 (full automation) until Phase 3 has run with manual approval for a meaningful stretch.
8. **Secrets never in source.** Env vars / secret storage only. No broker credentials hardcoded, ever.
9. **Candle aggregation (ticks → OHLC bars) lives in `marketdata/`, not in a view or consumer.** It's a pure function of a tick stream, independently unit-testable, broker-agnostic — the Fyers-specific tick parsing stays in the adapter; only the aggregator's *output* reaches Django Channels.
10. **Live chart/live analysis is not live execution.** A live-updating candlestick chart, live indicators, live strategy signals, and live paper P&L are all Phase 1 — none of them may place a real order. Don't let "it updates in real time" become a reason to wire a live feed to `execution/` early.
11. **`lightweight-charts` attribution**: keep the default TradingView branding on the chart, or if removed, add the attribution notice + link to tradingview.com per its NOTICE file (Apache 2.0 condition).

## Acceptance check for the abstraction (rule 1)
Swapping the Fyers adapter for a stub adapter that returns fixed sample data must not require touching any file outside `marketdata/` and `execution/`. If it does, the abstraction has leaked — fix it before moving on.

## When in doubt
Prefer the simpler, standard-library-first option consistent with the stack above. Flag scope questions rather than silently expanding a phase (e.g. don't add AI-layer features to Phase 1 — see PRD §15).
