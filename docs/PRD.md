# AI Trading Automation Platform — PRD
*Version 1.3 (consolidated) | Personal use | Indian markets | Phase 1–4 roadmap*

> This file is the full specification. `CLAUDE.md` at the repo root points here and carries only the hard rules an agent must never violate while coding.

---

## 1. Product Overview

A personal-use, Django-based AI-assisted trading platform to reduce continuous market monitoring. It analyzes Indian financial markets, lets the owner create and manage trading strategies, backtest them, paper trade them, generate alerts, and eventually execute trades through a broker API.

Not intended to be sold, offered as advisory, or used to give recommendations to third parties.

## 2. Vision

- A personal trading operating system: the user sets strategy/risk rules, software handles repetitive analysis, monitoring, testing, alerting, and eventually execution.
- Minimize screen time and emotional/manual decision-making.
- Strategy logic explicit, testable, versioned, auditable.
- AI as an analysis/filtering layer, never an oracle.
- Start with Indian equities/derivatives; keep architecture extensible (commodities, crypto, forex later).

## 3. Non-Goals for Phase 1

No real-money trading. No broker order execution. No public/advisory product. No multi-user SaaS. No profitability guarantee. No HFT infrastructure.

## 4. Market Scope

NSE/BSE equities, NIFTY 50 / BANK NIFTY. Future: equity derivatives, options, commodities, crypto, forex.

## 5. Technology Stack — Locked

| Layer | Choice | Rationale |
|---|---|---|
| Backend | Python + Django | Existing skill |
| API layer | Django REST Framework, where an API is genuinely needed (e.g. chart data endpoints) | — |
| Frontend | Django templates + HTML/CSS + vanilla JavaScript | No React experience; single-user dashboard doesn't need a component-based SPA |
| Interactivity (optional) | htmx and/or Alpine.js | Partial-page updates, simple reactivity, no build pipeline |
| Charting | TradingView `lightweight-charts` (plain JS) — free, Apache 2.0, personal use permitted | Drops into a Django template directly. **License condition**: keep the default TradingView branding visible, or if removed, add the attribution notice + link to tradingview.com per the NOTICE file |
| Live data push (server → browser) | Django Channels (ASGI), Redis as channel layer | Needed to push live ticks/candles to the browser; reuses the Redis instance already planned for Celery |
| Database | PostgreSQL (prod); SQLite OK for early local dev | — |
| Background jobs | Celery + Redis (or equivalent) | — |
| Deployment | VPS (Linux), static IP required from Phase 3 onward (SEBI compliance, §11) | Reuses existing deployment pattern |

**Frontend decision is locked** — revisit only if a genuinely complex, highly interactive dashboard can't reasonably be built with templates + htmx/Alpine, not by default preference.

## 6. Broker & Data API Strategy

| Item | Decision |
|---|---|
| Development-phase broker/data API | **Fyers API** — free trading API, free live + historical market data |
| Reason | No existing Zerodha demat account; Fyers has zero cost to start building against |
| Target production broker (optional, later) | **Zerodha Kite Connect** (₹500/mo, bundles live+historical data+execution) — only if/when a Zerodha account is opened |
| Migration approach | Broker-adapter interface (§7) — swapping brokers means adding one adapter, not rewriting strategy/backtesting code |

This is a two-broker-capable design from day one, even though only Fyers is connected at first.

## 7. Broker Abstraction — Mandatory Architecture Requirement

**Hard requirement, not optional.** All broker/data interaction goes through one internal interface, implemented once per broker as an adapter. No other module calls a broker SDK directly.

Required interface methods:
- `get_historical_candles(instrument, interval, from, to)` → internal candle format
- `get_live_quote(instrument)` / `subscribe_ticks(instruments)` → internal tick format
- `place_order(order)` / `modify_order()` / `cancel_order()` → internal order-status format (Phase 3+)
- `get_positions()` / `get_holdings()` / `get_order_status()` (Phase 3+)
- `get_instrument_master()` → resolves each broker's own instrument identifier to one internal instrument ID

