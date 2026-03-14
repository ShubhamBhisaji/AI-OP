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

    def test_export_impl_prefers_exporter_base_when_present(self):
        kernel = object.__new__(AetherKernel)

        class _Exporter:
            def _base_export_agent(self, name):
                return {"path": "base", "name": name}

            def _base_export_system(self, system_name, agent_names):
                return {"path": "base", "system": system_name, "agents": agent_names}

        kernel.exporter = _Exporter()

        out_agent = AetherKernel._export_agent_impl(kernel, "alpha")
        out_system = AetherKernel._export_system_impl(kernel, "sys", ["a1"])

        self.assertEqual(out_agent["path"], "base")
        self.assertEqual(out_agent["name"], "alpha")
        self.assertEqual(out_system["path"], "base")
        self.assertEqual(out_system["system"], "sys")

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
