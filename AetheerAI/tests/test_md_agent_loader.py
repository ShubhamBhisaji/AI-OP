"""test_md_agent_loader.py — Tests for the Markdown agent definition loader.

Covers:
- Heading-based section parsing
- YAML front-matter parsing
- AgentSpec field extraction
- MdAgentLoader.load_directory()
- AgentFactory.create_from_markdown()
- AgentFactory.load_agents_from_directory()
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Fix import path ──────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ════════════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════════════

MINIMAL_MD = textwrap.dedent("""\
    # my_test_agent

    ## Purpose
    Test the Markdown loader end-to-end.

    ## Skills
    - summarization
    - fact_checking

    ## Tools
    - web_search
    - file_writer

    ## Config
    permission_level: 2
""")

FULL_MD = textwrap.dedent("""\
    # full_agent

    ## Purpose
    A fully configured agent for comprehensive testing.

    ## Role
    Quality Assurance Specialist

    ## Skills
    - testing
    - debugging
    - reporting

    ## Tools
    - file_writer
    - code_runner

    ## Objectives
    - Verify all outputs are correct
    - File detailed bug reports

    ## Permissions
    - read:workspace
    - write:workspace
    - execute:code

    ## Integrations
    - api

    ## Knowledge
    - docs/qa_guidelines.txt
    - https://example.com/test-strategy

    ## Config
    permission_level: 3
""")

FRONT_MATTER_MD = textwrap.dedent("""\
    ---
    name: fm_agent
    purpose: Agent defined via front matter
    permission_level: 1
    skills: web_research, fact_checking
    ---

    Some extra body text ignored for spec purposes.
