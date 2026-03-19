"""economic_guardrails.py — Hard economic constraints for agent operations.

Closes BLOCKER 5: Economic Safeguards Weak.

Agents acting in business environments must respect:
    1. Rate limits       — Max operations per time window (sliding window)
    2. Cost constraints  — Hard budget caps with pre-spend checks
    3. Resource caps     — Max concurrent operations, memory, tokens
    4. Quotas            — Per-agent, per-category daily/hourly limits
    5. Action caps       — Per-session / per-hour / per-day total action limits
    6. Throttling        — Automatic slowdown as budget % climbs; manual throttle

All six controls are HARD constraints — operations are BLOCKED when limits
are hit, not just logged.

Usage
-----
    eg = EconomicGuardrails(agent_name="store_bot", monthly_budget_usd=50.0)

    # Check before action
    verdict = eg.check_quota(agent_name="store_bot", category="api_call")
    if not verdict["allowed"]:
        raise PermissionError(verdict["reason"])

    # Record after action
    eg.record_usage(category="api_call", cost_usd=0.01, tokens=500)

    # Set custom limits
    eg.set_rate_limit("api_call", max_per_minute=30, max_per_hour=500)
    eg.set_quota("store_bot", "transaction", daily_limit=100)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Rate Limiter ────────────────────────────────────────────────────────────

class _SlidingWindowCounter:
    """Thread-safe sliding window rate limiter."""

    def __init__(self, max_count: int, window_seconds: float) -> None:
        self.max_count = max_count
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """Check if an action is allowed under the rate limit."""
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            if len(self._timestamps) >= self.max_count:
                return False
            self._timestamps.append(now)
            return True

    def current_count(self) -> int:
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            return len(self._timestamps)

    @property
    def remaining(self) -> int:
        return max(0, self.max_count - self.current_count())


# ── Rate Limit Config ───────────────────────────────────────────────────────

@dataclass
class RateLimitConfig:
    category: str
    max_per_minute: int = 60
    max_per_hour: int = 1000
    max_per_day: int = 10000

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "max_per_minute": self.max_per_minute,
            "max_per_hour": self.max_per_hour,
            "max_per_day": self.max_per_day,
        }


# ── Quota Config ────────────────────────────────────────────────────────────

@dataclass
class QuotaConfig:
    agent_name: str
    category: str
    daily_limit: int = 0       # 0 = unlimited
    hourly_limit: int = 0
    max_cost_per_action: float = 0.0   # 0 = unlimited
    max_concurrent: int = 0    # 0 = unlimited

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent_name,
            "category": self.category,
            "daily_limit": self.daily_limit,
            "hourly_limit": self.hourly_limit,
            "max_cost_per_action": self.max_cost_per_action,
            "max_concurrent": self.max_concurrent,
        }


# ── Action Cap Config ───────────────────────────────────────────────────────

@dataclass
class ActionCapConfig:
    """Hard cap on the total number of external actions an agent may fire."""
    agent_name: str
    session_cap: int = 0     # 0 = unlimited; resets when reset() is called
    hourly_cap: int = 0      # 0 = unlimited; auto-resets every 60 min
    daily_cap: int = 0       # 0 = unlimited; auto-resets every 24 h

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent_name,
            "session_cap": self.session_cap,
            "hourly_cap": self.hourly_cap,
            "daily_cap": self.daily_cap,
        }


# ── Budget Warning Levels ───────────────────────────────────────────────────

_BUDGET_WARN_PCT   = 0.50   # 50 % consumed → WARNING
_BUDGET_ALERT_PCT  = 0.80   # 80 % consumed → ALERT (auto-throttle to 50 %)
_BUDGET_CRITICAL_PCT = 0.95 # 95 % consumed → CRITICAL (auto-throttle to 10 %)


# ── Usage Record ────────────────────────────────────────────────────────────

@dataclass
class UsageRecord:
    category: str
    agent_name: str
    cost_usd: float = 0.0
    tokens: int = 0
    timestamp: float = field(default_factory=time.time)


# ── EconomicGuardrails ─────────────────────────────────────────────────────

class EconomicGuardrails:
    """
    Hard economic constraints for agent operations.

    All checks are BLOCKING — operations are denied when limits are hit.

    Parameters
    ----------
    agent_name        : Default agent name.
    monthly_budget_usd: Hard monthly budget cap.
    default_rate_limit: Default rate limit per category (per minute).
    finops            : Optional FinOpsController for cost tracking.
    """

    def __init__(
        self,
        agent_name: str = "",
        monthly_budget_usd: float = 0.0,
        default_rate_limit: int = 60,
        finops: Any = None,
    ) -> None:
        self.agent_name = agent_name
        self.monthly_budget_usd = monthly_budget_usd
        self._default_rate_limit = default_rate_limit
        self._finops = finops
        self._lock = threading.Lock()

        # Rate limiters: category -> {window_name -> SlidingWindowCounter}
        self._rate_limiters: dict[str, dict[str, _SlidingWindowCounter]] = {}
        self._rate_configs: dict[str, RateLimitConfig] = {}

        # Quotas: (agent, category) -> QuotaConfig
        self._quotas: dict[tuple[str, str], QuotaConfig] = {}

        # Usage tracking
        self._usage: list[UsageRecord] = []
        self._max_usage = 5000
        self._total_cost_usd: float = 0.0
        self._total_tokens: int = 0
        self._concurrent: dict[str, int] = defaultdict(int)  # category -> active count

        # Daily/hourly counters: (agent, category, window_key) -> count
        self._counters: dict[str, int] = defaultdict(int)
        self._counter_resets: dict[str, float] = {}

        # ── Action Caps ─────────────────────────────────────────────────
        # Per-agent config
        self._action_caps: dict[str, ActionCapConfig] = {}
        # action counts: agent -> {window_key -> count}
        self._action_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._action_resets: dict[str, dict[str, float]] = defaultdict(dict)
        # Session counter: counts since last reset()
        self._session_action_counts: dict[str, int] = defaultdict(int)

        # ── Budget warning / auto-throttle ──────────────────────────────
        self._auto_throttle_enabled: bool = True
        self._throttle_rate: float = 1.0  # 1.0 = no throttle

    # ── 1. Rate Limits ────────────────────────────────────────────────────

    def set_rate_limit(
        self,
        category: str,
        max_per_minute: int = 60,
        max_per_hour: int = 1000,
        max_per_day: int = 10000,
    ) -> None:
        """Set rate limits for a category of operations."""
        config = RateLimitConfig(
            category=category,
            max_per_minute=max_per_minute,
            max_per_hour=max_per_hour,
            max_per_day=max_per_day,
        )
        self._rate_configs[category] = config
        self._rate_limiters[category] = {
            "minute": _SlidingWindowCounter(max_per_minute, 60),
            "hour": _SlidingWindowCounter(max_per_hour, 3600),
            "day": _SlidingWindowCounter(max_per_day, 86400),
        }
        logger.info("EconomicGuardrails: rate limit set for '%s': %d/min, %d/hr, %d/day.",
                    category, max_per_minute, max_per_hour, max_per_day)

    def _check_rate_limit(self, category: str) -> dict[str, Any]:
        """Check if an operation is within rate limits."""
        limiters = self._rate_limiters.get(category)
        if limiters is None:
            # Create default rate limiter
            self.set_rate_limit(category, max_per_minute=self._default_rate_limit)
            limiters = self._rate_limiters[category]

        for window_name, limiter in limiters.items():
            if not limiter.allow():
                return {
                    "allowed": False,
                    "reason": f"Rate limit exceeded: {category} ({window_name}: {limiter.max_count}/{limiter.window_seconds}s)",
                    "window": window_name,
                    "limit": limiter.max_count,
                }

        return {"allowed": True}

    # ── 2. Cost Constraints ───────────────────────────────────────────────

    def _check_budget(self, estimated_cost: float = 0.0) -> dict[str, Any]:
        """Check if spending is within budget."""
        if self.monthly_budget_usd <= 0:
            return {"allowed": True}

        # Check total spend
        total = self._total_cost_usd
        if self._finops is not None:
            try:
                fin_status = self._finops.status()
                total = fin_status.get("used_usd", total)
            except Exception:
                pass

        if total + estimated_cost > self.monthly_budget_usd:
            return {
                "allowed": False,
                "reason": f"Budget exceeded: ${total:.4f} + ${estimated_cost:.4f} > ${self.monthly_budget_usd:.2f}",
                "spent": total,
                "budget": self.monthly_budget_usd,
            }

        return {"allowed": True, "remaining": self.monthly_budget_usd - total}

    # ── 3. Resource Caps ──────────────────────────────────────────────────

    def _check_concurrent(self, category: str) -> dict[str, Any]:
        """Check concurrent operation limits."""
        quota_key = (self.agent_name, category)
        quota = self._quotas.get(quota_key)
        if quota is None or quota.max_concurrent <= 0:
            return {"allowed": True}

        current = self._concurrent.get(category, 0)
        if current >= quota.max_concurrent:
            return {
                "allowed": False,
                "reason": f"Concurrent limit exceeded: {category} ({current}/{quota.max_concurrent})",
                "current": current,
                "limit": quota.max_concurrent,
            }

        return {"allowed": True}

    # ── 4. Quotas ────────────────────────────────────────────────────────

    def set_quota(
        self,
        agent_name: str,
        category: str,
        daily_limit: int = 0,
        hourly_limit: int = 0,
        max_cost_per_action: float = 0.0,
        max_concurrent: int = 0,
    ) -> None:
        """Set quota for a specific agent + category combination."""
        self._quotas[(agent_name, category)] = QuotaConfig(
            agent_name=agent_name,
            category=category,
            daily_limit=daily_limit,
            hourly_limit=hourly_limit,
            max_cost_per_action=max_cost_per_action,
            max_concurrent=max_concurrent,
        )
        logger.info("EconomicGuardrails: quota set for %s/%s: daily=%d, hourly=%d.",
                    agent_name, category, daily_limit, hourly_limit)

    def _check_quota(self, agent_name: str, category: str) -> dict[str, Any]:
        """Check if an operation is within quota."""
        quota = self._quotas.get((agent_name, category))
        if quota is None:
            return {"allowed": True}

        now = time.time()

        # Hourly quota
        if quota.hourly_limit > 0:
            hour_key = f"{agent_name}:{category}:hour"
            hour_reset = self._counter_resets.get(hour_key, 0)
            if now - hour_reset > 3600:
                self._counters[hour_key] = 0
                self._counter_resets[hour_key] = now
            if self._counters[hour_key] >= quota.hourly_limit:
                return {
                    "allowed": False,
                    "reason": f"Hourly quota exceeded: {agent_name}/{category} ({self._counters[hour_key]}/{quota.hourly_limit})",
                }

        # Daily quota
        if quota.daily_limit > 0:
            day_key = f"{agent_name}:{category}:day"
            day_reset = self._counter_resets.get(day_key, 0)
            if now - day_reset > 86400:
                self._counters[day_key] = 0
                self._counter_resets[day_key] = now
            if self._counters[day_key] >= quota.daily_limit:
                return {
                    "allowed": False,
                    "reason": f"Daily quota exceeded: {agent_name}/{category} ({self._counters[day_key]}/{quota.daily_limit})",
                }

        return {"allowed": True}

    # ── 5. Action Caps ───────────────────────────────────────────────────

    def set_action_cap(
        self,
        agent_name: str,
        session_cap: int = 0,
        hourly_cap: int = 0,
        daily_cap: int = 0,
    ) -> None:
        """Set hard action-count caps for an agent.

        Parameters
        ----------
        session_cap : Max total external actions per session (cleared on reset()).
        hourly_cap  : Max external actions per rolling 60-minute window.
        daily_cap   : Max external actions per rolling 24-hour window.
        """
        self._action_caps[agent_name] = ActionCapConfig(
            agent_name=agent_name,
            session_cap=session_cap,
            hourly_cap=hourly_cap,
            daily_cap=daily_cap,
        )
        logger.info(
            "EconomicGuardrails: action cap set for '%s': session=%d, hourly=%d, daily=%d.",
            agent_name, session_cap, hourly_cap, daily_cap,
        )

    def _check_action_cap(self, agent_name: str) -> dict[str, Any]:
        """Check if this agent has exceeded any action-count cap."""
        cap = self._action_caps.get(agent_name)
        if cap is None:
            return {"allowed": True}

        now = time.time()

        # Session cap
        if cap.session_cap > 0:
            used = self._session_action_counts[agent_name]
            if used >= cap.session_cap:
                return {
                    "allowed": False,
                    "reason": (
                        f"Session action cap reached for '{agent_name}': "
                        f"{used}/{cap.session_cap} actions this session."
                    ),
                    "cap_type": "session",
                    "used": used,
                    "limit": cap.session_cap,
                }

        windows = {}
        if cap.hourly_cap > 0:
            windows["hour"] = (cap.hourly_cap, 3600.0)
        if cap.daily_cap > 0:
            windows["day"] = (cap.daily_cap, 86400.0)

        acounts = self._action_counts[agent_name]
        aresets = self._action_resets[agent_name]

        for window_name, (limit, window_secs) in windows.items():
            reset_ts = aresets.get(window_name, 0.0)
            if now - reset_ts > window_secs:
                acounts[window_name] = 0
                aresets[window_name] = now
            used = acounts[window_name]
            if used >= limit:
                return {
                    "allowed": False,
                    "reason": (
                        f"{window_name.capitalize()} action cap reached for '{agent_name}': "
                        f"{used}/{limit} actions."
                    ),
                    "cap_type": window_name,
                    "used": used,
                    "limit": limit,
                }

        return {"allowed": True}

    def _record_action(self, agent_name: str) -> None:
        """Increment all action counters after a successful action."""
        now = time.time()
        cap = self._action_caps.get(agent_name)
        self._session_action_counts[agent_name] += 1

        if cap is None:
            return

        acounts = self._action_counts[agent_name]
        aresets = self._action_resets[agent_name]

        for window_name, window_secs in (("hour", 3600.0), ("day", 86400.0)):
            reset_ts = aresets.get(window_name, 0.0)
            if now - reset_ts > window_secs:
                acounts[window_name] = 0
                aresets[window_name] = now
            acounts[window_name] += 1

    def action_cap_status(self, agent_name: str) -> dict[str, Any]:
        """Return current action-count usage for an agent."""
        cap = self._action_caps.get(agent_name)
        now = time.time()
        acounts = self._action_counts[agent_name]
        aresets = self._action_resets[agent_name]

        def _count(window_name: str, secs: float) -> int:
            reset_ts = aresets.get(window_name, 0.0)
            if now - reset_ts > secs:
                return 0
            return acounts.get(window_name, 0)

        return {
            "agent": agent_name,
            "session": {
                "used": self._session_action_counts.get(agent_name, 0),
                "limit": cap.session_cap if cap else 0,
            },
            "hour": {
                "used": _count("hour", 3600.0),
                "limit": cap.hourly_cap if cap else 0,
            },
            "day": {
                "used": _count("day", 86400.0),
                "limit": cap.daily_cap if cap else 0,
            },
        }

    # ── 6. Budget Thresholds & Auto-Throttle ─────────────────────────────

    def budget_threshold_check(self) -> dict[str, Any]:
        """Return the current budget consumption level and any warning.

        Levels:
            OK       — < 50 % consumed
            WARNING  — 50–79 % consumed
            ALERT    — 80–94 % consumed  (auto-throttle to 50 %)
            CRITICAL — ≥ 95 % consumed   (auto-throttle to 10 %)
            EXCEEDED — over 100 %        (all operations blocked)
        """
        if self.monthly_budget_usd <= 0:
            return {"level": "OK", "message": "No budget cap configured.", "throttle": 1.0}

        spent = self._total_cost_usd
        if self._finops is not None:
            try:
                fin_status = self._finops.status()
                spent = float(fin_status.get("used_usd", spent))
            except Exception:
                pass

        pct = spent / self.monthly_budget_usd

        if pct >= 1.0:
            level, msg, throttle = "EXCEEDED", "Monthly budget exhausted; all operations blocked.", 0.0
        elif pct >= _BUDGET_CRITICAL_PCT:
            level, msg, throttle = (
                "CRITICAL",
                f"Budget critical: {pct*100:.1f}% consumed — auto-throttled to 10%.",
                0.10,
            )
        elif pct >= _BUDGET_ALERT_PCT:
            level, msg, throttle = (
                "ALERT",
                f"Budget alert: {pct*100:.1f}% consumed — auto-throttled to 50%.",
                0.50,
            )
        elif pct >= _BUDGET_WARN_PCT:
            level, msg, throttle = (
                "WARNING",
                f"Budget warning: {pct*100:.1f}% consumed.",
                1.0,
            )
        else:
            level, msg, throttle = "OK", f"Budget healthy: {pct*100:.1f}% consumed.", 1.0

        # Apply auto-throttle
        if self._auto_throttle_enabled and throttle < self._throttle_rate:
            self.set_throttle(throttle)

        return {
            "level": level,
            "message": msg,
            "spent_usd": round(spent, 4),
            "budget_usd": self.monthly_budget_usd,
            "percent": round(pct * 100, 2),
            "throttle": throttle,
        }

    # ── Unified Check ────────────────────────────────────────────────────

    def check_quota(
        self,
        agent_name: str = "",
        category: str = "general",
        estimated_cost: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Run ALL economic checks for an operation.

        This is the single entry point for enforcement.
        Returns {"allowed": True/False, "reason": "..."}.

        Checks (in order):
            1. Rate limit (per-category sliding window)
            2. Budget (monthly cap + estimated cost)
            3. Concurrent operations (if quota configured)
            4. Per-agent/category quota (hourly/daily)
            5. Per-action cost limit
            6. Action cap (session/hourly/daily hard ceiling)
        """
        agent = agent_name or self.agent_name

        # 1. Rate limit check
        rate_result = self._check_rate_limit(category)
        if not rate_result["allowed"]:
            logger.warning("EconomicGuardrails: BLOCKED %s/%s — %s",
                          agent, category, rate_result["reason"])
            return rate_result

        # 2. Budget check
        budget_result = self._check_budget(estimated_cost)
        if not budget_result["allowed"]:
            logger.warning("EconomicGuardrails: BLOCKED %s/%s — %s",
                          agent, category, budget_result["reason"])
            return budget_result

        # 3. Concurrent check
        concurrent_result = self._check_concurrent(category)
        if not concurrent_result["allowed"]:
            logger.warning("EconomicGuardrails: BLOCKED %s/%s — %s",
                          agent, category, concurrent_result["reason"])
            return concurrent_result

        # 4. Quota check
        quota_result = self._check_quota(agent, category)
        if not quota_result["allowed"]:
            logger.warning("EconomicGuardrails: BLOCKED %s/%s — %s",
                          agent, category, quota_result["reason"])
            return quota_result

        # 5. Per-action cost check
        quota = self._quotas.get((agent, category))
        if quota and quota.max_cost_per_action > 0 and estimated_cost > quota.max_cost_per_action:
            reason = f"Action cost ${estimated_cost:.4f} exceeds limit ${quota.max_cost_per_action:.4f}"
            logger.warning("EconomicGuardrails: BLOCKED %s/%s — %s", agent, category, reason)
            return {"allowed": False, "reason": reason}

        # 6. Action cap check
        cap_result = self._check_action_cap(agent)
        if not cap_result["allowed"]:
            logger.warning("EconomicGuardrails: BLOCKED %s/%s — %s",
                          agent, category, cap_result["reason"])
            return cap_result

        return {"allowed": True}

    # ── Record Usage ──────────────────────────────────────────────────────

    def record_usage(
        self,
        category: str = "general",
        agent_name: str = "",
        cost_usd: float = 0.0,
        tokens: int = 0,
    ) -> None:
        """Record resource usage after an operation completes."""
        agent = agent_name or self.agent_name

        record = UsageRecord(
            category=category,
            agent_name=agent,
            cost_usd=cost_usd,
            tokens=tokens,
        )
        self._usage.append(record)
        if len(self._usage) > self._max_usage:
            self._usage = self._usage[-self._max_usage:]

        with self._lock:
            self._total_cost_usd += cost_usd
            self._total_tokens += tokens

        # Update quota counters
        hour_key = f"{agent}:{category}:hour"
        day_key = f"{agent}:{category}:day"
        self._counters[hour_key] = self._counters.get(hour_key, 0) + 1
        self._counters[day_key] = self._counters.get(day_key, 0) + 1

        # Ensure reset timestamps exist
        now = time.time()
        if hour_key not in self._counter_resets:
            self._counter_resets[hour_key] = now
        if day_key not in self._counter_resets:
            self._counter_resets[day_key] = now

        # Increment action cap counters
        self._record_action(agent)

        # Re-evaluate budget thresholds to trigger auto-throttle if needed
        if self._auto_throttle_enabled and self.monthly_budget_usd > 0:
            self.budget_threshold_check()

    def enter_operation(self, category: str) -> None:
        """Mark the start of a concurrent operation."""
        with self._lock:
            self._concurrent[category] = self._concurrent.get(category, 0) + 1

    def exit_operation(self, category: str) -> None:
        """Mark the end of a concurrent operation."""
        with self._lock:
            self._concurrent[category] = max(0, self._concurrent.get(category, 0) - 1)

    # ── Status & Reporting ───────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return full economic guardrails status."""
        budget_info = self.budget_threshold_check() if self.monthly_budget_usd > 0 else {}
        return {
            "agent": self.agent_name,
            "total_cost_usd": round(self._total_cost_usd, 4),
            "total_tokens": self._total_tokens,
            "monthly_budget_usd": self.monthly_budget_usd,
            "budget_remaining_usd": round(
                max(0, self.monthly_budget_usd - self._total_cost_usd), 4
            ) if self.monthly_budget_usd > 0 else None,
            "budget_level": budget_info.get("level", "OK"),
            "budget_percent": budget_info.get("percent", 0.0),
            "throttle_rate": self.throttle_rate,
            "auto_throttle_enabled": self._auto_throttle_enabled,
            "rate_limits": {k: v.to_dict() for k, v in self._rate_configs.items()},
            "quotas": {
                f"{k[0]}/{k[1]}": v.to_dict()
                for k, v in self._quotas.items()
            },
            "action_caps": {k: v.to_dict() for k, v in self._action_caps.items()},
            "concurrent": dict(self._concurrent),
            "usage_records": len(self._usage),
        }

    def usage_summary(self, hours: float = 24) -> dict[str, Any]:
        """Summarize usage over a time window."""
        cutoff = time.time() - (hours * 3600)
        recent = [u for u in self._usage if u.timestamp > cutoff]

        by_category: dict[str, dict[str, Any]] = {}
        for u in recent:
            if u.category not in by_category:
                by_category[u.category] = {"count": 0, "cost_usd": 0.0, "tokens": 0}
            by_category[u.category]["count"] += 1
            by_category[u.category]["cost_usd"] += u.cost_usd
            by_category[u.category]["tokens"] += u.tokens

        for v in by_category.values():
            v["cost_usd"] = round(v["cost_usd"], 4)

        return {
            "hours": hours,
            "total_operations": len(recent),
            "total_cost_usd": round(sum(u.cost_usd for u in recent), 4),
            "total_tokens": sum(u.tokens for u in recent),
            "by_category": by_category,
        }

    def rate_limit_status(self, category: str) -> dict[str, Any]:
        """Return current rate limit status for a category."""
        limiters = self._rate_limiters.get(category)
        if limiters is None:
            return {"category": category, "status": "no_limit"}

        return {
            "category": category,
            "minute": {
                "used": limiters["minute"].current_count(),
                "limit": limiters["minute"].max_count,
                "remaining": limiters["minute"].remaining,
            },
            "hour": {
                "used": limiters["hour"].current_count(),
                "limit": limiters["hour"].max_count,
                "remaining": limiters["hour"].remaining,
            },
            "day": {
                "used": limiters["day"].current_count(),
                "limit": limiters["day"].max_count,
                "remaining": limiters["day"].remaining,
            },
        }

    def reset(self) -> None:
        """Reset all counters and usage (e.g. monthly rollover or new session)."""
        with self._lock:
            self._total_cost_usd = 0.0
            self._total_tokens = 0
            self._usage.clear()
            self._counters.clear()
            self._counter_resets.clear()
            self._concurrent.clear()
            # Reset action cap counters
            self._session_action_counts.clear()
            self._action_counts.clear()
            self._action_resets.clear()
            # Reset throttle
            self._throttle_rate = 1.0
            # Recreate rate limiters with same configs
            for cat, config in self._rate_configs.items():
                self._rate_limiters[cat] = {
                    "minute": _SlidingWindowCounter(config.max_per_minute, 60),
                    "hour": _SlidingWindowCounter(config.max_per_hour, 3600),
                    "day": _SlidingWindowCounter(config.max_per_day, 86400),
                }
        logger.info("EconomicGuardrails: all counters reset.")

    def __repr__(self) -> str:
        return (
            f"EconomicGuardrails(agent={self.agent_name!r}, "
            f"budget=${self.monthly_budget_usd:.2f}, "
            f"cost=${self._total_cost_usd:.4f}, "
            f"throttle={self.throttle_rate:.0%})"
        )

    # ── Throttle Control ─────────────────────────────────────────────────

    def set_throttle(self, rate: float) -> None:
        """
        Throttle all operations to a fraction of normal rate.

        Parameters
        ----------
        rate : 0.0 (fully blocked) to 1.0 (no throttle).
               0.25 means only 25% of normal rate limits apply.
        """
        rate = max(0.0, min(1.0, rate))
        with self._lock:
            self._throttle_rate = rate
            # Apply to all rate limiters
            for cat, config in self._rate_configs.items():
                self._rate_limiters[cat] = {
                    "minute": _SlidingWindowCounter(
                        max(1, int(config.max_per_minute * rate)), 60
                    ),
                    "hour": _SlidingWindowCounter(
                        max(1, int(config.max_per_hour * rate)), 3600
                    ),
                    "day": _SlidingWindowCounter(
                        max(1, int(config.max_per_day * rate)), 86400
                    ),
                }
        logger.info("EconomicGuardrails: throttled to %.0f%%.", rate * 100)

    @property
    def throttle_rate(self) -> float:
        return getattr(self, "_throttle_rate", 1.0)

    # ── Per-Operation Cost Tracking ──────────────────────────────────────

    def cost_by_category(self, hours: float = 24) -> dict[str, float]:
        """Return cost breakdown by category over a time window."""
        cutoff = time.time() - (hours * 3600)
        costs: dict[str, float] = defaultdict(float)
        for u in self._usage:
            if u.timestamp > cutoff:
                costs[u.category] += u.cost_usd
        return {k: round(v, 4) for k, v in costs.items()}

    def cost_by_agent(self, hours: float = 24) -> dict[str, float]:
        """Return cost breakdown by agent over a time window."""
        cutoff = time.time() - (hours * 3600)
        costs: dict[str, float] = defaultdict(float)
        for u in self._usage:
            if u.timestamp > cutoff:
                costs[u.agent_name] += u.cost_usd
        return {k: round(v, 4) for k, v in costs.items()}

    def top_cost_operations(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most expensive individual operations."""
        sorted_ops = sorted(self._usage, key=lambda u: u.cost_usd, reverse=True)
        return [
            {
                "category": u.category,
                "agent": u.agent_name,
                "cost_usd": round(u.cost_usd, 4),
                "tokens": u.tokens,
                "ts": u.timestamp,
            }
            for u in sorted_ops[:limit]
        ]
