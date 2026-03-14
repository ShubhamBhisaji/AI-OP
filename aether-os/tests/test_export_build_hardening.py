import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.aether_kernel import AetherKernel


class _DummyAI:
    def chat(self, messages):
        return (
            "=== FILE: ../outside.py ===\n"
            "print('x')\n"
            "=== END FILE ===\n"
            "=== FILE: safe/main.py ===\n"
            "print('ok')\n"
            "=== END FILE ===\n"
        )


class _DummyMemory:
    def save(self, key, value):
        self.last = (key, value)


class ExportBuildHardeningTests(unittest.TestCase):
    def test_safe_fs_component_blocks_traversal_corpus(self):
        corpus = [
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            "/abs/path",
            "..",
            "./../x",
            "a/../../b",
            "C:\\Windows\\Temp",
        ]
        for raw in corpus:
            safe = AetherKernel._safe_fs_component(raw, fallback="x")
            self.assertTrue(safe)
            self.assertNotIn("..", safe)
            self.assertNotIn("/", safe)
            self.assertNotIn("\\", safe)

    def test_build_application_sanitizes_written_paths(self):
        kernel = object.__new__(AetherKernel)
        kernel.ai_adapter = _DummyAI()
        kernel.memory = _DummyMemory()

        written: list[str] = []

        def _fake_file_writer(filename: str, content: str):
            written.append(filename)
            return "File written successfully"

        with patch("tools.file_writer.file_writer", side_effect=_fake_file_writer):
            out = kernel.build_application("../../my app")

        self.assertIn("files", out)
        self.assertGreaterEqual(len(written), 2)
        for name in written:
            normalized = name.replace("\\", "/")
            self.assertNotIn("..", normalized)
            self.assertTrue(normalized.startswith("my_app/"))

    def test_no_hardcoded_gpt41_fallback_in_export_runtime_templates(self):
        src = (ROOT / "core" / "aether_kernel.py").read_text(encoding="utf-8")
        self.assertNotIn('_model or "gpt-4.1"', src)
        self.assertNotIn('os.environ.get("AI_MODEL", "gpt-4.1")', src)


if __name__ == "__main__":
    unittest.main()
