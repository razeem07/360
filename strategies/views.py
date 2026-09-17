import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from rest_framework.response import Response
from rest_framework.views import APIView

from marketdata.models import Instrument
from marketdata.views import AVAILABLE_TIMEFRAMES, DEFAULT_TIMEFRAME, TIMEFRAME_LABELS

from .analysis import build_signal_preview
from .models import Strategy, StrategyVersion
from .rules import RuleError


def _parsed_amount(post, prefix: str) -> dict | None:
    """Reads '<prefix>_type' + '<prefix>_value' form fields into {"type","value"}."""
    amount_type = post.get(f"{prefix}_type")
    value = post.get(f"{prefix}_value")
    if not amount_type or not value:
        return None
    return {"type": amount_type, "value": float(value)}


def _parsed_rules(post, field_name: str) -> dict:
    raw = post.get(field_name, "")
    try:
        return json.loads(raw) if raw else {"all": []}
    except json.JSONDecodeError as exc:
        raise RuleError(f"Malformed {field_name}: {exc}") from exc


class StrategyListView(LoginRequiredMixin, View):
    login_url = "core:login"

    def get(self, request):
        strategies = Strategy.objects.prefetch_related("versions").all()
        return render(request, "strategies/strategy_list.html", {"strategies": strategies})


class StrategyFormView(LoginRequiredMixin, View):
    """Create (no strategy_id) or edit (strategy_id) a strategy's current version."""

    login_url = "core:login"

    def get(self, request, strategy_id=None):
        strategy = get_object_or_404(Strategy, pk=strategy_id) if strategy_id else None
        version = strategy.latest_version if strategy else None
        return render(request, "strategies/strategy_form.html", {
            "strategy": strategy,
            "version": version,
            "category_choices": Strategy.CATEGORY_CHOICES,
        })

    def post(self, request, strategy_id=None):
        try:
            entry_rules = _parsed_rules(request.POST, "entry_rules_json")
            exit_rules = _parsed_rules(request.POST, "exit_rules_json")
        except RuleError as exc:
            strategy = get_object_or_404(Strategy, pk=strategy_id) if strategy_id else None
            return render(request, "strategies/strategy_form.html", {
                "strategy": strategy,
                "version": strategy.latest_version if strategy else None,
                "category_choices": Strategy.CATEGORY_CHOICES,
                "error": str(exc),
            }, status=400)

        version_fields = dict(
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            stop_loss=_parsed_amount(request.POST, "stop_loss") or {"type": "pct", "value": 2},
            target=_parsed_amount(request.POST, "target") or {"type": "pct", "value": 4},
            trailing_stop=_parsed_amount(request.POST, "trailing_stop"),
            position_sizing=_parsed_amount(request.POST, "position_sizing") or {"type": "fixed_pct", "value": 10},
            max_positions=int(request.POST.get("max_positions", 1)),
            max_capital_pct=request.POST.get("max_capital_pct", 100),
            max_risk_per_trade_pct=request.POST.get("max_risk_per_trade_pct", 1),
            min_risk_reward=request.POST.get("min_risk_reward", 1),
            notes=request.POST.get("notes", ""),
        )

        if strategy_id:
            strategy = get_object_or_404(Strategy, pk=strategy_id)
            strategy.name = request.POST.get("name", strategy.name)
            strategy.category = request.POST.get("category", strategy.category)
            strategy.save()

            current = strategy.latest_version
            if current is None or current.is_locked:
                next_number = (current.version_number + 1) if current else 1
                StrategyVersion.objects.create(strategy=strategy, version_number=next_number, **version_fields)
            else:
                for field, value in version_fields.items():
                    setattr(current, field, value)
                current.save()
        else:
            strategy = Strategy.objects.create(
                name=request.POST["name"], category=request.POST.get("category", "custom"),
            )
            StrategyVersion.objects.create(strategy=strategy, version_number=1, **version_fields)

        return redirect("strategies:detail", strategy_id=strategy.id)


