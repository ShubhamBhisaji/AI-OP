---
name: aetheerai-orchestration
description: 'Build and run AetheerAI multi-agent teams using the Project Manager and Digital Assembly Line patterns. Use when: spawning sub-agents, defining agent roles, wiring orchestration pipelines, choosing coordination modes (pipeline/vote/broadcast/debate/best_of/orchestrate), creating teams, configuring AgentFactory, delegating goals to a managed team of specialist agents, building sequential data pipelines, or enabling self-healing fault-tolerant workflows. The Master (Orchestrator) acts as the CEO Project Manager — it decomposes a goal, hires the right agents, and drives them to completion. If one machine (agent) breaks, the Master AI fixes or replaces it instantly without stopping the line.'
argument-hint: 'Describe the goal or system you want to orchestrate (e.g., "build a research + coding team" or "run a pipeline for content generation")'
---

# AetheerAI Orchestration — The Project Manager & Digital Assembly Line

> **Pattern 1 — The Project Manager:** You are the CEO. You give a goal to the **Project Manager** (AetheerAI Orchestrator). The PM hires specialists (sub-agents), delegates work, and returns a finished result — you never write every email or code every feature yourself.

> **Pattern 2 — The Digital Assembly Line:** In 2024, AI was a single craftsman making one thing at a time. AetheerAI is the Factory Owner. It builds a Digital Assembly Line where each agent is a machine on the line — raw data in, finished output out. If one machine breaks, the Master AI fixes or replaces it instantly without stopping the whole line.

---

## When to Use This Skill

- Designing a new multi-agent workflow from scratch
- Adding agents to an existing team in the registry
- Choosing the right coordination mode for a goal
- Building a sequential data pipeline (fetch → clean → analyze → deliver)
- Enabling self-healing / fault-tolerant agent workflows
- Debugging why agents aren't collaborating correctly
- Exporting or extending an orchestrated team

---

## Core Architecture

```
User Goal (CLI / API)
  └─ AetheerAiKernel          core/aetheerai_kernel.py
       └─ Orchestrator        core/orchestrator.py       ← "The Project Manager"
            ├─ TeamManager    core/team_manager.py       ← resolves team → agents
            ├─ AgentRegistry  registry/agent_registry.py ← live agent lookup
            ├─ AgentFactory   factory/agent_factory.py   ← creates & registers agents
            └─ BaseAgent ×N   agents/base_agent.py       ← the specialist "employees"
                 └─ result → Orchestrator synthesizes → final answer to user
```

---

## Step-by-Step Workflow

### Step 1 — Define the Goal

State the end outcome clearly. The less ambiguous, the better the orchestration result. Examples:
- "Research competitors and produce a summary report"
- "Build a REST API endpoint and write its unit tests"
- "Generate marketing copy, then review it for tone"

### Step 2 — Choose Your Agent Roster

Use `AgentFactory.AGENT_PRESETS` to pick built-in agent types. Mix and match based on the goal:

| Preset Name           | Specialty                                 |
|-----------------------|-------------------------------------------|
| `research_agent`      | Web research, summarization               |
| `coding_agent`        | Code generation, debugging                |
| `marketing_agent`     | Copywriting, messaging                    |
| `automation_agent`    | Scripts, workflows, task automation       |
| `data_analysis_agent` | Data parsing, stats, visualization        |
| `chatbot_agent`       | Conversational UI, Q&A                    |
| `api_agent`           | REST/GraphQL integration, data fetching   |
| `business_agent`      | Business logic, planning, decision-making |

> **Decision rule:** Does the task require output from one agent to feed another? → `pipeline`. Does it need diverse independent views? → `vote` or `broadcast`. Does it need adversarial critique? → `debate`.

### Step 3 — Create the Agents

```python
# factory/agent_factory.py — AgentFactory.create()
factory.create(
    name="my_coder",
    role="coding_agent",          # matches a AGENT_PRESETS key
    tools=["code_runner"],        # validated against ToolManager
    skills=["python", "testing"],
    permission_level=1            # 0=GUEST 1=STANDARD 2=ELEVATED 3=ADMIN
)
```

Each agent gets a UUID, RBAC permission level, and a `history[]` for audit.

### Step 4 — Assemble the Team

