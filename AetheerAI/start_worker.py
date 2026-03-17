"""Start and autoscale Upstash queue workers."""
from __future__ import annotations

import argparse
import logging
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Sequence

from core.env_loader import load_env
from integrations.upstash_redis_queue import UpstashRedisQueue
from utils.log_config import setup_logging

logger = logging.getLogger("aetheer.worker.supervisor")


def _env_first(*names: str) -> str:
    for name in names:
        raw = (os.getenv(name) or "").strip()
        if raw:
            return raw
    return ""


def _env_int(*names: str, default: int, minimum: int | None = None) -> int:
    raw = _env_first(*names)
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        return max(minimum, value)
    return value


def _env_float(*names: str, default: float, minimum: float | None = None) -> float:
    raw = _env_first(*names)
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        return max(minimum, value)
    return value


def _env_bool(*names: str, default: bool = False) -> bool:
    raw = _env_first(*names).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _default_max_workers() -> int:
    cpu_count = os.cpu_count() or 1
    return max(1, min(cpu_count, 16))


@dataclass(frozen=True)
class WorkerSupervisorConfig:
    autoscale: bool
    fixed_workers: int
    min_workers: int
    max_workers: int
    target_queue_depth_per_worker: int
    scale_up_step: int
    scale_down_step: int
    queue_depth_ema_alpha: float
    queue_depth_high_watermark: int
    scale_interval_seconds: float
    scale_down_cooldown_seconds: float
    pop_timeout: int
    idle_sleep: float
    max_concurrency: int
    claim_heartbeat_seconds: float
    sandbox_enabled: bool
    sandbox_strict: bool
    job_max_runtime_seconds: int
    job_max_memory_mb: int
    job_max_cpu_seconds: int
    log_level: str


def _calculate_desired_workers(
    queue_depth: int,
    *,
    min_workers: int,
    max_workers: int,
    target_queue_depth_per_worker: int,
) -> int:
    depth = max(0, int(queue_depth))
    if depth == 0:
        desired = min_workers
    else:
        desired = math.ceil(depth / max(1, int(target_queue_depth_per_worker)))
    return max(min_workers, min(max_workers, desired))


def _smooth_queue_depth(previous_depth: float | None, sample_depth: int, *, alpha: float) -> float:
    sample = max(0.0, float(sample_depth))
    if previous_depth is None:
        return sample

    weight = max(0.05, min(1.0, float(alpha)))
    return (sample * weight) + (float(previous_depth) * (1.0 - weight))


