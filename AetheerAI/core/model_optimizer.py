"""
model_optimizer.py — Model Performance Tracking, Persistence & Auto-Tuning.

Adds three missing capabilities on top of ModelRouter:

  1. Performance Tracking  — records latency and success/failure for every
                             model call, building a real-world performance
                             profile per (provider, model) pair.

  2. Model Persistence     — serialises the accumulated stats to a .pkl
                             checkpoint (fast binary, survives restarts).
                             A human-readable .json sidecar can be exported
                             separately for inspection or dashboards.
                             .h5 export is available when h5py is installed
                             (stores the same data in HDF5 format).

  3. Adaptive Tuning       — computes a composite score from latency and
                             success rate, then re-orders each complexity
                             tier in the routing table so the best-performing
                             models are tried first.  Poorly-performing models
                             are soft-demoted (moved toward the bottom of the
                             tier) rather than hard-removed, so they can
                             recover if conditions change.

Minimal integration
-------------------
    from core.model_optimizer import ModelOptimizer
    from core.model_router   import ModelRouter

    optimizer = ModelOptimizer.load_or_create()      # restore disk state if present
    router    = ModelRouter(ai_adapter)

    # After each AI call, record the outcome:
    optimizer.record("openai", "gpt-4o", latency_ms=430.0, success=True)

    # Periodically or on clean shutdown — persist:
    optimizer.save()

    # Re-rank the routing table with live performance data:
    router._routing_table = optimizer.tune(router._routing_table)
"""

from __future__ import annotations

