"""analytics_tool — Statistical analysis and data insights, no external dependencies."""
from __future__ import annotations
import json, math, re, logging
from collections import Counter

logger = logging.getLogger(__name__)


def analytics_tool(data: str, action: str = "stats") -> str:
    """
    Run statistical analysis on numeric data.

    data   : Comma- or newline-separated numbers  OR  a JSON array/object.
             For JSON object: analysis runs on all numeric values collectively.
             For 'correlation': two comma-separated series split by '|'
               e.g. "1,2,3 | 2,4,6"
    action : stats | histogram | percentile | correlation | frequency |
             normalize | zscore | outliers | describe | moving_avg

    Actions:
        stats      : Mean, median, mode, std, variance, min, max, range, sum.
        histogram  : ASCII bar chart of value distribution.
        percentile : P10, P25, P50, P75, P90, P95, P99.
        correlation: Pearson r between two series (split with ' | ').
        frequency  : Value counts sorted by frequency.
        normalize  : Min-max normalize values to [0, 1].
        zscore     : Z-score for each value ((x - mean) / std).
        outliers   : Values > 2 std dev from mean (IQR method also shown).
        describe   : Comprehensive summary combining stats + percentiles.
        moving_avg : 3-period simple moving average.
    """
    if not data or not isinstance(data, str):
        return "Error: 'data' must be a non-empty string of numbers."

    action = (action or "stats").strip().lower()

    # ── Parse data ────────────────────────────────────────────────────
    if action == "correlation":
        if "|" not in data:
            return "Error: 'correlation' requires two series separated by ' | '."
        parts = data.split("|", 1)
        xs = _parse_numbers(parts[0])
        ys = _parse_numbers(parts[1])
        if xs is None: return "Error: Could not parse first series."
        if ys is None: return "Error: Could not parse second series."
        return _correlation(xs, ys)

    # Check for JSON input
    stripped = data.strip()
    nums: list[float] | None = None
    if stripped.startswith(("[", "{")):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                nums = [float(v) for v in parsed if isinstance(v, (int, float))]
            elif isinstance(parsed, dict):
                nums = [float(v) for v in parsed.values() if isinstance(v, (int, float))]
        except (json.JSONDecodeError, ValueError):
            pass

    if nums is None:
        nums = _parse_numbers(data)

    if nums is None or len(nums) == 0:
        return "Error: Could not parse any numbers from input."

    # ── Dispatch ──────────────────────────────────────────────────────
    if action == "stats":      return _stats(nums)
    if action == "histogram":  return _histogram(nums)
    if action == "percentile": return _percentiles(nums)
    if action == "frequency":  return _frequency(nums)
    if action == "normalize":  return _normalize(nums)
    if action == "zscore":     return _zscores(nums)
    if action == "outliers":   return _outliers(nums)
    if action == "describe":   return _describe(nums)
    if action == "moving_avg": return _moving_avg(nums)

    return (
        f"Unknown action '{action}'. Use: stats, histogram, percentile, correlation, "
        "frequency, normalize, zscore, outliers, describe, moving_avg."
    )


# ── number parsing ────────────────────────────────────────────────────────────

def _parse_numbers(s: str) -> list[float] | None:
    tokens = re.split(r"[\s,;\n\t]+", s.strip())
    try:
        nums = [float(t) for t in tokens if t not in ("", "|")]
        return nums if nums else None
    except ValueError:
        return None


# ── statistical primitives ───────────────────────────────────────────────────

def _mean(nums: list[float]) -> float:
    return sum(nums) / len(nums)

def _median(nums: list[float]) -> float:
    s = sorted(nums)
    n = len(s)
    mid = n // 2
    return (s[mid - 1] + s[mid]) / 2 if n % 2 == 0 else s[mid]

def _variance(nums: list[float]) -> float:
    if len(nums) < 2:
        return 0.0
    m = _mean(nums)
    return sum((x - m) ** 2 for x in nums) / (len(nums) - 1)  # sample variance

def _std(nums: list[float]) -> float:
    return math.sqrt(_variance(nums))