def _apply_scale_step_limit(
    current_count: int,
    proposed_count: int,
    *,
    scale_up_step: int,
    scale_down_step: int,
) -> int:
    current = max(0, int(current_count))
    proposed = max(0, int(proposed_count))

    if proposed > current:
        return min(proposed, current + max(1, int(scale_up_step)))
    if proposed < current:
        return max(proposed, current - max(1, int(scale_down_step)))
    return proposed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autoscaling supervisor for Upstash Redis queue workers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--autoscale",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("AETHEER_WORKER_AUTOSCALE", "AETHER_WORKER_AUTOSCALE", default=True),
        help="Enable queue-depth based autoscaling for worker replicas.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=_env_int("AETHEER_WORKER_PROCESSES", "AETHER_WORKER_PROCESSES", default=1, minimum=1),
        help="Fixed number of worker replicas when autoscaling is disabled.",
    )
    parser.add_argument(
        "--min-workers",
        type=int,
        default=_env_int("AETHEER_WORKER_MIN_PROCESSES", "AETHER_WORKER_MIN_PROCESSES", default=1, minimum=1),
        help="Minimum worker replicas when autoscaling is enabled.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=_env_int(
            "AETHEER_WORKER_MAX_PROCESSES",
            "AETHER_WORKER_MAX_PROCESSES",
            default=_default_max_workers(),
            minimum=1,
        ),
        help="Maximum worker replicas when autoscaling is enabled.",
    )
    parser.add_argument(
        "--target-queue-depth-per-worker",
        type=int,
        default=_env_int(
            "AETHEER_WORKER_TARGET_QUEUE_DEPTH_PER_WORKER",
            "AETHER_WORKER_TARGET_QUEUE_DEPTH_PER_WORKER",
            default=4,
            minimum=1,
        ),
        help="Scale target: each worker should handle about this many queued jobs.",
    )
    parser.add_argument(
        "--scale-up-step",
        type=int,
        default=_env_int(
            "AETHEER_WORKER_SCALE_UP_STEP",
            "AETHER_WORKER_SCALE_UP_STEP",
            default=2,
            minimum=1,
        ),
        help="Maximum worker replicas added in a single autoscale cycle.",
    )
    parser.add_argument(
        "--scale-down-step",
        type=int,
        default=_env_int(
            "AETHEER_WORKER_SCALE_DOWN_STEP",
            "AETHER_WORKER_SCALE_DOWN_STEP",
            default=1,
            minimum=1,
        ),
        help="Maximum worker replicas removed in a single autoscale cycle.",
    )
    parser.add_argument(
        "--queue-depth-ema-alpha",
        type=float,
        default=_env_float(
            "AETHEER_WORKER_QUEUE_DEPTH_EMA_ALPHA",
            "AETHER_WORKER_QUEUE_DEPTH_EMA_ALPHA",
            default=0.4,
            minimum=0.05,
        ),
        help="Smoothing factor (0..1] for queue depth EMA used by autoscaling.",
    )
    parser.add_argument(
        "--queue-depth-high-watermark",
        type=int,
        default=_env_int(
            "AETHEER_WORKER_QUEUE_DEPTH_HIGH_WATERMARK",
            "AETHER_WORKER_QUEUE_DEPTH_HIGH_WATERMARK",
            default=0,
            minimum=0,
        ),
        help="Immediate surge threshold; when queue depth reaches this value, scale to max workers (0 disables).",
    )
    parser.add_argument(
        "--scale-interval-seconds",
        type=float,
        default=_env_float(
            "AETHEER_WORKER_SCALE_INTERVAL_SECONDS",
            "AETHER_WORKER_SCALE_INTERVAL_SECONDS",
            default=5.0,
            minimum=0.5,
        ),
        help="How often the supervisor recomputes desired worker count.",
    )
    parser.add_argument(
        "--scale-down-cooldown-seconds",
        type=float,
        default=_env_float(
            "AETHEER_WORKER_SCALE_DOWN_COOLDOWN_SECONDS",
            "AETHER_WORKER_SCALE_DOWN_COOLDOWN_SECONDS",
            default=45.0,
            minimum=1.0,
        ),
        help="Queue-empty cooldown before shrinking worker count.",
    )

    # Pass-through worker process flags.
    parser.add_argument(
        "--pop-timeout",
        type=int,
        default=_env_int("UPSTASH_REDIS_POP_TIMEOUT_SECONDS", default=30, minimum=1),
        help="BRPOP timeout in seconds for each worker process.",
    )
    parser.add_argument(
        "--idle-sleep",
        type=float,
        default=_env_float("AETHEER_WORKER_IDLE_SLEEP_SECONDS", "AETHER_WORKER_IDLE_SLEEP_SECONDS", default=0.25, minimum=0.05),
        help="Worker idle sleep interval when no jobs are popped.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=_env_int("AETHEER_WORKER_MAX_CONCURRENCY", "AETHER_WORKER_MAX_CONCURRENCY", default=1, minimum=1),
        help="Thread concurrency per worker process.",
    )
    parser.add_argument(
        "--claim-heartbeat-seconds",
        type=float,
        default=_env_float("AETHEER_JOB_CLAIM_HEARTBEAT_SECONDS", default=30.0, minimum=5.0),
        help="Execution-claim heartbeat interval forwarded to each worker process.",
    )
    parser.add_argument(
        "--sandbox-enabled",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("AETHEER_JOB_SANDBOX_ENABLED", default=True),
        help="Run each queue job in an isolated subprocess sandbox.",
    )
    parser.add_argument(
        "--sandbox-strict",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("AETHEER_JOB_SANDBOX_STRICT", default=True),
        help="Fail jobs when hard CPU/memory limits cannot be enforced.",
    )
    parser.add_argument(
        "--job-max-runtime-seconds",
        type=int,
        default=_env_int("AETHEER_JOB_MAX_RUNTIME_SECONDS", default=600, minimum=1),
        help="Hard runtime cap for each job subprocess.",
    )
    parser.add_argument(
        "--job-max-memory-mb",
        type=int,
        default=_env_int("AETHEER_JOB_MAX_MEMORY_MB", default=1024, minimum=0),
        help="Hard memory cap in MB per job subprocess (0 disables).",
    )
    parser.add_argument(
        "--job-max-cpu-seconds",
        type=int,
        default=_env_int("AETHEER_JOB_MAX_CPU_SECONDS", default=300, minimum=0),
        help="Hard CPU-time cap in seconds per job subprocess (0 disables).",
    )
    parser.add_argument(
        "--log-level",
        default=(os.getenv("LOG_LEVEL") or "INFO"),
        help="Log level for supervisor and spawned worker processes.",
    )

    return parser.parse_args(argv)


