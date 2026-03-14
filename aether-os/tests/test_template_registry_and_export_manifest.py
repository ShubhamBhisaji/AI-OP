import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.template_registry import TemplateRegistry
from evals.quality_gate_patch_proposal import generate_proposal_report


class TemplateRegistryManifestTests(unittest.TestCase):
    def test_template_registry_has_version_for_externalized_templates(self):
        reg = TemplateRegistry(templates_dir=ROOT / "templates")
        self.assertNotEqual(reg.version("export_agent_run_agent.py.tpl"), "unknown")
        rendered = reg.render_tokens(
            "export_agent_run_agent.py.tpl",
            {
                "AGENT_NAME": "A",
                "AGENT_ROLE": "R",
                "AGENT_SKILLS": "S",
            },
        )
        self.assertIn("Standalone runner", rendered)

    def test_additional_externalized_templates_render(self):
        reg = TemplateRegistry(templates_dir=ROOT / "templates")
        readme = reg.render_tokens(
            "export_agent_readme.md.tpl",
            {
                "AGENT_NAME": "A",
                "AGENT_ROLE": "R",
                "AGENT_SKILLS": "S",
                "AGENT_TOOLS": "T",
                "AGENT_VERSION": "1.0.0",
                "SAFE_NAME": "A",
            },
        )
        self.assertIn("# A", readme)

        system_readme = reg.render_tokens(
            "export_system_readme.md.tpl",
            {
                "SYSTEM_NAME": "SYS",
                "AGENT_COUNT": "1",
                "AGENT_TABLE": "| a | r | launch_a.bat |",
            },
        )
        self.assertIn("SYS", system_readme)

    def test_render_tokens_raises_on_missing_tokens(self):
        reg = TemplateRegistry(templates_dir=ROOT / "templates")
        with self.assertRaises(ValueError):
            reg.render_tokens("export_agent_run_agent.py.tpl", {"AGENT_NAME": "x"})

    def test_quality_gate_patch_proposal_blocks_when_gates_fail(self):
        report = generate_proposal_report(
            {
                "python_unit_tests": True,
                "tours_checks": False,
                "security_checks": True,
            }
        )
        self.assertIn("patch_proposal", report)
        self.assertFalse(report["patch_proposal"]["allowed"])


if __name__ == "__main__":
    unittest.main()
