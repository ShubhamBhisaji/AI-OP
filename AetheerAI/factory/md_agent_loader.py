"""md_agent_loader.py — Parse agent definition Markdown files into AgentSpec.

Markdown format
---------------
Agent definition files follow a simple, human-friendly convention.
Each section maps to a field of ``AgentSpec``.  The file name (without
``.md``) is used as the default agent name when the heading name is absent.

Example
-------
```markdown
# my_research_agent

## Purpose
Find and summarise information from the web for a given topic.

## Role
Research Specialist

## Skills
- web_research
- summarization
- fact_checking

## Tools
- web_search
- file_writer

## Objectives
- Gather verifiable, sourced information
- Produce concise executive-summary reports

## Permissions
- read:web
- write:workspace

## Integrations
- api

## Knowledge
- docs/research_guidelines.txt
- https://example.com/knowledge-base

## Config
permission_level: 2
```

YAML front-matter (between ``---`` fences at the top of the file) is also
accepted and takes precedence over heading-based values:

```markdown
---
name: my_research_agent
purpose: Find and summarise information from the web
permission_level: 2
---
```

Usage
-----
from factory.md_agent_loader import MdAgentLoader

spec = MdAgentLoader.parse_file("agents/my_research_agent.md")
errors = spec.validate()
if not errors:
    agent = factory.build_from_spec(spec)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from agents.agent_spec import AgentSpec

logger = logging.getLogger(__name__)

# ── Section aliases ────────────────────────────────────────────────────────
# Maps heading text (lowercased) to canonical AgentSpec field.
_SECTION_ALIASES: dict[str, str] = {
    "purpose": "purpose",
    "description": "purpose",
    "about": "purpose",
    "role": "role",
    "role title": "role",
    "skills": "skills",
    "skill": "skills",
    "tools": "tools",
    "tool": "tools",
    "objectives": "objectives",
    "objective": "objectives",
    "goals": "objectives",
    "goal": "objectives",
    "permissions": "permissions",
    "permission": "permissions",
    "integrations": "integrations",
    "integration": "integrations",
    "knowledge": "knowledge",
    "knowledge sources": "knowledge",
    "config": "config",
    "configuration": "config",
    "settings": "config",
}

# ── Helpers ────────────────────────────────────────────────────────────────

def _strip_md_formatting(text: str) -> str:
    """Remove common Markdown inline formatting from a single-line string."""
    text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)  # bold / italic
    text = re.sub(r"`(.+?)`", r"\1", text)               # inline code
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)      # links
    return text.strip()


def _parse_list_block(lines: list[str]) -> list[str]:
    """Extract list items (``- item`` or ``* item`` or ``1. item``)."""
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Bullet list
        m = re.match(r"^[-*+]\s+(.+)$", stripped)
        if m:
            items.append(_strip_md_formatting(m.group(1)))
            continue
        # Numbered list
        m = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if m:
            items.append(_strip_md_formatting(m.group(1)))
            continue
        # Plain non-empty line that is not a sub-heading
        if stripped and not stripped.startswith("#"):
            items.append(_strip_md_formatting(stripped))
    return [i for i in items if i]


def _parse_config_block(lines: list[str]) -> dict[str, Any]:
    """Parse simple ``key: value`` pairs from a config section."""
    cfg: dict[str, Any] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip().lower().replace(" ", "_")
            val = val.strip()
            # Coerce to int/float/bool when possible
            if val.lower() in ("true", "yes"):
                cfg[key] = True
            elif val.lower() in ("false", "no"):
                cfg[key] = False
            else:
                try:
                    cfg[key] = int(val)
                except ValueError:
                    try:
                        cfg[key] = float(val)
                    except ValueError:
                        cfg[key] = val
    return cfg


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """
    Extract YAML-style front matter (between ``---`` fences).

    Returns ``(front_matter_dict, remaining_text)``.
    A simple key/value parser is used — no full YAML dependency required.
    """
    pattern = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    m = pattern.match(text)
    if not m:
        return {}, text
    raw_fm = m.group(1)
    remaining = text[m.end():]
    fm: dict[str, Any] = {}
    for line in raw_fm.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip().lower().replace(" ", "_").replace("-", "_")
            val = val.strip()
            if val.lower() in ("true", "yes"):
                fm[key] = True
            elif val.lower() in ("false", "no"):
                fm[key] = False
            else:
                try:
                    fm[key] = int(val)
                except ValueError:
                    try:
                        fm[key] = float(val)
                    except ValueError:
                        fm[key] = val
    return fm, remaining


# ── Main parser ────────────────────────────────────────────────────────────

class MdAgentLoader:
    """Parse Markdown agent definition files into ``AgentSpec`` instances."""

    # ── Public API ─────────────────────────────────────────────────────────

    @classmethod
    def parse_file(cls, path: str | Path, *, default_name: str | None = None) -> AgentSpec:
        """
        Parse a Markdown agent definition file and return an ``AgentSpec``.

        Parameters
        ----------
        path:
            Path to the ``.md`` file.
        default_name:
            Agent name to use when the file does not declare one.
            Defaults to the stem of the file name.

        Returns
        -------
        AgentSpec
            Parsed, unvalidated spec.  Call ``spec.validate()`` before use.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Agent markdown file not found: {path}")
        text = path.read_text(encoding="utf-8")
        stem = path.stem  # filename without extension
        return cls.parse_text(text, default_name=default_name or stem)

    @classmethod
    def parse_text(cls, text: str, *, default_name: str = "unnamed_agent") -> AgentSpec:
        """
        Parse a Markdown string and return an ``AgentSpec``.

        Parameters
        ----------
        text:
            Full Markdown content of the agent definition.
        default_name:
            Fallback agent name.

        Returns
        -------
        AgentSpec
        """
        # 1. Strip front matter (highest precedence)
        front_matter, body = _parse_front_matter(text)

        # 2. Build section map from H2 headings in the body
        sections = cls._split_sections(body)

        # 3. Extract the top-level H1 heading as a name candidate
        h1_name = cls._extract_h1(body)

        # 4. Resolve each field (front matter > body sections > defaults)
        raw_name: str = (
            str(front_matter.get("name", "")).strip()
            or _strip_md_formatting(h1_name)
            or default_name
        )
        # Normalise name: lower, replace spaces with underscores
        name = re.sub(r"[^\w]", "_", raw_name.lower()).strip("_") or default_name

        purpose: str = (
            str(front_matter.get("purpose", "")).strip()
            or cls._text_from_section(sections, "purpose")
            or f"Agent: {name.replace('_', ' ').title()}"
        )

        # Role is not a field on AgentSpec but is stored in metadata
        role: str = (
            str(front_matter.get("role", "")).strip()
            or cls._text_from_section(sections, "role")
            or ""
        )

        skills: list[str] = (
            cls._list_from_fm(front_matter, "skills")
            or cls._list_from_section(sections, "skills")
        )
        tools: list[str] = (
            cls._list_from_fm(front_matter, "tools")
            or cls._list_from_section(sections, "tools")
        )
        objectives: list[str] = (
            cls._list_from_fm(front_matter, "objectives")
            or cls._list_from_section(sections, "objectives")
        )
        permissions: list[str] = (
            cls._list_from_fm(front_matter, "permissions")
            or cls._list_from_section(sections, "permissions")
        )
        integrations: list[str] = (
            cls._list_from_fm(front_matter, "integrations")
            or cls._list_from_section(sections, "integrations")
        )
        knowledge: list[str] = (
            cls._list_from_fm(front_matter, "knowledge")
            or cls._list_from_section(sections, "knowledge")
        )

        # Config block — front-matter keys win over inline config section
        config_section: dict[str, Any] = _parse_config_block(
            sections.get("config", [])
        )
        permission_level: int = int(
            front_matter.get(
                "permission_level",
                config_section.get("permission_level", 1),
            )
        )
        permission_level = max(0, min(5, permission_level))

        # Metadata: store role and any extra front-matter keys
        metadata: dict[str, Any] = {}
        if role:
            metadata["role"] = role
        for k, v in front_matter.items():
            if k not in {
                "name", "purpose", "permission_level", "skills", "tools",
                "objectives", "permissions", "integrations", "knowledge",
            }:
                metadata[k] = v
        for k, v in config_section.items():
            if k != "permission_level":
                metadata.setdefault(k, v)

        spec = AgentSpec(
            name=name,
            purpose=purpose,
            skills=skills,
            tools=tools,
            objectives=objectives,
            permissions=permissions,
            integrations=integrations,
            knowledge=knowledge,
            permission_level=permission_level,
            metadata=metadata,
        )
        logger.debug("MdAgentLoader: parsed spec for '%s' from markdown.", name)
        return spec

    @classmethod
    def load_directory(
        cls,
        directory: str | Path,
        *,
        recursive: bool = False,
    ) -> list[AgentSpec]:
        """
        Load all ``.md`` files in *directory* as agent specs.

        Parameters
        ----------
        directory:
            Path to the folder containing ``.md`` agent definition files.
        recursive:
            If ``True``, scan sub-directories as well.

        Returns
        -------
        list[AgentSpec]
            Successfully parsed specs (invalid files are logged and skipped).
        """
        directory = Path(directory)
        if not directory.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")

        pattern = "**/*.md" if recursive else "*.md"
        specs: list[AgentSpec] = []
        for md_file in sorted(directory.glob(pattern)):
            try:
                spec = cls.parse_file(md_file)
                errors = spec.validate()
                if errors:
                    logger.warning(
                        "MdAgentLoader: '%s' has validation errors — skipping: %s",
                        md_file.name, "; ".join(errors),
                    )
                    continue
                specs.append(spec)
                logger.info("MdAgentLoader: loaded spec '%s' from '%s'.", spec.name, md_file.name)
            except Exception as exc:
                logger.warning("MdAgentLoader: failed to parse '%s': %s", md_file.name, exc)
        return specs

    # ── Private helpers ────────────────────────────────────────────────────

    @staticmethod
    def _split_sections(text: str) -> dict[str, list[str]]:
        """
        Split body text into a dict of ``{canonical_field: [content lines]}``.

        Only H2 headings (``## Heading``) are used as section delimiters.
        """
        sections: dict[str, list[str]] = {}
        current_key: str | None = None
        current_lines: list[str] = []

        for line in text.splitlines():
            h2_match = re.match(r"^##\s+(.+)$", line)
            if h2_match:
                if current_key is not None:
                    sections[current_key] = current_lines
                heading_raw = h2_match.group(1).strip().lower()
                current_key = _SECTION_ALIASES.get(heading_raw)
                current_lines = []
            else:
                if current_key is not None:
                    current_lines.append(line)

        if current_key is not None:
            sections[current_key] = current_lines

        return sections

    @staticmethod
    def _extract_h1(text: str) -> str:
        """Return the text of the first H1 heading (``# Heading``), or ``''``."""
        for line in text.splitlines():
            m = re.match(r"^#\s+(.+)$", line)
            if m:
                return m.group(1).strip()
        return ""

    @staticmethod
    def _text_from_section(sections: dict[str, list[str]], key: str) -> str:
        """Return all non-empty lines in a section joined into one string."""
        lines = sections.get(key, [])
        parts = [
            _strip_md_formatting(line.strip())
            for line in lines
            if line.strip() and not line.strip().startswith("#")
               and not re.match(r"^[-*+]\s", line.strip())
               and not re.match(r"^\d+[.)]\s", line.strip())
        ]
        return " ".join(parts).strip()

    @staticmethod
    def _list_from_section(sections: dict[str, list[str]], key: str) -> list[str]:
        """Extract a list from a section's content."""
        return _parse_list_block(sections.get(key, []))

    @staticmethod
    def _list_from_fm(fm: dict[str, Any], key: str) -> list[str]:
        """Extract a list value from front matter (handles comma-separated strings)."""
        val = fm.get(key)
        if val is None:
            return []
        if isinstance(val, list):
            return [str(item).strip() for item in val if str(item).strip()]
        if isinstance(val, str):
            return [s.strip() for s in val.split(",") if s.strip()]
        return []
