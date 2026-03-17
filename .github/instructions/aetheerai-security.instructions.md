---
description: "Use when building, editing, or running any AetheerAI agent, pipeline, or orchestration workflow. Enforces security tier rules: DESTRUCTIVE and HIGH_RISK tool classification, ApprovalGate requirements, PolicyEngine permission levels, and RedTeam gating. Apply to all agent factory calls, team assembly, and orchestrator.run() invocations."
applyTo: "AetheerAI/**/*.py"
---

# AetheerAI Security Rules — Always Apply

These rules are non-negotiable for any agent, pipeline, or orchestration code written in this workspace.

---

## Tool Tier Classification

Every tool assigned to an agent must be classified before use:

### Tier 1 — DESTRUCTIVE (irreversible external actions)
Requires `ApprovalGate` before execution. Auto-rejected in headless/CI mode.

| Tool | Action |
|---|---|
| `file_writer` | Writes / overwrites files on disk |
| `local_file_tool` | Generic local file operations |
| `email_tool` | Sends emails — external, irreversible |
| `slack_discord_tool` | Posts to team channels — external, irreversible |

### Tier 2 — HIGH_RISK (arbitrary code / cloud / DB mutations)
Requires `ApprovalGate` before execution. Auto-rejected in headless/CI mode.

| Tool | Action |
|---|---|
| `code_runner` | Executes Python in a subprocess |
| `terminal_tool` | Runs shell / PowerShell commands |
| `github_tool` | Commits and PRs on real repos |
| `aws_gcp_tool` | Cloud storage delete / EC2 stop-reboot |
| `kubernetes_tool` | Pod deletion / deployment restart / scaling |
| `sql_db_tool` | DML mutations on live databases |

### Tier 3 — STANDARD
No gate required. Use freely within permission level.

---

## ApprovalGate — Required for Tier 1 & 2

```python
from security.approval_gate import ApprovalGate, DESTRUCTIVE_TOOLS, HIGH_RISK_TOOLS

# Always gate before executing a Tier 1 or Tier 2 tool
approved = ApprovalGate.request("<tool_name>", {<tool_kwargs>})
# In headless/CI mode this auto-rejects — never bypass
```

**Never call a Tier 1 or Tier 2 tool directly without `ApprovalGate.request()` first.**

---

## PolicyEngine — Permission Levels

Use `PermissionLevel` from `security/policy_engine.py` — never bare integers.

| Level | Value | Assign When |
|---|---|---|
| `READ_ONLY` | 1 | Agent only reads data, no writes |
| `STANDARD` | 2 | Normal tool use, no destructive calls |
| `ELEVATED` | 3 | Needs Tier 1 tools (with approval gate) |
| `PRIVILEGED` | 4 | Needs Tier 2 tools (with approval gate) |
| `ADMIN` | 5 | Full access — use sparingly, document why |

```python
from security.policy_engine import PermissionLevel

factory.create(
    name="sender",
    role="automation_agent",
    tools=["slack_discord_tool"],
    permission_level=PermissionLevel.ELEVATED   # NOT bare integer 3
)
```

---

## RedTeam Gate — Required Before External Execution

Run `RedTeamCoordinator` before any workflow that writes, sends, or calls outside the local process.

```python
from core.red_team_agent import RedTeamCoordinator

report = RedTeamCoordinator(ai_adapter, audit_logger).run(
    target_description="<describe the integration>"
)

if report.severity in ("HIGH", "CRITICAL"):
    raise RuntimeError(f"RedTeam BLOCKED ({report.severity}): {report.findings}")
elif report.severity == "MEDIUM":
    # Warn — log, surface to user, then continue with caution
    print(f"[RedTeam WARNING] MEDIUM: {report.findings}")
# LOW / PASS — proceed
```

| Severity | Action |
|---|---|
| `CRITICAL` / `HIGH` | **Halt** — do not proceed |
| `MEDIUM` | **Warn** — log findings, continue with caution |
| `LOW` / `PASS` | **Proceed** |

**Skip RedTeam only for pure read/analyze-only workflows (no Tier 1/2 tools, no external writes).**

---

## Audit — Always Active

All tool calls must flow through `security/audit_logger.py`. Healing cycles are logged to `memory/audit_log.jsonl`. Never disable audit logging.

---

## Self-Healing Tuning

Set `MAX_HEALING_CYCLES` in `core/self_healer.py` per environment:

| Environment | Value |
|---|---|
| Production | `3` |
| Staging / QA | `2` (default) |
| Fast experimental | `1` |