**Internal instrument identifier**: strategies, backtests, and paper-trading records reference instruments by one internal ID stable across brokers — never a broker's raw symbol format directly. Each adapter maps to/from its broker's format at the boundary only.

**Must never happen**: broker-specific symbol strings, response fields, order-type codes, or auth/token logic appearing outside the adapter module (`marketdata/`, `execution/`). No parallel code path written "for Kite later" instead of a second adapter implementing the same interface.

**Acceptance check**: deleting the Fyers adapter and swapping in a stub adapter returning fixed sample data must not require touching any file outside `marketdata/` and `execution/`. If it does, the abstraction has leaked.

## 8. Live Chart & Live Analysis Data Flow

Both historical and live charting run entirely on the Fyers connection already established in §6/§7 — no separate data provider or TradingView data integration is needed. TradingView's `lightweight-charts` is a rendering library only; it does not supply data.

```
Fyers WebSocket (ticks)
   → Fyers adapter (marketdata/) — broker-specific parsing, isolated here
   → Candle aggregator (marketdata/) — broker-agnostic; builds OHLC bars from ticks
   → Django Channels consumer — pushes finalized/in-progress bar to connected browsers
   → Browser: plain JS WebSocket client
   → lightweight-charts: candleSeries.update(bar)
```

**Candle aggregator** is a named component of `marketdata/`: pure Python, takes a tick stream, returns the current/finalized OHLC bar for a given interval. Independently unit-testable, same as indicators (§12).

**Build order**: static historical chart first (proves the Fyers historical adapter + charting library work together), live layer added after — not both at once.

**Scope boundary — reinforced, not new**: live chart, live indicators, live strategy signals, and live paper-trading P&L are all Phase 1 (analysis and simulation only). None of this places a real order. A signal becoming an actual order on a live account only happens in Phase 3, gated by explicit per-order approval, order preview, the kill switch, and the SEBI Strategy-ID/static-IP requirements (§11). Live data making the *chart* feel real-time does not change which phase live *execution* belongs to.

## 9. Fee & Slippage Model

Independent of broker/data decision — a locally maintained, versioned config, not fetched from any API.

| Charge | Applies to | Source of truth |
|---|---|---|
| Brokerage | Per order, by product type | Broker's published rate card |
| STT | Buy/sell, by segment | Government-set; changes periodically |
| Exchange transaction charge | Turnover-based | NSE/BSE published schedule |
| GST | 18% on brokerage + exchange + SEBI charges | Government rate |
| SEBI turnover fee | Turnover-based | SEBI published rate |
| Stamp duty | Buy side only | State-government rate, nationally unified |
| Slippage | Configurable %, by instrument liquidity | Your own documented assumption |

**Rule**: fee schedules are a dated, versioned table (not a single constant) so a backtest spanning years applies the rate that was actually in force on each trade's date. A backtest is not valid for review until run with the fee model enabled — zero-fee backtests are permitted only as an explicitly labeled "gross, pre-cost" diagnostic.

## 10. Architecture Skeleton

```
trading_platform/
├── core/                  # auth, dashboard shell, settings, env config
├── marketdata/            # OHLCV ingestion, indicators, timestamps (source-tagged) — broker adapters live here
├── strategies/            # strategy definitions, versioning, entry/exit/risk rules
├── backtesting/           # backtest engine, equity curve, metrics, fee model
├── papertrading/          # virtual portfolio, fills, P&L
├── risk/                  # position sizing, exposure limits, kill switch — used by all modules above
├── ai/                    # scoring/ranking layer — isolated, called by strategies, never authoritative
├── reports/               # daily/strategy/backtest/paper-trading reports
└── execution/             # Phase 3+ — broker order adapter, order preview, approval flow
```

No strategy logic in views or templates. Strategy, risk, and AI modules are plain Python, independently unit-testable.

## 11. SEBI Algo-Trading Compliance

SEBI's algo-trading framework became mandatory for all brokers 1 April 2026. Doesn't block Phase 1–2 (no live orders exist yet); two requirements are architectural and should be designed for now:

