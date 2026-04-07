# Agent Name Goes Here

## Purpose
A one-sentence description of what this agent does and why it exists.

## Role
Optional: a more specific role title (e.g. "SEO Content Specialist").
If omitted, the Purpose is used as the role.

## Skills
- skill_one
- skill_two
- skill_three

## Tools
# ── Standard tools (no approval required) ──────────────────────────────
- web_search
# ── DESTRUCTIVE tools (Tier 1) — require ApprovalGate at each call ─────
# These tools make irreversible changes (file writes, email, messaging).
# ApprovalGate will prompt the operator before every call.
# In headless/CI mode they are auto-rejected.
- file_writer
# ── HIGH-RISK tools (Tier 2) — require ApprovalGate at each call ────────
# These tools execute code or mutate external infrastructure.
# - code_runner
# - terminal_tool
# - github_tool

## Objectives
- Clear, action-oriented objective statement
- Another measurable objective

## Permissions
- read:web
- write:workspace

## Integrations
- api

## Knowledge
- docs/reference_guide.txt
- https://example.com/knowledge-base

## Config
# permission_level: 1–5  (1=STANDARD default; 3=ELEVATED for Tier-1 tools; 4=PRIVILEGED for Tier-2)
permission_level: 1