```python
# core/team_manager.py — TeamManager.create_team()
team_manager.create_team(
    name="product_launch_team",
    agent_names=["my_researcher", "my_coder", "my_marketer"]
)
# Persisted to registry/teams_store.json
```

`TeamManager` validates that every name exists in `AgentRegistry` before saving.

### Step 5 — Choose a Coordination Mode

| Mode          | When to Use                                        | Notes                                              |
|---------------|----------------------------------------------------|----------------------------------------------------|
| `pipeline`    | Steps are sequential; output[i] is input[i+1]      | Injection-fence sanitization between steps         |
| `broadcast`   | All agents get the same prompt independently        | Good for parallel execution of the same task       |
| `vote`        | All agents answer; AI synthesizes consensus         | Use for judgment or analysis tasks                 |
| `best_of`     | All agents attempt; AI picks single best answer     | Use when quality matters more than diversity       |
| `debate`      | Two agents argue opposing sides for N rounds        | Capped at `MAX_DEBATE_ROUNDS = 10`                 |
| `orchestrate` | AI auto-selects agents + mode based on goal text    | Best for novel goals with no prior configuration   |

### Step 6 — Run the Orchestration

```python
# core/orchestrator.py — Orchestrator.run()
result = orchestrator.run(
    task="Research our top 3 competitors and write a product positioning doc.",
    team_name="product_launch_team",
    mode="pipeline"               # or "vote", "broadcast", "debate", "best_of", "orchestrate"
)
```

The Orchestrator:
1. Resolves `team_name` → agent list via `TeamManager → AgentRegistry`
2. Executes the task under the selected mode
3. Runs `_STEP_VALIDATION_PROMPT` (hallucination check) between pipeline steps
4. Synthesizes or selects the final result
5. Returns it to the caller

### Step 7 — Verify and Audit

- Agent performance is tracked on `BaseAgent`: `tasks_completed`, `tasks_failed`, `success_rate`
- All tool calls flow through `security/audit_logger.py` and `memory/audit_log.jsonl`
- Teams persist in `registry/teams_store.json`; agents in `registry/registry_store.json`

---

## The Digital Assembly Line Pattern

Use this pattern when your goal is a **sequential data flow** — each agent produces output that the next agent consumes, like machines on a factory floor.

### Assembly Line Anatomy

```
Raw Input
  │
  ▼
[ Agent 1: Fetcher ]      api_agent       — grabs raw data from a source
  │  output[1] → input[2]
  ▼
[ Agent 2: Cleaner ]      data_analysis_agent — normalizes, deduplicates
  │  output[2] → input[3]
  ▼
[ Agent 3: Analyzer ]     business_agent  — extracts insights, decisions
  │  output[3] → input[4]
  ▼
[ Agent 4: Dispatcher ]   automation_agent — pushes to Slack, Gmail, etc.
  │
  ▼
Delivered Result
```

> This is exactly the `pipeline` coordination mode. Each stage's output becomes the next stage's full input. The Orchestrator enforces a `_MAX_PIPELINE_PASSTHROUGH_CHARS` limit (12 000 chars) and runs an injection-fence between every step.

### Building an Assembly Line

```python
# 1. Create each station on the line
for name, role, tools in [
    ("fetcher",    "api_agent",           ["http_get"]),
    ("cleaner",    "data_analysis_agent", ["data_parser"]),
    ("analyzer",   "business_agent",      ["summarizer"]),
    ("dispatcher", "automation_agent",    ["slack_send", "gmail_send"]),
]:
    factory.create(name=name, role=role, tools=tools, permission_level=1)

# 2. Assemble the line as a team (order matters for pipeline mode)
team_manager.create_team(
    name="data_pipeline",
    agent_names=["fetcher", "cleaner", "analyzer", "dispatcher"]
)

# 3. Run the line
result = orchestrator.run(
    task="Fetch yesterday's sales data, clean it, summarize trends, and post to #sales-alerts on Slack.",
    team_name="data_pipeline",
    mode="pipeline"   # sequential: output[i] → input[i+1]
)
```

> **Order is the pipeline.** Agents run in the order they appear in `agent_names`. Design your list from left (raw input) to right (final delivery).

---