- Below SEBI's 10-orders-per-second-per-exchange-per-client threshold, no separate registration is required for personal, non-resold automated trading.
- Every live order must carry an exchange-assigned Algo-ID/Strategy-ID obtained through the broker (per-broker onboarding step at Phase 3).
- A **static IP** is required for API order placement from April 2026 — the VPS deployment (§5) satisfies this if the provider assigns a static IP.
- A functioning **kill switch** must exist before the first live order (already required by §13 (Risk Management) and §20 (Security & Safety); now also a regulatory requirement).
- **Action item, not yet due**: re-confirm current broker-specific onboarding steps for Strategy-ID and static-IP registration when Phase 3 actually begins — framework is new enough (mid-2026) that broker processes may still be settling.

## 12. Phase 1 — Functional Requirements

**Auth & Security**: login/logout, secure password handling, session management, protected pages, env vars for secrets, no hardcoded broker credentials.

**Main Dashboard**: market regime, NIFTY/BANK NIFTY overview, breadth, top movers, breakout candidates, recent signals, paper P&L, open positions, risk utilization, recent errors.

**Stock Analysis**: search/select stock, price chart, OHLCV, EMA/SMA/RSI/MACD/ATR, support/resistance, trend classification, relative strength, sector info, AI-assisted summary.

**Market Analysis**: index trend, breadth, volatility, sector performance, regime classification.

**Strategy Management**: create/edit/duplicate/archive/activate strategies with entry/exit/stop/target/trailing-stop/position-sizing rules, max positions, max capital, max risk/trade, min risk/reward, versioning.

**Strategy Categories**: range, breakout, trend-following, momentum, mean-reversion, custom rule-based; architecture supports adding types without rewriting the app.

**Backtesting**: select strategy version/instruments/date range/timeframe/capital; apply position-sizing and risk rules; realistic fees (§9) and slippage; trade-by-trade results; equity curve; compare versions; reproducible results. Metrics: total return, CAGR, win rate, avg win/loss, profit factor, max drawdown, risk/reward stats, trade count, largest win/loss, max consecutive win/loss streaks, Sharpe ratio (or documented equivalent).

**Paper Trading**: virtual portfolio, live/delayed data, strategy-generated virtual orders, documented fill model, stop/target/trailing simulation, position tracking, realized/unrealized P&L, trade history, transaction-cost simulation.

**Risk Management** (mandatory across every phase): risk per trade, max daily/weekly/monthly loss, max exposure, max open positions, max position size, max sector exposure, min risk/reward, stop-loss requirement, trading halt on breach, risk display before every simulated/live trade.

## 13. Phase 2 — Alert System

Strategy-based entry/exit alerts, strong buy/sell alerts, breakout/breakdown alerts, performance alerts, regime-change alerts, paper-trade notifications. Telegram/email/push. Alert history + acknowledgement. Anti-duplicate logic (key by strategy+instrument+signal type+date).

Reuse the exact strategy-evaluation code from backtesting/paper trading — don't build a second signal-detection path.

## 14. Phase 3 — Broker Integration, User-Approval Gated

Broker API integration (built as the isolated adapter from §7). Order preview (entry, quantity, stop, target, estimated risk/reward) mandatory before any order call. Explicit approval before every live order. Order-status tracking, partial fill/rejection handling, broker/API error handling. Emergency kill switch. Complete audit log. Strategy-ID tagging and static IP per §11.

## 15. Phase 4 — Fully Automated Trading

Only after Phase 3 has run with manual approval for a meaningful stretch (weeks, not days) with no missed edge cases. Automatic signal execution, order placement, stop/target management, exits. Position reconciliation with broker. Daily loss circuit breaker. Exposure limits. Duplicate-order protection. API failure protection. Emergency global kill switch. Automatic recovery/reconciliation after restart. Detailed audit trail.

## 16. AI Layer

Sentiment analysis, regime classification, stock ranking/scoring, news sentiment (where licensing permits), setup-quality scoring, anomaly detection, post-trade analysis. **Defer most of this past Phase 1** — it's a project on its own; Phase 1 §12 doesn't require it. Every AI output must show inputs/features used, model/version info, confidence/score, and a clear line between model output and deterministic rules. AI is never authoritative — it's advisory input to a documented strategy rule, or it doesn't count.