def _build_config(args: argparse.Namespace) -> WorkerSupervisorConfig:
    fixed_workers = max(1, int(args.workers))
    min_workers = max(1, int(args.min_workers))
    max_workers = max(min_workers, int(args.max_workers))

    return WorkerSupervisorConfig(
        autoscale=bool(args.autoscale),
        fixed_workers=fixed_workers,
        min_workers=min_workers,
        max_workers=max_workers,
        target_queue_depth_per_worker=max(1, int(args.target_queue_depth_per_worker)),
        scale_up_step=max(1, int(args.scale_up_step)),
        scale_down_step=max(1, int(args.scale_down_step)),
        queue_depth_ema_alpha=max(0.05, min(1.0, float(args.queue_depth_ema_alpha))),
        queue_depth_high_watermark=max(0, int(args.queue_depth_high_watermark)),
        scale_interval_seconds=max(0.5, float(args.scale_interval_seconds)),
        scale_down_cooldown_seconds=max(1.0, float(args.scale_down_cooldown_seconds)),
        pop_timeout=max(1, int(args.pop_timeout)),
        idle_sleep=max(0.05, float(args.idle_sleep)),
        max_concurrency=max(1, int(args.max_concurrency)),
        claim_heartbeat_seconds=max(5.0, float(args.claim_heartbeat_seconds)),
        sandbox_enabled=bool(args.sandbox_enabled),
        sandbox_strict=bool(args.sandbox_strict),
        job_max_runtime_seconds=max(1, int(args.job_max_runtime_seconds)),
        job_max_memory_mb=max(0, int(args.job_max_memory_mb)),
        job_max_cpu_seconds=max(0, int(args.job_max_cpu_seconds)),
        log_level=str(args.log_level or "INFO").upper(),
    )


def _build_worker_command(config: WorkerSupervisorConfig) -> list[str]:
    root = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(root, "workers", "upstash_job_worker.py")
    return [
        sys.executable,
        script_path,
        "--pop-timeout",
        str(config.pop_timeout),
        "--idle-sleep",
        str(config.idle_sleep),
        "--max-concurrency",
        str(config.max_concurrency),
        "--claim-heartbeat-seconds",
        str(config.claim_heartbeat_seconds),
        "--sandbox-enabled" if config.sandbox_enabled else "--no-sandbox-enabled",
        "--sandbox-strict" if config.sandbox_strict else "--no-sandbox-strict",
        "--job-max-runtime-seconds",
        str(config.job_max_runtime_seconds),
        "--job-max-memory-mb",
        str(config.job_max_memory_mb),
        "--job-max-cpu-seconds",
        str(config.job_max_cpu_seconds),
        "--log-level",
        config.log_level,
    ]


def _reap_workers(processes: list[subprocess.Popen[object]]) -> list[subprocess.Popen[object]]:
    alive: list[subprocess.Popen[object]] = []
    for process in processes:
        code = process.poll()
        if code is None:
            alive.append(process)
        else:
            logger.warning("Worker exited pid=%s code=%s", process.pid, code)
    return alive


def _stop_process(process: subprocess.Popen[object], *, timeout: float = 10.0) -> None:
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _scale_workers(
    processes: list[subprocess.Popen[object]],
    *,
    desired_count: int,
    worker_command: Sequence[str],
    worker_cwd: str,
) -> list[subprocess.Popen[object]]:
    desired_count = max(0, int(desired_count))
    processes = _reap_workers(processes)

    while len(processes) < desired_count:
        process = subprocess.Popen(list(worker_command), cwd=worker_cwd)
        processes.append(process)
        logger.info("Launched worker pid=%s (%s/%s)", process.pid, len(processes), desired_count)

    if len(processes) > desired_count:
        to_stop = processes[desired_count:]
        processes = processes[:desired_count]
        for process in to_stop:
            logger.info("Stopping worker pid=%s for scale-down", process.pid)
            _stop_process(process)

    return processes


