# AETHER OS — Autonomous Multi-Agent AI Operating System

> **AetheerAI — An AI Master!!**  
> A production-ready platform where a CEO Agent decomposes any high-level goal into tasks,  
> routes them to specialist agents, monitors execution, and delivers results.

---

## Architecture

```
User Goal
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                     CEO AGENT                           │
│  Plan → Assign → Execute → Monitor → Replan → Deliver  │
└────────────────────────┬────────────────────────────────┘
                         │  dispatches tasks to
          ┌──────────────┼──────────────────────────────┐
          ▼              ▼              ▼                ▼             ▼
    DeveloperAgent  ResearchAgent  MarketingAgent  OperationsAgent  SupportAgent
    (writes code)   (web research)  (campaigns)    (automation)     (Q&A)
          │              │              │                │
          └──────────────┴──────────────┴────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │    Tool Layer        │
              │  file_writer         │
              │  web_search          │
              │  code_runner         │
              │  terminal_tool       │
              │  http_client  ...    │
              └──────────┬───────────┘
                         │
              ┌──────────▼───────────┐
              │   Security Layer     │
              │  ApprovalGate        │
              │  PolicyEngine (RBAC) │
              │  ManifestGuard       │
              │  AuditLogger         │
              └──────────┬───────────┘
                         │
              ┌──────────▼───────────┐
              │   Memory System      │
              │  MemoryManager       │
              │  TieredMemoryManager │
              │  ChromaDB (vector)   │
              └──────────────────────┘
```

---

## Folder Structure

```
AetheerAI/
├── agents/
│   ├── base_agent.py          # Foundation class for all agents (RBAC profiles)
│   ├── ceo_agent.py           # ★ CEO: plan → assign → execute → monitor → deliver
│   ├── developer_agent.py     # ★ Writes/debugs code, runs linter
│   ├── research_agent.py      # ★ Web search, fact-checking, reports
│   ├── marketing_agent.py     # ★ Content, SEO, campaigns
│   ├── operations_agent.py    # ★ Automation, APIs, terminal, data
│   └── support_agent.py       # ★ Q&A, troubleshooting, knowledge base
│
├── api/
│   ├── __init__.py
│   └── server.py              # ★ FastAPI backend (all REST endpoints)
│
├── core/
│   ├── aetheerai_kernel.py    # Central kernel — boots all subsystems
│   ├── orchestrator.py        # Multi-agent coordination (pipeline/vote/debate…)
│   ├── workflow_engine.py     # Task execution with self-correction + HITL
│   ├── team_manager.py        # Named teams of agents
│   ├── model_router.py        # Auto-routes tasks to cheapest capable model
│   ├── self_healer.py         # Automatically debugs failed tasks
│   └── …                      # 20+ other subsystem modules
│
├── factory/
│   └── agent_factory.py       # Dynamically creates agents from presets or config
│
├── memory/
│   ├── memory_manager.py      # Key-value + ChromaDB vector store
│   └── tiered_memory.py       # Short/long/archival three-tier memory
│
├── security/
│   ├── approval_gate.py       # Human approval before destructive tool calls
│   ├── policy_engine.py       # RBAC — permission levels 0–5
│   ├── audit_logger.py        # Append-only JSONL audit log
│   └── intent_manifest.py     # Per-agent tool allow/deny manifests
│
├── tools/                     # 40+ plug-in tools (file, web, code, DB, cloud…)
│   └── tool_manager.py        # Tool registry + RBAC enforcement
│
├── examples/
│   └── build_website.py       # ★ "Build a simple website" demo workflow
│
├── app.py                     # Streamlit GUI dashboard
├── main.py                    # CLI interactive mode
└── requirements.txt           # Python dependencies
```

★ = New files added by this build

---

## Core Features

### 1. CEO Agent (`agents/ceo_agent.py`)

The central orchestrating agent:

```python
from core.aetheerai_kernel import AetheerAiKernel
from agents.ceo_agent import CEOAgent

kernel = AetheerAiKernel(ai_provider="openai", model="gpt-4o")
ceo = CEOAgent(kernel, max_tasks=20, max_cost_usd=5.0, max_runtime_seconds=300)

result = ceo.run("Build a simple SaaS landing page for TaskFlow")

print(result.final_summary)
print(f"{result.completed_tasks}/{result.total_tasks} tasks completed")
```

**What it does:**
1. **PLAN** — Calls LLM to produce a JSON task list with agent assignments
2. **ASSIGN** — Looks up or creates the right specialist agent per task
3. **EXECUTE** — Runs tasks in dependency order (respects `depends_on`)
4. **MONITOR** — Tracks status; re-plans tasks that fail
5. **DELIVER** — Synthesises a final professional summary

---

### 2. Specialist Agents

| Agent | Class | Default Permission | Typical Tools |
|---|---|---|---|
| Developer | `DeveloperAgent` | ELEVATED (2) | file_writer, code_runner, linter |
| Researcher | `ResearchAgent` | STANDARD (1) | web_search, web_scraper_pro |
| Marketer | `MarketingAgent` | STANDARD (1) | file_writer, markdown_tool |
| Operations | `OperationsAgent` | ADMIN (3) | terminal_tool, http_client, csv_tool |
| Support | `SupportAgent` | STANDARD (1) | web_search, note_taker |

Each agent has a specialised system prompt and convenience helper methods:

```python
from agents.developer_agent import DeveloperAgent

dev = DeveloperAgent("my_dev", tool_manager=kernel.tool_manager, ai_adapter=kernel.ai_adapter)
dev.write_file("hello.py", "print('Hello from AETHER!')")
dev.lint("hello.py")
```

---

### 3. Memory System

```python
# Short-term (in-session)
kernel.memory.set("key", {"data": 123})
kernel.memory.get("key")

# Scoped per agent
scoped = kernel.memory.scoped("my_agent")
scoped.set("last_task", "research competitor pricing")

# Long-term semantic search (requires chromadb)
kernel.memory.store("project_knowledge", "TaskFlow targets remote teams...")
results = kernel.memory.semantic_search("remote teams project management")
```

---

### 4. Human Control Layer

Three levels of control:

```python
# 1. Pre-task HITL callback passed to ceo.run()
from core.workflow_engine import WorkflowFeedback, HITLAction

def my_approval(checkpoint):
    print(f"Agent '{checkpoint.agent_name}' wants to run:\n{checkpoint.task}")
    choice = input("Approve? [y/n/r] ").strip().lower()
    if choice == "n": return WorkflowFeedback(action=HITLAction.CANCEL)
    if choice == "r":
        revised = input("Revised task: ")
        return WorkflowFeedback(action=HITLAction.REVISE, revised_task=revised)
    return WorkflowFeedback(action=HITLAction.APPROVE)

result = ceo.run(goal, hitl_callback=my_approval)

# 2. Per-tool ApprovalGate (automatic for DESTRUCTIVE/HIGH_RISK tools)
# Set AETHER_AUTO_APPROVE=false in .env (default) to require confirmation
# Set AETHER_HEADLESS=true in CI to auto-reject risky calls

# 3. Budget / time caps on CEOAgent constructor
ceo = CEOAgent(kernel, max_cost_usd=2.0, max_runtime_seconds=120)
```

---

### 5. FastAPI REST API (`api/server.py`)

```bash
# Start the API server
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

# Or directly
python api/server.py
```

Interactive docs: http://localhost:8000/docs

**Key endpoints:**

| Method | URL | Description |
|---|---|---|
| `POST` | `/api/projects` | Submit a goal → CEO runs it |
| `GET`  | `/api/projects` | List all projects |
| `GET`  | `/api/projects/{id}` | Get results + task breakdown |
| `POST` | `/api/agents` | Create a custom agent |
| `GET`  | `/api/agents` | List registered agents |
| `POST` | `/api/agents/{name}/run` | Run one task on an agent directly |
| `POST` | `/api/chat` | Direct AI assistant (no CEO planning) |
| `GET`  | `/api/health` | Health check |