""")


# ════════════════════════════════════════════════════════════════════════════
# MdAgentLoader unit tests
# ════════════════════════════════════════════════════════════════════════════

class TestMdAgentLoaderParseText:
    """Tests for MdAgentLoader.parse_text()."""

    def setup_method(self):
        from factory.md_agent_loader import MdAgentLoader
        self.loader = MdAgentLoader

    def test_minimal_name_from_h1(self):
        spec = self.loader.parse_text(MINIMAL_MD)
        assert spec.name == "my_test_agent"

    def test_minimal_purpose(self):
        spec = self.loader.parse_text(MINIMAL_MD)
        assert "test" in spec.purpose.lower()

    def test_minimal_skills(self):
        spec = self.loader.parse_text(MINIMAL_MD)
        assert "summarization" in spec.skills
        assert "fact_checking" in spec.skills

    def test_minimal_tools(self):
        spec = self.loader.parse_text(MINIMAL_MD)
        assert "web_search" in spec.tools
        assert "file_writer" in spec.tools

    def test_minimal_permission_level(self):
        spec = self.loader.parse_text(MINIMAL_MD)
        assert spec.permission_level == 2

    def test_full_agent_role_in_metadata(self):
        spec = self.loader.parse_text(FULL_MD)
        assert spec.metadata.get("role") == "Quality Assurance Specialist"

    def test_full_objectives(self):
        spec = self.loader.parse_text(FULL_MD)
        assert len(spec.objectives) == 2
        assert any("correct" in o.lower() for o in spec.objectives)

    def test_full_permissions(self):
        spec = self.loader.parse_text(FULL_MD)
        assert "read:workspace" in spec.permissions
        assert "execute:code" in spec.permissions

    def test_full_integrations(self):
        spec = self.loader.parse_text(FULL_MD)
        assert "api" in spec.integrations

    def test_full_knowledge(self):
        spec = self.loader.parse_text(FULL_MD)
        assert any("qa_guidelines" in k for k in spec.knowledge)
        assert any("http" in k for k in spec.knowledge)

    def test_full_permission_level(self):
        spec = self.loader.parse_text(FULL_MD)
        assert spec.permission_level == 3

    def test_front_matter_name(self):
        spec = self.loader.parse_text(FRONT_MATTER_MD)
        assert spec.name == "fm_agent"

    def test_front_matter_purpose(self):
        spec = self.loader.parse_text(FRONT_MATTER_MD)
        assert "front matter" in spec.purpose.lower()

    def test_front_matter_skills_csv(self):
        spec = self.loader.parse_text(FRONT_MATTER_MD)
        assert "web_research" in spec.skills
        assert "fact_checking" in spec.skills

    def test_front_matter_permission_level(self):
        spec = self.loader.parse_text(FRONT_MATTER_MD)
        assert spec.permission_level == 1

    def test_permission_level_clamped_high(self):
        md = "# clamp_agent\n## Purpose\nTest.\n## Config\npermission_level: 99\n"
        spec = self.loader.parse_text(md)
        assert spec.permission_level == 5

    def test_permission_level_clamped_low(self):
        md = "# clamp_agent\n## Purpose\nTest.\n## Config\npermission_level: -5\n"
        spec = self.loader.parse_text(md)
        assert spec.permission_level == 0

    def test_name_normalised_spaces(self):
        md = "# My Research Agent\n## Purpose\nTest.\n"
        spec = self.loader.parse_text(md)
        assert spec.name == "my_research_agent"

    def test_default_name_from_param(self):
        md = "## Purpose\nNo heading.\n"
        spec = self.loader.parse_text(md, default_name="fallback_agent")
        assert spec.name == "fallback_agent"

    def test_validation_passes_for_valid_md(self):
        spec = self.loader.parse_text(MINIMAL_MD)
        assert spec.is_valid(), spec.validate()

    def test_validation_passes_for_full_md(self):
        spec = self.loader.parse_text(FULL_MD)
        assert spec.is_valid(), spec.validate()


class TestMdAgentLoaderParseFile:
    """Tests for MdAgentLoader.parse_file()."""

    def setup_method(self):
        from factory.md_agent_loader import MdAgentLoader
        self.loader = MdAgentLoader

    def test_parse_file_reads_correctly(self, tmp_path):
        md_file = tmp_path / "test_agent.md"
        md_file.write_text(MINIMAL_MD, encoding="utf-8")
        spec = self.loader.parse_file(md_file)
        assert spec.name == "my_test_agent"
        assert "web_search" in spec.tools

    def test_parse_file_uses_stem_as_default_name(self, tmp_path):
        md_file = tmp_path / "stem_name_agent.md"
        md_file.write_text("## Purpose\nJust testing.\n", encoding="utf-8")
        spec = self.loader.parse_file(md_file)
        assert spec.name == "stem_name_agent"

    def test_parse_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            self.loader.parse_file("/nonexistent/path/agent.md")


class TestMdAgentLoaderDirectory:
    """Tests for MdAgentLoader.load_directory()."""

    def setup_method(self):
        from factory.md_agent_loader import MdAgentLoader
        self.loader = MdAgentLoader

    def test_load_directory_returns_specs(self, tmp_path):
        (tmp_path / "agent_a.md").write_text(MINIMAL_MD, encoding="utf-8")
        (tmp_path / "agent_b.md").write_text(FULL_MD, encoding="utf-8")
        specs = self.loader.load_directory(tmp_path)
        names = {s.name for s in specs}
        assert "my_test_agent" in names
        assert "full_agent" in names

    def test_load_directory_skips_invalid(self, tmp_path):
        # A file that causes a parse error (e.g. binary content) should be skipped.
        # All valid .md files produce at least a fallback-purpose spec, so we
        # test that malformed binary files don't crash the loader.
        bad_file = tmp_path / "bad_binary.md"
        bad_file.write_bytes(b"\xff\xfe" + b"\x00" * 10)  # invalid UTF-8
        (tmp_path / "good.md").write_text(MINIMAL_MD, encoding="utf-8")
        specs = self.loader.load_directory(tmp_path)
        names = {s.name for s in specs}
        # Only the good file should produce a spec
        assert "my_test_agent" in names
        assert "bad_binary" not in names

    def test_load_directory_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested_agent.md").write_text(FULL_MD, encoding="utf-8")
        specs = self.loader.load_directory(tmp_path, recursive=True)
        names = {s.name for s in specs}
        assert "full_agent" in names

    def test_load_directory_not_a_directory(self):
        with pytest.raises(NotADirectoryError):
            self.loader.load_directory("/nonexistent/dir")


# ════════════════════════════════════════════════════════════════════════════
# AgentFactory integration tests
# ════════════════════════════════════════════════════════════════════════════

def _make_factory(tmp_path):
    """Build a minimal AgentFactory with stub dependencies."""
    from factory.agent_factory import AgentFactory
    from registry.agent_registry import AgentRegistry
    from tools.tool_manager import ToolManager

    registry = AgentRegistry(persist=False)
    tm = ToolManager()
    ai = MagicMock()
    ai.chat.return_value = "mock response"
    return AgentFactory(
        registry=registry,
        tool_manager=tm,
        ai_adapter=ai,
        template_store_path=str(tmp_path / "templates.json"),
    )


class TestAgentFactoryMarkdown:
    """Tests for AgentFactory.create_from_markdown() and load_agents_from_directory()."""

    def test_create_from_markdown_returns_agent(self, tmp_path):
        md_file = tmp_path / "my_test_agent.md"
        md_file.write_text(MINIMAL_MD, encoding="utf-8")
        factory = _make_factory(tmp_path)
        agent = factory.create_from_markdown(str(md_file))
        assert agent.name == "my_test_agent"

    def test_create_from_markdown_skills(self, tmp_path):
        md_file = tmp_path / "my_test_agent.md"
        md_file.write_text(MINIMAL_MD, encoding="utf-8")
        factory = _make_factory(tmp_path)
        agent = factory.create_from_markdown(str(md_file))
        assert "summarization" in agent.skills

    def test_create_from_markdown_permission_level(self, tmp_path):
        md_file = tmp_path / "my_test_agent.md"
        md_file.write_text(MINIMAL_MD, encoding="utf-8")
        factory = _make_factory(tmp_path)
        agent = factory.create_from_markdown(str(md_file))
        assert agent.permission_level == 2

    def test_create_from_markdown_registers_in_registry(self, tmp_path):
        md_file = tmp_path / "my_test_agent.md"
        md_file.write_text(MINIMAL_MD, encoding="utf-8")
        factory = _make_factory(tmp_path)
        factory.create_from_markdown(str(md_file))
        assert factory.registry.get("my_test_agent") is not None

    def test_create_from_markdown_file_not_found(self, tmp_path):
        factory = _make_factory(tmp_path)
        with pytest.raises(FileNotFoundError):
            factory.create_from_markdown(str(tmp_path / "missing.md"))

    def test_create_from_markdown_invalid_spec(self, tmp_path):
        # The loader always produces a valid spec (with fallback purpose/name),
        # so an "empty" .md file still creates an agent using the file stem as name.
        md_file = tmp_path / "minimal_agent.md"
        md_file.write_text("## Skills\n- testing\n", encoding="utf-8")
        factory = _make_factory(tmp_path)
        agent = factory.create_from_markdown(str(md_file))
        # Name comes from stem, purpose gets a fallback value
        assert agent.name == "minimal_agent"
        assert "testing" in agent.skills

    def test_load_agents_from_directory(self, tmp_path):
        (tmp_path / "agent_a.md").write_text(MINIMAL_MD, encoding="utf-8")
        (tmp_path / "agent_b.md").write_text(FULL_MD, encoding="utf-8")
        factory = _make_factory(tmp_path)
        agents = factory.load_agents_from_directory(str(tmp_path))
        names = {a.name for a in agents}
        assert "my_test_agent" in names
        assert "full_agent" in names

    def test_load_agents_from_directory_skip_existing(self, tmp_path):
        md_file = tmp_path / "my_test_agent.md"
        md_file.write_text(MINIMAL_MD, encoding="utf-8")
        factory = _make_factory(tmp_path)
        first_batch = factory.load_agents_from_directory(str(tmp_path))
        second_batch = factory.load_agents_from_directory(str(tmp_path), skip_existing=True)
        assert len(first_batch) == 1
        assert len(second_batch) == 0  # already registered

    def test_load_agents_from_directory_not_a_dir(self, tmp_path):
        factory = _make_factory(tmp_path)
        with pytest.raises(NotADirectoryError):
            factory.load_agents_from_directory(str(tmp_path / "nonexistent"))