def run_supervisor(config: WorkerSupervisorConfig) -> None:
    worker_cwd = os.path.dirname(os.path.abspath(__file__))
    worker_command = _build_worker_command(config)

    autoscale_enabled = bool(config.autoscale)
    queue_monitor: UpstashRedisQueue | None = None
    if autoscale_enabled:
        try:
            queue_monitor = UpstashRedisQueue()
        except Exception as exc:
            autoscale_enabled = False
            logger.warning("Autoscaling disabled because queue monitor failed to initialize: %s", exc)

    if autoscale_enabled:
        logger.info(
            (
                "Worker autoscaling enabled: min=%s max=%s target_depth=%s "
                "scale_step(+%s/-%s) ema_alpha=%.2f high_watermark=%s interval=%ss"
            ),
            config.min_workers,
            config.max_workers,
            config.target_queue_depth_per_worker,
            config.scale_up_step,
            config.scale_down_step,
            config.queue_depth_ema_alpha,
            config.queue_depth_high_watermark,
            config.scale_interval_seconds,
        )
    else:
        logger.info("Worker autoscaling disabled; using fixed workers=%s", config.fixed_workers)

    processes: list[subprocess.Popen[object]] = []
    zero_depth_since: float | None = None
    smoothed_depth: float | None = None
    desired_count = config.min_workers if autoscale_enabled else config.fixed_workers

    try:
        while True:
            processes = _reap_workers(processes)

            if autoscale_enabled and queue_monitor is not None:
                queue_depth: int | None = None
                try:
                    queue_names = tuple(
                        str(name)
                        for name in getattr(queue_monitor, "priority_queue_names", (queue_monitor.queue_name,))
                        if str(name).strip()
                    )
                    if not queue_names:
                        queue_names = (str(getattr(queue_monitor, "queue_name", "job_queue")),)
                    queue_depth = max(0, int(queue_monitor.queue_depth_many(queue_names=queue_names)))
                except Exception as exc:
                    logger.warning("Queue depth probe failed; holding worker count steady: %s", exc)

                if queue_depth is not None:
                    smoothed_depth = _smooth_queue_depth(
                        smoothed_depth,
                        queue_depth,
                        alpha=config.queue_depth_ema_alpha,
                    )
                    depth_for_decision = max(queue_depth, int(math.ceil(smoothed_depth)))

                    proposed = _calculate_desired_workers(
                        depth_for_decision,
                        min_workers=config.min_workers,
                        max_workers=config.max_workers,
                        target_queue_depth_per_worker=config.target_queue_depth_per_worker,
                    )

                    if (
                        config.queue_depth_high_watermark > 0
                        and queue_depth >= config.queue_depth_high_watermark
                    ):
                        proposed = config.max_workers

                    # Scale down only after sustained empty queue to avoid worker churn.
                    if proposed < len(processes):
                        if queue_depth == 0:
                            if zero_depth_since is None:
                                zero_depth_since = time.monotonic()
                            idle_seconds = time.monotonic() - zero_depth_since
                            if idle_seconds < config.scale_down_cooldown_seconds:
                                proposed = len(processes)
                        else:
                            zero_depth_since = None
                            proposed = len(processes)
                    else:
                        zero_depth_since = None

                    proposed = _apply_scale_step_limit(
                        len(processes),
                        proposed,
                        scale_up_step=config.scale_up_step,
                        scale_down_step=config.scale_down_step,
                    )

                    desired_count = proposed
                    logger.debug(
                        "Autoscale sample: depth=%s ema=%.2f desired=%s active=%s",
                        queue_depth,
                        smoothed_depth,
                        desired_count,
                        len(processes),
                    )
                else:
                    smoothed_depth = None
                    desired_count = max(config.min_workers, len(processes))
            else:
                desired_count = config.fixed_workers

            processes = _scale_workers(
                processes,
                desired_count=desired_count,
                worker_command=worker_command,
                worker_cwd=worker_cwd,
            )

            time.sleep(config.scale_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Worker supervisor interrupted. Shutting down all worker processes.")
    finally:
        for process in processes:
            _stop_process(process)
        logger.info("Worker supervisor stopped.")


def main(argv: Sequence[str] | None = None) -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    load_env(os.path.join(root, ".env"))

    args = _parse_args(argv)
    config = _build_config(args)
    setup_logging(level=config.log_level)
    run_supervisor(config)


if __name__ == "__main__":
    main()