def _percentile(nums: list[float], p: float) -> float:
    s = sorted(nums)
    idx = (p / 100) * (len(s) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (idx - lo) * (s[hi] - s[lo])

def _mode(nums: list[float]) -> str:
    c = Counter(nums)
    max_count = max(c.values())
    modes = [k for k, v in c.items() if v == max_count]
    if len(modes) == len(set(nums)):
        return "no mode (all values unique)"
    return ", ".join(str(m) for m in sorted(modes)[:5])


# ── action implementations ────────────────────────────────────────────────────

def _stats(nums: list[float]) -> str:
    n = len(nums)
    mean = _mean(nums)
    std  = _std(nums)
    return (
        f"Count    : {n}\n"
        f"Sum      : {sum(nums):.4g}\n"
        f"Mean     : {mean:.4g}\n"
        f"Median   : {_median(nums):.4g}\n"
        f"Mode     : {_mode(nums)}\n"
        f"Std Dev  : {std:.4g}\n"
        f"Variance : {_variance(nums):.4g}\n"
        f"Min      : {min(nums):.4g}\n"
        f"Max      : {max(nums):.4g}\n"
        f"Range    : {max(nums) - min(nums):.4g}"
    )


def _histogram(nums: list[float], bins: int = 10, width: int = 40) -> str:
    mn, mx = min(nums), max(nums)
    if mn == mx:
        return f"All values are equal: {mn}"
    step = (mx - mn) / bins
    counts = [0] * bins
    for v in nums:
        idx = min(int((v - mn) / step), bins - 1)
        counts[idx] += 1
    max_count = max(counts) or 1
    lines = ["Distribution (ASCII histogram):"]
    for i, c in enumerate(counts):
        lo = mn + i * step
        hi = lo + step
        bar = "█" * int(c / max_count * width)
        lines.append(f"  {lo:8.2f}–{hi:8.2f} │ {bar:<{width}} {c}")
    return "\n".join(lines)


def _percentiles(nums: list[float]) -> str:
    ps = [10, 25, 50, 75, 90, 95, 99]
    lines = ["Percentiles:"]
    for p in ps:
        lines.append(f"  P{p:<3} : {_percentile(nums, p):.4g}")
    return "\n".join(lines)


def _correlation(xs: list[float], ys: list[float]) -> str:
    n = min(len(xs), len(ys))
    if n < 2:
        return "Error: Need at least 2 data points in each series."
    xs, ys = xs[:n], ys[:n]
    mx, my = _mean(xs), _mean(ys)
    num   = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom = math.sqrt(sum((x - mx)**2 for x in xs) * sum((y - my)**2 for y in ys))
    if denom == 0:
        return "Error: Cannot compute correlation (zero variance in one series)."
    r = num / denom
    if abs(r) > 0.9:   strength = "Very strong"
    elif abs(r) > 0.7: strength = "Strong"
    elif abs(r) > 0.5: strength = "Moderate"
    elif abs(r) > 0.3: strength = "Weak"
    else:              strength = "Very weak / none"
    direction = "positive" if r > 0 else "negative"
    return (
        f"Pearson r  : {r:.4f}\n"
        f"r²         : {r**2:.4f}\n"
        f"Correlation: {strength} {direction}\n"
        f"N          : {n} pairs"
    )


def _frequency(nums: list[float]) -> str:
    c = Counter(nums)
    total = len(nums)
    lines = ["Value Frequency:"]
    for val, count in c.most_common(30):
        pct = count / total * 100
        bar = "▓" * min(int(pct / 2), 30)
        lines.append(f"  {val:>12.4g}  {count:5}  ({pct:5.1f}%)  {bar}")
    if len(c) > 30:
        lines.append(f"  ... ({len(c) - 30} more unique values)")
    return "\n".join(lines)


def _normalize(nums: list[float]) -> str:
    mn, mx = min(nums), max(nums)
    if mn == mx:
        return "Error: All values are equal — cannot normalize."
    normed = [(v - mn) / (mx - mn) for v in nums]
    preview = [f"{v:.4f}" for v in normed[:20]]
    suffix = f" ... ({len(normed) - 20} more)" if len(normed) > 20 else ""
    return (
        f"Original range : [{mn:.4g}, {mx:.4g}]\n"
        f"Normalized [0,1]: [{', '.join(preview)}{suffix}]"
    )


def _zscores(nums: list[float]) -> str:
    mean, std = _mean(nums), _std(nums)
    if std == 0:
        return "Error: Standard deviation is 0 — z-scores undefined."
    zs = [(v - mean) / std for v in nums]
    preview = [f"{z:.2f}" for z in zs[:20]]
    suffix  = f" ... ({len(zs) - 20} more)" if len(zs) > 20 else ""
    return (
        f"Mean  : {mean:.4g}\n"
        f"Std   : {std:.4g}\n"
        f"Z-scores: [{', '.join(preview)}{suffix}]"
    )


def _outliers(nums: list[float]) -> str:
    mean, std = _mean(nums), _std(nums)
    # Std-dev method (|z| > 2)
    sd_outliers = [v for v in nums if abs(v - mean) > 2 * std]
    # IQR method
    q1 = _percentile(nums, 25)
    q3 = _percentile(nums, 75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    iqr_outliers = [v for v in nums if v < lo or v > hi]
    out = [
        f"Values          : {len(nums)}",
        f"Mean ± 2σ method: {len(sd_outliers)} outlier(s)",
    ]
    if sd_outliers:
        out.append("  " + ", ".join(f"{v:.4g}" for v in sorted(sd_outliers)[:20]))
    out += [
        f"IQR method (1.5×IQR fence): {len(iqr_outliers)} outlier(s)  (fence: [{lo:.4g}, {hi:.4g}])",
    ]
    if iqr_outliers:
        out.append("  " + ", ".join(f"{v:.4g}" for v in sorted(iqr_outliers)[:20]))
    return "\n".join(out)


def _describe(nums: list[float]) -> str:
    return _stats(nums) + "\n\n" + _percentiles(nums)


def _moving_avg(nums: list[float], window: int = 3) -> str:
    if len(nums) < window:
        return f"Error: Need at least {window} values for a {window}-period moving average."
    ma = [
        _mean(nums[i:i + window])
        for i in range(len(nums) - window + 1)
    ]
    preview = [f"{v:.4g}" for v in ma[:30]]
    suffix  = f" ... ({len(ma) - 30} more)" if len(ma) > 30 else ""
    return (
        f"Window     : {window}\n"
        f"Input len  : {len(nums)}\n"
        f"Output len : {len(ma)}\n"
        f"Moving avg : [{', '.join(preview)}{suffix}]"
    )
