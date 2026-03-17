"""Tests for autoscaling behavior in start_worker.py."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import start_worker


class StartWorkerSupervisorTests(unittest.TestCase):
    def test_calculate_desired_workers_scales_with_depth(self):
        self.assertEqual(
            start_worker._calculate_desired_workers(
                0,
                min_workers=1,
                max_workers=6,
                target_queue_depth_per_worker=4,
            ),
            1,
        )
        self.assertEqual(
            start_worker._calculate_desired_workers(
                4,
                min_workers=1,
                max_workers=6,
                target_queue_depth_per_worker=4,
            ),
            1,
        )
        self.assertEqual(
            start_worker._calculate_desired_workers(
                5,
                min_workers=1,
                max_workers=6,
                target_queue_depth_per_worker=4,
            ),
            2,
        )
        self.assertEqual(
            start_worker._calculate_desired_workers(
                200,
                min_workers=1,
                max_workers=6,
                target_queue_depth_per_worker=4,
            ),
            6,
        )

    def test_parse_args_reads_autoscale_defaults_from_env(self):
        with patch.dict(
            os.environ,
            {
                "AETHEER_WORKER_AUTOSCALE": "1",
                "AETHEER_WORKER_MIN_PROCESSES": "2",
                "AETHEER_WORKER_MAX_PROCESSES": "5",
                "AETHEER_WORKER_TARGET_QUEUE_DEPTH_PER_WORKER": "3",
                "AETHEER_WORKER_SCALE_INTERVAL_SECONDS": "2.5",
                "AETHEER_WORKER_SCALE_DOWN_COOLDOWN_SECONDS": "12",
                "AETHEER_WORKER_MAX_CONCURRENCY": "4",
            },
            clear=False,
        ):
            args = start_worker._parse_args([])

        self.assertTrue(args.autoscale)
        self.assertEqual(args.min_workers, 2)
        self.assertEqual(args.max_workers, 5)
        self.assertEqual(args.target_queue_depth_per_worker, 3)
        self.assertAlmostEqual(args.scale_interval_seconds, 2.5)
        self.assertAlmostEqual(args.scale_down_cooldown_seconds, 12.0)
        self.assertEqual(args.max_concurrency, 4)

    def test_build_config_clamps_max_workers_and_fixed_mode(self):
        args = start_worker._parse_args(
            [
                "--no-autoscale",
                "--workers",
                "3",
                "--min-workers",
                "5",
                "--max-workers",
                "2",
            ]
        )
        cfg = start_worker._build_config(args)

        self.assertFalse(cfg.autoscale)
        self.assertEqual(cfg.fixed_workers, 3)
        self.assertEqual(cfg.min_workers, 5)
        self.assertEqual(cfg.max_workers, 5)

    def test_build_worker_command_points_to_worker_script(self):
        cfg = start_worker.WorkerSupervisorConfig(
            autoscale=True,
            fixed_workers=1,
            min_workers=1,
            max_workers=3,
            target_queue_depth_per_worker=4,
            scale_interval_seconds=5.0,
            scale_down_cooldown_seconds=30.0,
            pop_timeout=20,
            idle_sleep=0.1,
            max_concurrency=2,
            sandbox_enabled=True,
            sandbox_strict=True,
            job_max_runtime_seconds=600,
            job_max_memory_mb=1024,
            job_max_cpu_seconds=300,
            log_level="INFO",
        )

        cmd = start_worker._build_worker_command(cfg)

        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("workers/upstash_job_worker.py", cmd[1].replace("\\", "/"))
        self.assertIn("--max-concurrency", cmd)
        self.assertIn("2", cmd)

    def test_run_supervisor_uses_priority_queue_depth_probe(self):
        class _QueueMonitor:
            queue_name = "job_queue"
            priority_queue_names = ("job_queue:high", "job_queue", "job_queue:low")

            def __init__(self):
                self.calls = []

            def queue_depth_many(self, *, queue_names):
                self.calls.append(tuple(queue_names))
                return 0

        monitor = _QueueMonitor()
        cfg = start_worker.WorkerSupervisorConfig(
            autoscale=True,
            fixed_workers=1,
            min_workers=1,
            max_workers=3,
            target_queue_depth_per_worker=4,
            scale_interval_seconds=5.0,
            scale_down_cooldown_seconds=30.0,
            pop_timeout=20,
            idle_sleep=0.1,
            max_concurrency=1,
            sandbox_enabled=True,
            sandbox_strict=True,
            job_max_runtime_seconds=600,
            job_max_memory_mb=1024,
            job_max_cpu_seconds=300,
            log_level="INFO",
        )

        with patch.object(start_worker, "UpstashRedisQueue", return_value=monitor), patch.object(
            start_worker,
            "_scale_workers",
            side_effect=KeyboardInterrupt(),
        ):
            start_worker.run_supervisor(cfg)

        self.assertGreaterEqual(len(monitor.calls), 1)
        self.assertEqual(monitor.calls[0], monitor.priority_queue_names)


if __name__ == "__main__":
    unittest.main()
