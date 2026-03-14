import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.aether_kernel import AetherKernel
from core.template_registry import TemplateRegistry


class ServiceExtractionTemplateTests(unittest.TestCase):
    def test_build_application_delegate_falls_back_without_compiler(self):
        kernel = object.__new__(AetherKernel)
        kernel._build_application_impl = lambda app_name, progress=None: {"ok": app_name}

        out = kernel.build_application("demo")
        self.assertEqual(out["ok"], "demo")

    def test_export_delegate_falls_back_without_exporter(self):
        kernel = object.__new__(AetherKernel)
        kernel._export_agent_impl = lambda name: {"name": name, "ok": True}

        out = kernel.export_agent("alpha")
        self.assertEqual(out["name"], "alpha")
        self.assertTrue(out["ok"])

    def test_template_registry_renders_templates(self):
        reg = TemplateRegistry(templates_dir=ROOT / "templates")
        out = reg.render(
            "build_application_prompt.txt.tpl",
            {"app_name": "sample-app"},
        )
        self.assertIn("sample-app", out)
        self.assertIn("=== FILE:", out)


if __name__ == "__main__":
    unittest.main()