**Example — submit a project via curl:**

```bash
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My SaaS Landing Page",
    "goal": "Build a professional landing page for TaskFlow, a project management app",
    "background": false
  }'
```

---

## Example: "Build a Simple Website" Workflow

```bash
# Run the bundled example
python examples/build_website.py
```

The CEO agent will:
1. Research SaaS landing page best practices (ResearchAgent)
2. Write a full HTML/CSS/JS landing page (DeveloperAgent)
3. Write conversion-optimised marketing copy (MarketingAgent)
4. Save files to `workspace/` (OperationsAgent)
5. Deliver a consolidated summary

---

## Running Locally

### 1. Prerequisites

```bash
# Python 3.11+ recommended
python --version
```

### 2. Install dependencies

```bash
cd AetheerAI
pip install -r requirements.txt

# For the FastAPI server, also install:
pip install fastapi uvicorn
```

### 3. Configure environment

```bash
cp .env.example .env   # create from template (if .env doesn't exist)
# Edit .env — set your API key:
```

```ini
# .env
AI_PROVIDER=openai        # or: github | anthropic | gemini | ollama
AI_MODEL=gpt-4o
OPENAI_API_KEY=sk-...

# Budget caps
MAX_COST_USD=5.0
MAX_RUNTIME_SECONDS=300
```

**Free option — GitHub Models (no paid key needed):**
```ini
AI_PROVIDER=github
AI_MODEL=gpt-4.1
GITHUB_TOKEN=ghp_...     # github.com/settings/tokens — no scopes needed
```

### 4. Start the API server

```bash
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
# → Open http://localhost:8000/docs for interactive API docs
```

### 5. Start the Streamlit GUI

```bash
streamlit run app.py
```

### 6. Run the CLI

```bash
python main.py
python main.py --provider github
```

### 7. Run the website example

```bash
python examples/build_website.py
```

---

## Security Model

| Layer | Mechanism |
|---|---|
| Agent permissions | RBAC levels 0–3 (GUEST → ADMIN) via `PolicyEngine` |
| Dangerous tools | `ApprovalGate` requires human confirmation before `file_writer`, `code_runner`, `terminal_tool`, etc. |
| Prompt injection | Pipeline sanitizer strips injected directives between agent steps |
| Audit trail | Every tool call logged to `memory/audit_log.jsonl` |
| Budget limits | `max_cost_usd` + `max_runtime_seconds` on every project |
| Headless CI | `AETHER_HEADLESS=true` auto-rejects all guarded tool calls |

---

## Adding New Agents

```python
# Option A — from preset
agent = kernel.factory.create("research_agent")

# Option B — fully custom
from agents.base_agent import BaseAgent
agent = BaseAgent(
    name="legal_agent",
    role="Legal Research Agent",
    tools=["web_search", "file_writer"],
    skills=["contract_review", "regulatory_compliance"],
    permission_level=1,
)
kernel.registry.register(agent)
```

---

## Adding New Tools

```python
# tools/my_custom_tool.py
def my_custom_tool(query: str) -> str:
    """Does something useful."""
    return f"Result for: {query}"

# Register in ToolManager
kernel.tool_manager.register("my_custom_tool", my_custom_tool)
# Add permission in TOOL_PERMISSIONS dict in tool_manager.py
```

---

## Deployment

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY AetheerAI/ .
RUN pip install --no-cache-dir -r requirements.txt fastapi uvicorn
EXPOSE 8000
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t aether-os .
docker run -p 8000:8000 --env-file AetheerAI/.env aether-os
```

### Environment variables for production

```ini
AETHER_HEADLESS=true          # auto-reject risky ops in CI
AETHER_AUTO_APPROVE=false     # never auto-approve in production
SECRET_KEY=<random-32-chars>
LOG_LEVEL=WARNING
MAX_COST_USD=20.0
```