import json
import logging
import pickle
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default checkpoint location — sits beside this source file (or next to the
# .exe when frozen by PyInstaller).
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    """Return a writable directory for persistent data files."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "aetheerai_data"
    return Path(__file__).parent.parent / "memory"


_DEFAULT_PKL  = _data_dir() / "model_optimizer.pkl"
_DEFAULT_JSON = _data_dir() / "model_optimizer_report.json"

# ---------------------------------------------------------------------------
# How we score a model.  Higher is better.
#
#   composite = success_rate * WEIGHT_SUCCESS
#             + (1 - clamped_latency_ratio) * WEIGHT_LATENCY
#
# where clamped_latency_ratio = min(avg_latency_ms / MAX_LATENCY_MS, 1.0)
# ---------------------------------------------------------------------------

WEIGHT_SUCCESS: float = 0.65      # success rate matters more than raw speed
WEIGHT_LATENCY: float = 0.35
MAX_LATENCY_MS: float = 10_000.0  # latency ceiling for normalisation (10 s)
MIN_CALLS_TO_TUNE: int = 3        # ignore a model until we have ≥ N calls


# ---------------------------------------------------------------------------
# Per-model stat accumulator
# ---------------------------------------------------------------------------

@dataclass
class ModelStats:
    """Rolling performance statistics for a single (provider, model) pair."""

    provider: str
    model: str
    total_calls: int = 0
    success_calls: int = 0
    total_latency_ms: float = 0.0
    # peak / min latency for reporting
    peak_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    last_updated: float = field(default_factory=time.time)

    # ------------------------------------------------------------------ #
    # Mutation helpers                                                     #
    # ------------------------------------------------------------------ #

    def record(self, latency_ms: float, success: bool) -> None:
        self.total_calls += 1
        if success:
            self.success_calls += 1
        self.total_latency_ms += latency_ms
        if latency_ms > self.peak_latency_ms:
            self.peak_latency_ms = latency_ms
        if latency_ms < self.min_latency_ms:
            self.min_latency_ms = latency_ms
        self.last_updated = time.time()

    # ------------------------------------------------------------------ #
    # Derived metrics                                                      #
    # ------------------------------------------------------------------ #

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0  # no data → assume optimistic
        return self.success_calls / self.total_calls

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_ms / self.total_calls

    @property
    def composite_score(self) -> float:
        """
        Composite performance score in [0, 1].  Higher is better.
        Only meaningful when total_calls >= MIN_CALLS_TO_TUNE.
        """
        lat_ratio = min(self.avg_latency_ms / MAX_LATENCY_MS, 1.0)
        return (
            self.success_rate * WEIGHT_SUCCESS
            + (1.0 - lat_ratio) * WEIGHT_LATENCY
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "total_calls": self.total_calls,
            "success_calls": self.success_calls,
            "success_rate": round(self.success_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "peak_latency_ms": round(self.peak_latency_ms, 2),
            "min_latency_ms": (
                round(self.min_latency_ms, 2)
                if self.min_latency_ms != float("inf")
                else None
            ),
            "composite_score": round(self.composite_score, 4),
            "last_updated": self.last_updated,
        }


# ---------------------------------------------------------------------------
# Main optimizer class
# ---------------------------------------------------------------------------

class ModelOptimizer:
    """
    Tracks model performance, persists state to disk (.pkl / .json / .h5),
    and adaptively re-orders the ModelRouter routing table.

    Parameters
    ----------
    pkl_path  : Path to the pickle checkpoint file.
    json_path : Path for the human-readable JSON report export.
    """

    def __init__(
        self,
        pkl_path: Path | str = _DEFAULT_PKL,
        json_path: Path | str = _DEFAULT_JSON,
    ) -> None:
        self._pkl_path  = Path(pkl_path)
        self._json_path = Path(json_path)
        # keyed by "(provider, model)"
        self._stats: dict[str, ModelStats] = {}

    # ------------------------------------------------------------------ #
    # Class-level factory                                                  #
    # ------------------------------------------------------------------ #

    @classmethod
    def load_or_create(
        cls,
        pkl_path: Path | str = _DEFAULT_PKL,
        json_path: Path | str = _DEFAULT_JSON,
    ) -> "ModelOptimizer":
        """
        Load an existing .pkl checkpoint if present, otherwise create a fresh
        instance.  This is the recommended entry point.

            optimizer = ModelOptimizer.load_or_create()
        """
        instance = cls(pkl_path=pkl_path, json_path=json_path)
        try:
            instance.load()
        except FileNotFoundError:
            logger.info(
                "ModelOptimizer: no checkpoint at '%s' — starting fresh.",
                pkl_path,
            )
        return instance

    # ------------------------------------------------------------------ #
    # Performance recording                                                #
    # ------------------------------------------------------------------ #

    def record(
        self,
        provider: str,
        model: str,
        latency_ms: float,
        success: bool,
    ) -> ModelStats:
        """
        Record one model call outcome.

        Parameters
        ----------
        provider   : Provider name, e.g. "openai", "ollama".
        model      : Model name, e.g. "gpt-4o".
        latency_ms : Wall-clock latency of the call in milliseconds.
        success    : True if the call returned a usable result.

        Returns the updated ModelStats for that (provider, model) pair.
        """
        if latency_ms < 0:
            raise ValueError("latency_ms must be non-negative.")

        key = _key(provider, model)
        if key not in self._stats:
            self._stats[key] = ModelStats(provider=provider, model=model)
        stats = self._stats[key]
        stats.record(latency_ms=latency_ms, success=success)

        logger.debug(
            "ModelOptimizer.record: %s/%s  latency=%.1fms  success=%s  "
            "score=%.3f  calls=%d",
            provider, model, latency_ms, success,
            stats.composite_score, stats.total_calls,
        )
        return stats

    # ------------------------------------------------------------------ #
    # Context-manager helper for timing a live call                       #
    # ------------------------------------------------------------------ #

    def timed_record(self, provider: str, model: str):
        """
        Context manager that automatically measures latency and records the
        outcome.  Mark success/failure via the yielded ``ctx`` object.

        Usage::

            with optimizer.timed_record("openai", "gpt-4o") as ctx:
                result = adapter.chat(messages)
                ctx.success = not result.startswith("Error")
        """
        return _TimedRecord(self, provider, model)

    # ------------------------------------------------------------------ #
    # Persistence — .pkl (primary)                                        #
    # ------------------------------------------------------------------ #

    def save(self) -> Path:
        """
        Persist performance stats to the .pkl checkpoint file.

        Returns the path written to.
        """
        self._pkl_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "stats": {k: self._stats[k].to_dict() for k in self._stats},
        }
        with open(self._pkl_path, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("ModelOptimizer: saved %d model stat(s) to '%s'.",
                    len(self._stats), self._pkl_path)
        return self._pkl_path

    def load(self) -> None:
        """
        Load performance stats from the .pkl checkpoint.

        Raises
        ------
        FileNotFoundError  — if the checkpoint does not exist yet.
        """
        if not self._pkl_path.exists():
            raise FileNotFoundError(self._pkl_path)

        with open(self._pkl_path, "rb") as f:
            payload = pickle.load(f)  # noqa: S301 — trusted local file

        raw_stats = payload.get("stats", {})
        for key, d in raw_stats.items():
            ms = ModelStats(
                provider=d["provider"],
                model=d["model"],
                total_calls=d.get("total_calls", 0),
                success_calls=d.get("success_calls", 0),
                total_latency_ms=d.get("avg_latency_ms", 0.0) * d.get("total_calls", 0),
                peak_latency_ms=d.get("peak_latency_ms", 0.0),
                min_latency_ms=d.get("min_latency_ms") or float("inf"),
                last_updated=d.get("last_updated", time.time()),
            )
            self._stats[key] = ms

        logger.info(
            "ModelOptimizer: loaded %d model stat(s) from '%s'.",
            len(self._stats), self._pkl_path,
        )

    # ------------------------------------------------------------------ #
    # Persistence — .h5 (optional, requires h5py)                        #
    # ------------------------------------------------------------------ #

    def save_h5(self, path: Path | str | None = None) -> Path:
        """
        Export performance stats to HDF5 format (.h5).

        Requires ``pip install h5py``.  Raises ``ImportError`` if not present.
        Falls back gracefully so the rest of the system is never blocked.
        """
        try:
            import h5py  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "h5py is required for HDF5 export: pip install h5py"
            ) from exc

        h5_path = Path(path) if path else self._pkl_path.with_suffix(".h5")
        h5_path.parent.mkdir(parents=True, exist_ok=True)

        with h5py.File(h5_path, "w") as hf:
            hf.attrs["version"] = 1
            for key, s in self._stats.items():
                grp = hf.create_group(key)
                grp.attrs["provider"]         = s.provider
                grp.attrs["model"]            = s.model
                grp.attrs["total_calls"]      = s.total_calls
                grp.attrs["success_calls"]    = s.success_calls
                grp.attrs["total_latency_ms"] = s.total_latency_ms
                grp.attrs["peak_latency_ms"]  = s.peak_latency_ms
                grp.attrs["min_latency_ms"]   = (
                    s.min_latency_ms if s.min_latency_ms != float("inf") else -1.0
                )
                grp.attrs["last_updated"]     = s.last_updated

        logger.info("ModelOptimizer: exported HDF5 to '%s'.", h5_path)
        return h5_path

    def load_h5(self, path: Path | str | None = None) -> None:
        """Load performance stats previously saved with ``save_h5()``."""
        try:
            import h5py  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "h5py is required for HDF5 loading: pip install h5py"
            ) from exc

        h5_path = Path(path) if path else self._pkl_path.with_suffix(".h5")
        if not h5_path.exists():
            raise FileNotFoundError(h5_path)

        with h5py.File(h5_path, "r") as hf:
            for key in hf.keys():
                grp = hf[key]
                total = int(grp.attrs.get("total_calls", 0))
                ms = ModelStats(
                    provider=str(grp.attrs["provider"]),
                    model=str(grp.attrs["model"]),
                    total_calls=total,
                    success_calls=int(grp.attrs.get("success_calls", 0)),
                    total_latency_ms=float(grp.attrs.get("total_latency_ms", 0.0)),
                    peak_latency_ms=float(grp.attrs.get("peak_latency_ms", 0.0)),
                    min_latency_ms=(
                        float(grp.attrs["min_latency_ms"])
                        if float(grp.attrs.get("min_latency_ms", -1.0)) >= 0
                        else float("inf")
                    ),
                    last_updated=float(grp.attrs.get("last_updated", time.time())),
                )
                self._stats[key] = ms

        logger.info("ModelOptimizer: loaded HDF5 from '%s' (%d entries).",
                    h5_path, len(self._stats))

    # ------------------------------------------------------------------ #
    # JSON report export                                                   #
    # ------------------------------------------------------------------ #

    def export_json(self, path: Path | str | None = None) -> Path:
        """
        Write a human-readable JSON performance report.
        Does not replace the .pkl checkpoint.
        """
        out = Path(path) if path else self._json_path
        out.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "total_models_tracked": len(self._stats),
            "models": [s.to_dict() for s in self._sorted_by_score()],
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        logger.info("ModelOptimizer: JSON report written to '%s'.", out)
        return out

    # ------------------------------------------------------------------ #
    # Adaptive performance tuning                                         #
    # ------------------------------------------------------------------ #

    def tune(
        self,
        routing_table: dict[str, list[tuple[str, str]]],
    ) -> dict[str, list[tuple[str, str]]]:
        """
        Return a re-ordered copy of *routing_table* where models with better
        composite scores are surfaced toward the top of each complexity tier.

        Rules
        -----
        - A model must have at least ``MIN_CALLS_TO_TUNE`` recorded calls
          before its score influences ordering.  Untracked models keep their
          original relative position.
        - The re-ordering is *soft*: it sorts within the tier but never adds
          or removes entries, so the routing table structure stays intact.
        - Calling this repeatedly is safe — it works on a copy and is
          idempotent given the same performance data.

        Parameters
        ----------
        routing_table : The dict from ``ModelRouter._routing_table``.

        Returns a new dict (same structure, potentially new ordering).
        """
        tuned: dict[str, list[tuple[str, str]]] = {}
        for tier, candidates in routing_table.items():
            tuned[tier] = self._sort_candidates(candidates)
        return tuned

    def _sort_candidates(
        self,
        candidates: list[tuple[str, str]],
    ) -> list[tuple[str, str]]:
        """
        Sort a list of (provider, model) tuples by composite score (desc).
        Models with < MIN_CALLS_TO_TUNE entries are ranked below scored ones,
        preserving their original relative order among the unscored group.
        """
        scored:   list[tuple[float, int, tuple[str, str]]] = []
        unscored: list[tuple[int,       tuple[str, str]]] = []

        for idx, pair in enumerate(candidates):
            provider, model = pair
            key = _key(provider, model)
            stats = self._stats.get(key)
            if stats is not None and stats.total_calls >= MIN_CALLS_TO_TUNE:
                scored.append((stats.composite_score, idx, pair))
            else:
                unscored.append((idx, pair))

        # Sort scored models highest-score first; preserve original order on tie
        scored.sort(key=lambda x: (-x[0], x[1]))

        result = [pair for _, _, pair in scored]
        result += [pair for _, pair in unscored]
        return result

    # ------------------------------------------------------------------ #
    # Querying                                                             #
    # ------------------------------------------------------------------ #

    def get_stats(self, provider: str, model: str) -> ModelStats | None:
        """Return the ModelStats for a specific (provider, model), or None."""
        return self._stats.get(_key(provider, model))

    def all_stats(self) -> list[ModelStats]:
        """Return all tracked ModelStats objects, sorted by composite score desc."""
        return self._sorted_by_score()

    def report(self) -> dict[str, Any]:
        """Return a serialisable performance report dict."""
        return {
            "total_models_tracked": len(self._stats),
            "models": [s.to_dict() for s in self._sorted_by_score()],
        }

    def reset(self) -> None:
        """Clear all accumulated stats (in-memory only; does not delete disk files)."""
        self._stats.clear()
        logger.info("ModelOptimizer: in-memory stats cleared.")

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _sorted_by_score(self) -> list[ModelStats]:
        return sorted(
            self._stats.values(),
            key=lambda s: s.composite_score,
            reverse=True,
        )


# ---------------------------------------------------------------------------
# Timed-record context manager
# ---------------------------------------------------------------------------

class _TimedRecord:
    """Internal context manager returned by ``ModelOptimizer.timed_record()``."""

    def __init__(self, optimizer: ModelOptimizer, provider: str, model: str) -> None:
        self._optimizer = optimizer
        self._provider  = provider
        self._model     = model
        self._start: float = 0.0
        self.success: bool = True   # caller flips to False on error

    def __enter__(self) -> "_TimedRecord":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        latency_ms = (time.perf_counter() - self._start) * 1000.0
        if exc_type is not None:
            self.success = False
        self._optimizer.record(
            provider=self._provider,
            model=self._model,
            latency_ms=latency_ms,
            success=self.success,
        )
        return False  # do not suppress exceptions


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _key(provider: str, model: str) -> str:
    return f"{provider}/{model}"