class StrategyDetailView(LoginRequiredMixin, View):
    login_url = "core:login"

    def get(self, request, strategy_id):
        strategy = get_object_or_404(Strategy, pk=strategy_id)
        instruments = Instrument.objects.filter(is_active=True)
        symbol = request.GET.get("symbol")
        timeframe = request.GET.get("timeframe", DEFAULT_TIMEFRAME)
        if timeframe not in AVAILABLE_TIMEFRAMES:
            timeframe = DEFAULT_TIMEFRAME

        instrument = None
        if symbol:
            instrument = instruments.filter(internal_id=symbol).first()
        if instrument is None:
            instrument = instruments.first()  # e.g. a stale/mistyped symbol param — fall back rather than crash

        return render(request, "strategies/strategy_detail.html", {
            "strategy": strategy,
            "version": strategy.latest_version,
            "instruments": instruments,
            "selected_instrument": instrument,
            "timeframe": timeframe,
            "available_timeframes": [(tf, TIMEFRAME_LABELS[tf]) for tf in AVAILABLE_TIMEFRAMES],
        })


class StrategyDuplicateView(LoginRequiredMixin, View):
    login_url = "core:login"

    def post(self, request, strategy_id):
        source = get_object_or_404(Strategy, pk=strategy_id)
        source_version = source.latest_version

        base_name = f"{source.name} (copy)"
        name, suffix = base_name, 1
        while Strategy.objects.filter(name=name).exists():
            suffix += 1
            name = f"{base_name} {suffix}"

        new_strategy = Strategy.objects.create(name=name, category=source.category)
        if source_version:
            StrategyVersion.objects.create(
                strategy=new_strategy, version_number=1,
                entry_rules=source_version.entry_rules, exit_rules=source_version.exit_rules,
                stop_loss=source_version.stop_loss, target=source_version.target,
                trailing_stop=source_version.trailing_stop, position_sizing=source_version.position_sizing,
                max_positions=source_version.max_positions, max_capital_pct=source_version.max_capital_pct,
                max_risk_per_trade_pct=source_version.max_risk_per_trade_pct,
                min_risk_reward=source_version.min_risk_reward, notes=source_version.notes,
            )
        return redirect("strategies:edit", strategy_id=new_strategy.id)


class StrategyStatusView(LoginRequiredMixin, View):
    """POST-only: set a strategy's status (archive/activate). No execution
    implication in Phase 1 — this is just a filter/organization flag."""

    login_url = "core:login"

    def post(self, request, strategy_id, new_status):
        strategy = get_object_or_404(Strategy, pk=strategy_id)
        if new_status in dict(Strategy.STATUS_CHOICES):
            strategy.status = new_status
            strategy.save()
        return redirect("strategies:list")


class StrategyPreviewAPIView(APIView):
    """
    Chart-marker data for the signal preview (mirrors marketdata's
    CandleDataAPIView) — where this strategy version's entry/exit rules
    would have fired historically. Auth via REST_FRAMEWORK's default
    IsAuthenticated permission.
    """

    def get(self, request, strategy_id):
        strategy = get_object_or_404(Strategy, pk=strategy_id)
        version = strategy.latest_version
        instrument = get_object_or_404(Instrument, internal_id=request.GET.get("symbol"))
        timeframe = request.GET.get("timeframe", DEFAULT_TIMEFRAME)
        if timeframe not in AVAILABLE_TIMEFRAMES:
            timeframe = DEFAULT_TIMEFRAME

        if version is None:
            return Response({"entry_times": [], "exit_times": [], "bar_count": 0})

        try:
            preview = build_signal_preview(version, instrument, timeframe)
        except RuleError as exc:
            return Response({"error": str(exc)}, status=400)

        return Response({
            "entry_times": preview.entry_times,
            "exit_times": preview.exit_times,
            "bar_count": preview.bar_count,
        })