## 17. UI/UX Requirements

Dark-first professional interface, optional light mode. Responsive desktop/tablet/mobile. Hierarchy: market state → opportunities → risk → actions. Avoid clutter. Every signal shows why it fired. Risk info visually prominent. Confirmation dialogs for destructive/live actions. Clear loading/empty/error/data-unavailable states. Reference (not copy) UX from TradingView (charting/density), Zerodha Kite (workflow simplicity), QuantConnect (research/backtesting concepts).

## 18. Navigation

Dashboard · Market · Stock Scanner · Stock Analysis · Strategies · Backtesting · Paper Trading · Portfolio · Trade Journal · Alerts (Phase 2) · Broker/Execution (Phase 3+) · Reports · Settings

## 19. Data & Reliability Requirements

Record data source + timestamp for market data. Handle missing/invalid data safely — never silently substitute. Log background jobs/failures. Strategy versions immutable after a backtest is recorded. Store enough to reproduce a backtest. Timezone-aware timestamps (Asia/Kolkata primary). Separate market-data failures from strategy failures.

## 20. Security & Safety

Secrets outside source control (env vars/secret storage). Auth required for sensitive actions. Global kill switch (Phase 3/4). Duplicate-order prevention. Validate quantity/price/instrument/risk before execution. Log all execution decisions. No accidental live trading from dev/test mode. Explicit mode indicators: `BACKTEST` / `PAPER` / `LIVE`.

## 21. Reporting & Analytics

Daily market report, strategy performance report, backtest report, paper-trading report, portfolio P&L, drawdown monitoring, risk utilization, trade journal, strategy comparison, monthly summary.

## 22. Development Principles

Modular architecture. Business logic testable independent of UI. No strategy logic in Django templates/views. Separate data/strategy/AI/risk/execution/reporting services. Unit tests for indicators/signals/position sizing/risk rules. Integration tests for broker execution before live deployment. Git with meaningful commits. Document configuration/assumptions. **Build Phase 1 completely before enabling Phase 2.**

## 23. Phase Acceptance Criteria

- **Phase 1**: authenticated Django app; stock/market analysis; strategy management; backtesting (with fee model, §9); paper trading; risk management; portfolio/P&L; reports; no real-money execution; broker abstraction (§7) satisfies its own acceptance check.
- **Phase 2**: reliable strategy/market alerts with notification history and anti-duplicate controls.
- **Phase 3**: broker integration with explicit approval, order preview, risk validation, status tracking, kill switch, Strategy-ID tagging, static IP.
- **Phase 4**: fully automated execution with reconciliation, circuit breakers, failure handling, audit logs, emergency controls.

## 24. Key Product Rules

- A strategy must be testable before it can be used for paper trading.
- A strategy is not enabled for live execution solely because its backtest is profitable.
- Backtests must account for realistic costs and slippage (§9).
- Paper trading must run for a meaningful validation period before live use.
- AI scores are advisory/filtering inputs unless explicitly incorporated into a documented strategy rule.
- Risk limits override strategy signals.
- Live execution is always disabled by default.
- The system fails safely when data, broker connectivity, or internal services fail.

## 25. Important Disclaimer

Personal research and trading automation project. Backtested or AI-generated results do not guarantee future performance. Market conditions can change, models can fail, automated systems can suffer technical or execution failures. Live trading only after appropriate validation, risk controls, and compliance checks applicable to the broker and jurisdiction.

---

### Change log
- **v1.0**: original PRD — full scope, phases, architecture.
- **v1.1**: locked broker/data decision (Fyers dev → Kite optional), mandatory broker-abstraction requirement, versioned fee model, SEBI compliance notes.
- **v1.2**: locked technology stack — Django templates + HTML/JS (no React), htmx/Alpine optional, TradingView lightweight-charts.
- **v1.3**: added live chart/live analysis data flow (§8) — Fyers WebSocket ticks → candle aggregator → Django Channels → browser; added Django Channels to tech stack (§5); noted lightweight-charts attribution requirement; reinforced live-analysis-vs-live-execution phase boundary.
