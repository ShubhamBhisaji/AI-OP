# AetheerAI — How It Actually Works

This is the one-page guide that explains the system clearly.  
No metaphors.  Just the real code path.

---

## The 3 Concepts You Need

| Concept | What It Is | How You Use It |
|---|---|---|
| **Agent** | A named AI worker with a role and tools | `kernel.create_agent(name, role)` |
| **Task** | One piece of work given to one agent | `kernel.run_agent(name, task)` |
| **Team** | A named group of agents that work together | `kernel.create_team(name, [agents])` |

That's it.  Everything else builds on these three.

---

## The Real Code Path

```
Your Code
    │
    ▼
AetheerAiKernel(provider, model)          ← boots everything
    │
    ├── factory.create(name, role)         ← makes an agent from a preset
    │       │
    │       └── AgentRegistry              ← stores & looks up agents
    │
    ├── run_agent(name, task)              ← single agent
    │       │
    │       └── WorkflowEngine.execute()  ← calls AI with agent's system prompt
    │               │
    │               └── AIAdapter.chat()  ← OpenAI / Claude / Gemini / Ollama
    │
    └── orchestrator.run_pipeline()       ← multi-agent: A → B → C (chain)
            orchestrator.broadcast()      ← multi-agent: all get same task
            orchestrator.vote()           ← multi-agent: AI picks consensus
```

---

## Pattern 1 — Single Agent (the minimum)

```python
# Run in: cd AetheerAI && python examples/hello_agent.py

from core.aetheerai_kernel import AetheerAiKernel

kernel = AetheerAiKernel(ai_provider="github", model="gpt-4.1")
kernel.create_agent("researcher", "research_agent")

result = kernel.run_agent("researcher", "What are the top 3 benefits of multi-agent AI?")
print(result)
```

**What happens:**
1. Kernel boots the AI connection
2. `create_agent` makes a ResearchAgent with web_search + file_writer tools
3. `run_agent` sends the task to the AI using the agent's system prompt
4. Returns the AI's text response

---

## Pattern 2 — Pipeline (agents in sequence)

```python
kernel.create_agent("researcher", "research_agent")
kernel.create_agent("writer",     "marketing_agent")
kernel.create_agent("coder",      "coding_agent")

# researcher → writer → coder  (each output feeds the next)
steps = kernel.run_pipeline(
    agent_names=["researcher", "writer", "coder"],
    task="Build a product page for a task manager app",
)

for step in steps:
    print(f"[{step['agent']}] {step['result'][:200]}")
```

**When to use:** When tasks have a natural sequence — research first, then write, then code.

---

## Pattern 3 — Vote / Best-Of (get the best answer)

```python
kernel.create_agent("analyst_1", "research_agent")
kernel.create_agent("analyst_2", "research_agent")
kernel.create_agent("analyst_3", "coding_agent")

# All 3 agents answer; AI picks the best single response
winner = kernel.best_of(
    agent_names=["analyst_1", "analyst_2", "analyst_3"],
    task="Write a Python function to validate an email address",
)
print(winner["best_response"])

# OR: All 3 agents answer; AI synthesises a consensus
consensus = kernel.vote(
    agent_names=["analyst_1", "analyst_2", "analyst_3"],
    question="What is the best database for a real-time chat app?",
)
print(consensus["synthesis"])
```

**When to use:** When accuracy matters more than speed — multiple perspectives, one verdict.

---

## Pattern 4 — Collaborate (real back-and-forth)

```python
kernel.create_agent("dev",       "coding_agent")
kernel.create_agent("researcher","research_agent")
kernel.create_agent("marketer",  "marketing_agent")

session = kernel.collaborate(
    goal="Plan and build a SaaS landing page",
    agent_names=["researcher", "dev", "marketer"],
    rounds=2,          # how many back-and-forth rounds
)

print(session["final_synthesis"])
```

**When to use:** When a goal needs multiple experts iterating together — not just passing output forward.

---

## Pattern 5 — Auto-Orchestrate (let AI decide)

```python
# You don't pick the agents or the mode — the AI figures it out
result = kernel.orchestrate("Analyse our Q3 sales data and write a one-page report")
print(result["result"])
print("Agents used:", result["agents_used"])
print("Mode chosen:", result["mode"])
```

**When to use:** When you're not sure which agents or mode to choose — let the system decide.

---