## Self-Healing — The Line Never Stops

When a station (agent) fails, AetheerAI doesn't halt the whole assembly line. `SelfHealingDebugger` (`core/self_healer.py`) intercepts the failure silently and repairs it:

```
Agent fails
  └─ SelfHealingDebugger intercepts
       ├─ Master AI diagnoses ROOT_CAUSE
       ├─ Master AI generates PATCH_INSTRUCTIONS
       ├─ Agent re-runs with patched task  (up to MAX_HEALING_CYCLES = 2)
       │    ├─ success → pipeline continues seamlessly
       │    └─ still failing → cycle again (up to limit)
       └─ After MAX_HEALING_CYCLES exhausted → honest error surfaced to user
            └─ Every healing cycle recorded in memory/audit_log.jsonl
```

### Self-Healing Reference

| Constant | Value | Meaning |
|---|---|---|
| `MAX_HEALING_CYCLES` | `2` | Max autonomous repair attempts per failure |
| `_DIAGNOSIS_PROMPT` | internal | Master AI prompt: produces `ROOT_CAUSE` + `PATCH_INSTRUCTIONS` |
| Healing record | `HealingRecord` / `HealingCycle` | Immutable audit trail per failed task |

### What the Master AI Does During a Failure

1. Receives the agent name, role, original task, and error output
2. Diagnoses the root cause in one sentence (`ROOT_CAUSE:`)
3. Produces revised step-by-step instructions that avoid the same mistake (`PATCH_INSTRUCTIONS:`)
4. Re-deploys the same agent with the patched task — **no human intervention needed**
5. Logs the full healing cycle to `MemoryManager` for observability

> The human never sees transient failures — only healed results or an honest final error after all healing cycles are exhausted.

### Tuning Self-Healing

```python
# core/self_healer.py
MAX_HEALING_CYCLES: int = 2   # increase for more resilient pipelines,
                               # decrease for faster fail-fast behavior
```

For **critical production pipelines**, set `MAX_HEALING_CYCLES = 3`. For **fast experimental loops**, set it to `1`.

---

## Decision Checklist

Before running the orchestration, confirm:

- [ ] Goal is stated clearly (no ambiguity in scope)
- [ ] The right preset roles are selected for the task
- [ ] All agent names are registered (`AgentRegistry.list_names()`)
- [ ] Team has been created with `TeamManager.create_team()`
- [ ] Coordination mode matches the task structure (sequential → `pipeline`, parallel opinions → `vote`)
- [ ] Permission levels are set appropriately for the tools each agent needs
- [ ] Audit logging is enabled for compliance-sensitive tasks

---

## Common Pitfalls

| Problem | Cause | Fix |
|---|---|---|
| Agent not found at runtime | Name not registered in `AgentRegistry` | Call `factory.create()` before `team_manager.create_team()` |
| Pipeline output garbled | Prompt-injection in intermediate result | Injection-fence fires automatically; check `_MAX_PIPELINE_PASSTHROUGH_CHARS = 12 000` |
| Debate never converges | Too many rounds | Default cap is `MAX_DEBATE_ROUNDS = 10`; reduce for faster runs |
| Sub-agent blocked on tool | Permission level too low | Set `permission_level=2` for `ELEVATED` or `3` for `ADMIN` |
| Team creation fails | Agent name typo or not yet registered | Verify with `registry.list_names()` before `create_team()` |
| Self-healer keeps failing | Root cause not patchable by AI | Check `audit_log.jsonl` for `HealingRecord`; fix the tool or prompt manually |
| Pipeline truncated mid-flow | Output exceeded `_MAX_PIPELINE_PASSTHROUGH_CHARS` | Summarize earlier-stage output before passing; split into sub-pipelines |

---

## References

- Orchestrator modes + pipeline injection-fence: `AetheerAI/core/orchestrator.py`
- Agent factory presets: `AetheerAI/factory/agent_factory.py`
- Team management: `AetheerAI/core/team_manager.py`
- Registry: `AetheerAI/registry/agent_registry.py`
- BaseAgent RBAC + profile: `AetheerAI/agents/base_agent.py`
- Self-healing debugger: `AetheerAI/core/self_healer.py`
- Security audit: `AetheerAI/security/audit_logger.py`
