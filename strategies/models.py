from django.db import models


class Strategy(models.Model):
    """
    A named strategy 'slot'. All actual rules/parameters live on
    StrategyVersion — this model is just identity + status.
    """

    CATEGORY_CHOICES = [
        ("range", "Range"),
        ("breakout", "Breakout"),
        ("trend_following", "Trend Following"),
        ("momentum", "Momentum"),
        ("mean_reversion", "Mean Reversion"),
        ("custom", "Custom"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("archived", "Archived"),
    ]

    name = models.CharField(max_length=128, unique=True)
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "strategies"

    def __str__(self):
        return self.name

    @property
    def latest_version(self):
        return self.versions.order_by("-version_number").first()


class StrategyVersion(models.Model):
    """
    One immutable-once-backtested version of a Strategy's rules and risk
    parameters (PRD S19: "strategy versions immutable after a backtest is
    recorded"). `is_locked` is set True the first time a backtest run is
    recorded against this version (Backtesting milestone, not yet built) —
    editing a locked version creates version_number + 1 instead of mutating
    it. Always unlocked today since nothing records backtests yet, but the
    branching exists now so nothing about this model needs revisiting later.

    entry_rules / exit_rules use the condition schema evaluated by
    strategies/rules.py — see that module for the shape.
    """

    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()

    entry_rules = models.JSONField()
    exit_rules = models.JSONField()

    # Each: {"type": "pct"|"atr"|"rr", "value": <number>} — interpretation
    # (e.g. "atr" stop = value * ATR below entry) belongs to whichever
    # module actually simulates trades (Backtesting/Paper Trading); this
    # model only stores the configured parameters.
    stop_loss = models.JSONField()
    target = models.JSONField()
    trailing_stop = models.JSONField(null=True, blank=True)
    position_sizing = models.JSONField()

    max_positions = models.PositiveIntegerField(default=1)
    max_capital_pct = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    max_risk_per_trade_pct = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    min_risk_reward = models.DecimalField(max_digits=5, decimal_places=2, default=1)

    notes = models.TextField(blank=True)
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["strategy", "version_number"], name="uniq_strategy_version"),
        ]
        ordering = ["strategy", "-version_number"]

    def __str__(self):
        return f"{self.strategy.name} v{self.version_number}"