## The 6 Orchestration Modes

| Mode | What It Does | Best For |
|---|---|---|
| `run_agent` | One agent, one task | Simple tasks |
| `run_pipeline` | A → B → C in sequence | Workflow stages |
| `broadcast` | All agents get the same task | Parallel independence |
| `vote` | All agents answer; AI synthesises consensus | Decisions needing agreement |
| `best_of` | All agents attempt; AI picks the winner | Quality-critical single output |
| `collaborate` | Agents debate & refine together over rounds | Complex goals needing iteration |

---

## Built-In Agent Presets

Pass these as the `role` argument to `create_agent()`:

| Role Name | What It Does | Key Tools |
|---|---|---|
| `research_agent` | Web research, fact-checking, reports | web_search, http_client, file_writer |
| `coding_agent` | Build, review, and refactor code | file_writer, code_runner |
| `marketing_agent` | Copywriting, SEO, campaigns | file_writer, web_search |
| `automation_agent` | Repeat tasks, workflows, scripts | file_writer, code_runner, web_search |
| `ceo_agent` | Decomposes a goal, delegates to others | ping_agent, file_writer |

---

## Entry Points

| File | What It Does | When To Use |
|---|---|---|
| `python main.py` | Interactive CLI chat | Using AetheerAI manually |
| `python start_api.py` | REST API + Web UI at :8000 | Integrating with other systems |
| `python examples/hello_agent.py` | Minimal one-agent example | Learning the API |
| `python examples/build_website.py` | Full multi-agent pipeline demo | Seeing a real workflow |
| `python examples/collaborate_team.py` | Collaboration session demo | Multi-agent teamwork |

---

## File Map (What Each Folder Does)

```
AetheerAI/
├── main.py                 ← CLI entry point
├── start_api.py            ← Web API entry point
├── FLOW.md                 ← This file — how it works
│
├── core/
│   ├── aetheerai_kernel.py ← THE central controller — start here
│   ├── orchestrator.py     ← pipeline / vote / broadcast / best_of / debate
│   ├── workflow_engine.py  ← executes an agent on a task
│   └── team_manager.py     ← creates & stores named teams
│
├── factory/
│   └── agent_factory.py    ← creates agents from role presets
│
├── agents/
│   ├── base_agent.py       ← agent data model
│   ├── research_agent.py   ← built-in Research specialist
│   ├── developer_agent.py  ← built-in Developer specialist
│   ├── marketing_agent.py  ← built-in Marketing specialist
│   └── ceo_agent.py        ← built-in CEO / goal decomposer
│
├── ai/
│   └── ai_adapter.py       ← speaks to OpenAI / Claude / Gemini / Ollama
│
├── tools/                  ← 45+ tools (web_search, file_writer, code_runner …)
├── memory/                 ← per-agent memory (RAM → disk → vector DB)
├── security/               ← RBAC, manifests, audit logging
│
└── examples/
    ├── hello_agent.py      ← start here — 20 lines, one agent
    ├── build_website.py    ← full pipeline demo
    └── collaborate_team.py ← collaboration demo
```

---

## The Kernel's Public Methods at a Glance

```python
kernel = AetheerAiKernel(ai_provider="github", model="gpt-4.1")

# ── Agents ──────────────────────────────────────────────────────────
kernel.create_agent(name, role)              # fast: from preset
kernel.build_agent(name, role, context)      # smart: AI researches the role
kernel.run_agent(name, task)                 # → str
kernel.list_agents()                         # → ["agent1", ...]
kernel.delete_agent(name)

# ── Teams ────────────────────────────────────────────────────────────
kernel.create_team(name, [agent_names])
kernel.list_teams()

# ── Orchestration ────────────────────────────────────────────────────
kernel.run_pipeline(agent_names, task)       # → list[{agent, result}]
kernel.broadcast(agent_names, task)          # → list[{agent, result}]
kernel.vote(agent_names, question)           # → {synthesis, votes}
kernel.best_of(agent_names, task)            # → {best_response, agent}
kernel.agent_debate(agent1, agent2, topic)   # → {transcript, winner}
kernel.orchestrate(task)                     # → {result, agents_used, mode}
kernel.collaborate(goal, agent_names=...)    # → {final_synthesis, turns}

# ── Memory ───────────────────────────────────────────────────────────
kernel.remember(key, value)
kernel.retrieve(key)
```
