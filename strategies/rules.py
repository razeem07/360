"""
Strategy rule engine — pure Python, no ORM/Django imports (same philosophy
as marketdata/indicators.py), so it's independently unit-testable and reads
its bars from any source (real DB-backed Candle rows, resampled bars,
backtest fixtures, ...).

Rule schema (flat — one level of AND/OR, no nested boolean trees):

    {"all": [condition, ...]}   # every condition must hold
    {"any": [condition, ...]}   # at least one condition must hold

Each condition compares two operands:

    {"left": <operand>, "operator": <op>, "right": <operand>}

An operand is either a fixed value or an indicator reference:

    {"value": 30}
    {"indicator": "rsi", "params": {"period": 14}}

Supported indicators: close, open, high, low, volume (raw fields), sma,
ema, rsi, atr, vwap (rolling), macd_line, macd_signal, macd_hist — all
computed via marketdata.indicators, so this engine can never disagree with
what Stock Analysis shows for the same indicator.

Supported operators: <, <=, >, >=, ==, crosses_above, crosses_below.

PRD S19 discipline: a bar in an indicator's warm-up period (value is None)
makes any condition touching it False for that bar — never an error, never
a guessed value.
"""

from typing import Literal

from marketdata import indicators
from marketdata.resampling import PlainBar

_COMPARISON_OPS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
}
_CROSS_OPS = {"crosses_above", "crosses_below"}
SUPPORTED_OPERATORS = set(_COMPARISON_OPS) | _CROSS_OPS

_RAW_FIELDS = {"close", "open", "high", "low", "volume"}
_SUPPORTED_INDICATORS = _RAW_FIELDS | {"sma", "ema", "rsi", "atr", "vwap", "macd_line", "macd_signal", "macd_hist"}


class RuleError(ValueError):
    """Malformed ruleset or condition — never silently ignored."""


def _params_key(params: dict) -> tuple:
    return tuple(sorted(params.items()))


def _compute_indicator_series(name: str, params: dict, bars: list[PlainBar]) -> list[float | None]:
    if name in _RAW_FIELDS:
        return [getattr(b, name) for b in bars]

    closes = [b.close for b in bars]

    if name == "sma":
        return indicators.sma(closes, params.get("period", 20))
    if name == "ema":
        return indicators.ema(closes, params.get("period", 20))
    if name == "rsi":
        return indicators.rsi(closes, params.get("period", 14))
    if name in ("atr", "vwap"):
        ind_bars = [indicators.Bar(high=b.high, low=b.low, close=b.close, volume=b.volume) for b in bars]
        if name == "atr":
            return indicators.atr(ind_bars, params.get("period", 14))
        return indicators.rolling_vwap(ind_bars, params.get("period", 20))
    if name in ("macd_line", "macd_signal", "macd_hist"):
        result = indicators.macd(closes, params.get("fast", 12), params.get("slow", 26), params.get("signal", 9))
        return {"macd_line": result.macd_line, "macd_signal": result.signal_line, "macd_hist": result.histogram}[name]

    raise RuleError(f"Unsupported indicator {name!r}; supported: {sorted(_SUPPORTED_INDICATORS)}")


class _SeriesCache:
    """Computes each unique (indicator, params) series at most once per evaluate_ruleset() call."""

    def __init__(self, bars: list[PlainBar]):
        self._bars = bars
        self._cache: dict[tuple, list] = {}

    def resolve(self, operand: dict) -> list[float | None]:
        if "value" in operand:
            return [operand["value"]] * len(self._bars)

        if "indicator" not in operand:
            raise RuleError(f"Operand must have 'value' or 'indicator': {operand!r}")

        name = operand["indicator"]
        params = operand.get("params", {})
        if name not in _SUPPORTED_INDICATORS:
            raise RuleError(f"Unsupported indicator {name!r}; supported: {sorted(_SUPPORTED_INDICATORS)}")

        key = (name, _params_key(params))
        if key not in self._cache:
            self._cache[key] = _compute_indicator_series(name, params, self._bars)
        return self._cache[key]


def _evaluate_condition(condition: dict, cache: _SeriesCache, n_bars: int) -> list[bool]:
    for required in ("left", "operator", "right"):
        if required not in condition:
            raise RuleError(f"Condition missing {required!r}: {condition!r}")

    operator = condition["operator"]
    if operator not in SUPPORTED_OPERATORS:
        raise RuleError(f"Unsupported operator {operator!r}; supported: {sorted(SUPPORTED_OPERATORS)}")

    left = cache.resolve(condition["left"])
    right = cache.resolve(condition["right"])

    out = [False] * n_bars

    if operator in _COMPARISON_OPS:
        op = _COMPARISON_OPS[operator]
        for i in range(n_bars):
            if left[i] is not None and right[i] is not None:
                out[i] = op(left[i], right[i])
        return out

    # crosses_above / crosses_below need the previous bar too.
    for i in range(1, n_bars):
        prev_l, prev_r, cur_l, cur_r = left[i - 1], right[i - 1], left[i], right[i]
        if None in (prev_l, prev_r, cur_l, cur_r):
            continue
        if operator == "crosses_above":
            out[i] = prev_l <= prev_r and cur_l > cur_r
        else:
            out[i] = prev_l >= prev_r and cur_l < cur_r
    return out


def evaluate_ruleset(ruleset: dict, bars: list[PlainBar]) -> list[bool]:
    """Returns one bool per bar: whether the ruleset holds at that bar."""
    if not bars:
        return []

    combinator: Literal["all", "any"]
    if "all" in ruleset:
        combinator, conditions = "all", ruleset["all"]
    elif "any" in ruleset:
        combinator, conditions = "any", ruleset["any"]
    else:
        raise RuleError(f"Ruleset must have 'all' or 'any': {ruleset!r}")

    if not isinstance(conditions, list) or not conditions:
        raise RuleError(f"'{combinator}' must be a non-empty list of conditions: {ruleset!r}")

    cache = _SeriesCache(bars)
    n_bars = len(bars)
    condition_results = [_evaluate_condition(c, cache, n_bars) for c in conditions]

    combine = all if combinator == "all" else any
    return [combine(cr[i] for cr in condition_results) for i in range(n_bars)]
