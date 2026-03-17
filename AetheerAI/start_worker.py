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
    scale_interval_seconds: float
    scale_down_cooldown_seconds: float
    pop_timeout: int
    idle_sleep: float
    max_concurrency: int
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
        scale_interval_seconds=max(0.5, float(args.scale_interval_seconds)),
        scale_down_cooldown_seconds=max(1.0, float(args.scale_down_cooldown_seconds)),
        pop_timeout=max(1, int(args.pop_timeout)),
        idle_sleep=max(0.05, float(args.idle_sleep)),
        max_concurrency=max(1, int(args.max_concurrency)),
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
            "Worker autoscaling enabled: min=%s max=%s target_depth=%s interval=%ss",
            config.min_workers,
            config.max_workers,
            config.target_queue_depth_per_worker,
            config.scale_interval_seconds,
        )
    else:
        logger.info("Worker autoscaling disabled; using fixed workers=%s", config.fixed_workers)

    processes: list[subprocess.Popen[object]] = []
    zero_depth_since: float | None = None
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
                    proposed = _calculate_desired_workers(
                        queue_depth,
                        min_workers=config.min_workers,
                        max_workers=config.max_workers,
                        target_queue_depth_per_worker=config.target_queue_depth_per_worker,
                    )

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

                    desired_count = proposed
                    logger.debug(
                        "Autoscale sample: depth=%s desired=%s active=%s",
                        queue_depth,
                        desired_count,
                        len(processes),
                    )
                else:
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
