from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

# Placeholder cards for the Phase 1 dashboard shell (PRD §12 "Main Dashboard").
# Each card will be wired up to a real data source in a later milestone —
# none of this is strategy logic (CLAUDE.md rule 3), it's just view-layer
# placement of where that data will render.
DASHBOARD_CARDS = [
    {"key": "market_regime", "title": "Market Regime", "description": "Current market regime classification."},
    {"key": "index_overview", "title": "NIFTY / BANK NIFTY Overview", "description": "Index levels and trend."},
    {"key": "breadth", "title": "Market Breadth", "description": "Advance/decline and breadth indicators."},
    {"key": "top_movers", "title": "Top Movers", "description": "Largest gainers and losers."},
    {"key": "breakout_candidates", "title": "Breakout Candidates", "description": "Stocks approaching breakout levels."},
    {"key": "recent_signals", "title": "Recent Signals", "description": "Latest strategy-generated signals."},
    {"key": "paper_pnl", "title": "Paper P&L", "description": "Virtual portfolio profit and loss."},
    {"key": "open_positions", "title": "Open Positions", "description": "Currently open paper/live positions."},
    {"key": "risk_utilization", "title": "Risk Utilization", "description": "Exposure vs. configured risk limits."},
    {"key": "recent_errors", "title": "Recent Errors", "description": "Market data and job failures."},
]


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"
    login_url = "core:login"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cards"] = DASHBOARD_CARDS
        context["trading_mode"] = settings.TRADING_MODE
        return context
