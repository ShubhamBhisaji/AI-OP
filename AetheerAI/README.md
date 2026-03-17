```
  ___         _   _                     _    ___
 / _ \       | | | |                   / \  |_ _|
/ /_\ \  ___ | |_| |__   ___  ___ _ __/ _ \  | |
|  _  | / _ \| __| '_ \ / _ \/ _ \ '__/ ___ \ | |
| | | ||  __/| |_| | | |  __/  __/ | / /   \_\|___|
\_| |_/ \___| \__|_| |_|\___|\___|_|/_/   (v2.1)
```

<div align="center">

**Autonomous Multi-Agent AI Operating System**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?style=flat-square)](https://fastapi.tiangolo.com)
[![WebSocket](https://img.shields.io/badge/WebSocket-live--streaming-6366f1?style=flat-square)](#real-time-streaming)
[![Multi-User](https://img.shields.io/badge/Auth-API--Key-f43f5e?style=flat-square)](#multi-user--api-key-auth)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Agents](https://img.shields.io/badge/Agents-45%2B_tools-8b5cf6?style=flat-square)](#tools-45)

</div>

---

> **Most AI today is Reactive** — it waits for you.  
> **AetheerAI is Proactive** — it builds systems that work *for* you.  
> It is the difference between a tool you hold in your hand and an engine that runs in the background.

---

## ⚡ Quick Start (3 commands)

```bash
git clone https://github.com/your-org/AetheerAI.git && cd AetheerAI
cp .env.example .env          # add your AI provider key
python start_api.py           # open http://localhost:8000
```

The built-in web UI opens at **`http://localhost:8000`** — no React build, no Node.js required.

---

## What's New in v2.1

| Feature | Details |
|---|---|
| **Real-time streaming** | WebSocket (`/ws/goals/{id}`) + SSE (`/api/goals/{id}/stream`) — live progress in the UI |
| **API-key authentication** | Set `AETHER_API_KEYS=key1,key2` to restrict access; the UI persists your key automatically |
| **State snapshots** | `POST /api/state/save` / `load` — export & restore the full agent roster + memory to JSON |
| **Mobile-responsive UI** | Hamburger sidebar, fluid grid, touch-friendly inputs — works on any screen size |

---

## Table of Contents

1. [What is AetheerAI?](#what-is-aetheerai)
2. [Screenshots & Demo](#screenshots--demo)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [How to Run](#how-to-run)
7. [Usage & Input / Output](#usage--input--output)
8. [Architecture](#architecture)
9. [AI Providers](#ai-providers)
10. [Key Features](#key-features)
11. [Security](#security)
12. [Tools (45+)](#tools-45)
13. [Self-Improvement Loop](#self-improvement-loop)
14. [Project Layout](#project-layout)
15. [Running Tests](#running-tests)
16. [Contributing](#contributing)
17. [License](#license)

---

## What is AetheerAI?

### 1. The "Project Manager" — *for Business Owners*

Imagine you are the CEO of a company. You don't have time to write every email, code every feature, or talk to every customer.

- **The Master (AetheerAI):** This is your **Project Manager**. You tell it the goal (e.g., *"Launch a new product"*).
- **The Sub-Agents:** The Project Manager "hires" a Designer, a Coder, and a Marketer.
- **The Result:** AetheerAI doesn't just "chat" — it **builds the team**, gives them instructions, and makes sure they work together until the job is done.

---

### 2. The "Digital Assembly Line" — *for Engineers*

In the old world (2024), AI was a single craftsman making one thing at a time. In 2026, AetheerAI is the **Factory Owner**.

It builds a **Digital Assembly Line** where:
- one agent grabs raw data,
- another agent cleans it,
- a third agent analyzes it,
- and a fourth agent sends it to your Slack or Gmail.

If one "machine" (agent) breaks, the Master AI **fixes it or replaces it instantly** without stopping the whole line.

---

### 3. The "Smart City" Traffic System — *for Non-Techies*

Think of all your apps (Slack, GitHub, Salesforce, Notion) as **buildings in a city**. AetheerAI is the **Traffic Control Center**.

- It creates **Autonomous Vehicles** (Agents) that know how to navigate between these buildings.
- One agent goes to the "GitHub Building" to get code, drives it to the "Slack Building" to notify the team, and then parks the results in the "Google Drive Building."
- AetheerAI ensures there are **no crashes** and that every agent is on the most efficient route.

---

### 4. The "Orchestra" vs. the "Soloist" — *for Investors*

A standard AI is a **solo pianist** — it can play a great song, but it's just one person.

**AetheerAI is the Conductor.**

- The Conductor doesn't play an instrument; it **leads a Symphony of Agents**.
- The "Strings" (Research Agents), the "Brass" (Execution Agents), and the "Percussion" (Security Agents) all play together in perfect sync to create a complex masterpiece.

| Audience | Best Metaphor |
|---|---|
| Business Owners | The "Project Manager" — focus on delegation |
| Engineers | The "Digital Assembly Line" — focus on workflow |
| Non-Techies | The "Smart City" — focus on movement and apps |
| Investors | The "Orchestra" — focus on the beauty of coordination |

---

## Screenshots & Demo

### Streamlit Dashboard

```
┌─────────────────────────────────────────────────────────────────┐
│  🤖 AetheerAI — Dashboard                          [v2.0]       │
├───────────────────┬─────────────────────────────────────────────┤
│  AGENTS           │  Goal Submission                            │
│  ─────────────    │  ─────────────────────────────────────────  │
│  ✅ ceo_agent     │  Goal: Build a SaaS landing page            │
│  ✅ dev_agent     │  Provider: openai  Model: gpt-4o            │
│  ✅ research_bot  │  Budget cap: $5.00 │ Timeout: 300s          │
│  ✅ marketer      │                                             │
│  ✅ ops_agent     │  [▶  Run Goal]                              │
│                   │                                             │
│  [+ New Agent]    │  Progress ──────────────── 4/5 tasks ✅     │
│  [📋 Teams]       │  ╰─ ResearchAgent  → Done ✅               │
│  [🔧 Tools]       │  ╰─ DeveloperAgent → Done ✅               │
│                   │  ╰─ MarketingAgent → Done ✅               │
│                   │  ╰─ OperationsAgent→ Running ⏳            │
└───────────────────┴─────────────────────────────────────────────┘
```

### CLI Interactive Mode

```
$ python main.py

  █████╗ ███████╗████████╗██╗  ██╗███████╗███████╗██████╗
 ██╔══██╗██╔════╝╚══██╔══╝██║  ██║██╔════╝██╔════╝██╔══██╗
 ███████║█████╗     ██║   ███████║█████╗  █████╗  ██████╔╝
 ██╔══██║██╔══╝     ██║   ██╔══██║██╔══╝  ██╔══╝  ██╔══██╗
 ██║  ██║███████╗   ██║   ██║  ██║███████╗███████╗██║  ██║
 ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝
                    Autonomous AI Operating System  v2.0

Provider: openai  |  Model: gpt-4o  |  Agents: 3 loaded
──────────────────────────────────────────────────────────────
AETHEERAI> orchestrate "build a REST API for user auth"

  [CEO]  Planning goal…  4 tasks created
  [DEV]  Writing auth routes...    ✅  api/auth.py  (0.8 s)
  [DEV]  Writing JWT middleware...  ✅  api/jwt.py   (1.1 s)
  [OPS]  Writing Dockerfile...      ✅  Dockerfile   (0.4 s)
  [CEO]  Delivering summary...      ✅

  ✅  Goal completed — 4/4 tasks (cost: $0.03, 4.2 s)
```

### FastAPI Interactive Docs

```
  http://localhost:8000/docs

  ┌─────────────────────────────────────────────────────────┐
  │  AetheerAI REST API  v2.0  — Interactive Docs           │
  ├─────────────────────────────────────────────────────────┤
  │  POST  /api/goals          Submit a high-level goal     │
  │  GET   /api/goals          List goals + status          │
  │  POST  /api/projects       Run goal via CEO agent       │
  │  GET   /api/projects/{id}  Get results & task breakdown │
  │  POST  /api/agents         Create a custom agent        │
  │  GET   /api/system/status  Runtime health check         │
  └─────────────────────────────────────────────────────────┘
```

### Multi-Agent Pipeline Output

```
$ python examples/build_website.py

  [CEO]       Decomposing goal into 5 tasks…
  [RESEARCH]  Fetching SaaS landing page best practices  ✅  (2.1 s)
  [DEVELOPER] Writing index.html + styles.css            ✅  (3.5 s)
  [MARKETER]  Writing hero copy & CTA text               ✅  (1.2 s)
  [OPS]       Saving files to workspace/                 ✅  (0.1 s)
  [CEO]       Synthesising final report…                 ✅

  ─────────────────────────────────────────────
  ✅  Completed — 5/5 tasks  │  cost $0.07  │  8.2 s
  📁  Output saved to:  workspace/
      ├── index.html
      ├── styles.css
      └── copy.md
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| **Python** | 3.10 + | 3.11+ recommended |
| **pip** | latest | `python -m pip install --upgrade pip` |
| **Docker Desktop** | any recent | Required only for sandboxed `code_runner` tool |
| **Git** | any | For cloning the repo |
| **OS** | Windows 10+, macOS 12+, Ubuntu 20.04+ | Windows one-click launcher included |

**At least one AI provider credential is required** — choose any free option:

| Provider | Cost | How to get |
|---|---|---|
| GitHub Models | **Free** | [github.com/settings/tokens](https://github.com/settings/tokens) — no scopes needed |
| OpenAI | Pay-per-use | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| Anthropic Claude | Pay-per-use | [console.anthropic.com](https://console.anthropic.com) |
| Google Gemini | Free tier | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| Ollama (local) | **Free** | [ollama.com/download](https://ollama.com/download) |

---

## Installation

### Option A — Windows One-Click (Recommended for Windows users)

```bat
:: 1. Clone or download the repository
git clone https://github.com/your-org/AetheerAI.git
cd AetheerAI

:: 2. Double-click or run:
launchers\Start_AetheerAi.bat
```

This script installs dependencies, creates a `.env` interactively, and opens the Streamlit dashboard automatically.

---

### Option B — Manual Installation (All platforms)

**Step 1 — Clone the repository**

```bash
git clone https://github.com/your-org/AetheerAI.git
cd AetheerAI
```

**Step 2 — Create and activate a virtual environment** *(recommended)*

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

**Step 3 — Install Python dependencies**

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Step 4 — Install optional extras** *(pick what you need)*

```bash
# Semantic / RAG memory search (recommended)
pip install chromadb

# Linux only — ChromaDB sqlite3 fix
pip install pysqlite3-binary

# For the Playwright browser tool
playwright install chromium
```

**Step 5 — Copy and edit the environment file**

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Then open `.env` in any text editor and fill in your credentials (see [Configuration](#configuration)).

**Step 6 — Verify the install**

```bash
python main.py --version
# Expected: AetheerAI v2.0  Python 3.x.x
```

---

### Option C — PyInstaller Executable (Windows, no Python required)

```bash
# Build a standalone .exe
python build_pyinstaller.py

# Or use the batch builder:
launchers\build_setup_exe.bat
```

The installer is created in `installer/` and can be distributed to machines without Python.

---

## Configuration

All settings live in a single `.env` file at the project root.

```ini
# .env — minimum required settings

# ── AI Provider ──────────────────────────────────────────────────
AI_PROVIDER=github           # github | openai | anthropic | gemini | ollama
AI_MODEL=gpt-4o              # Model name for the chosen provider

# ── API Keys (set only the one you use) ──────────────────────────
GITHUB_TOKEN=ghp_...         # Free — github.com/settings/tokens (no scopes needed)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
# HUGGINGFACE_API_KEY=hf_...

# ── Budget & Safety Caps ──────────────────────────────────────────
MAX_COST_USD=5.0             # Stop execution if estimated cost exceeds this
MAX_RUNTIME_SECONDS=300      # Hard timeout for any single goal run

# ── Security ─────────────────────────────────────────────────────
AETHER_AUTO_APPROVE=false    # false = require human approval for destructive tools
AETHER_HEADLESS=false        # true = auto-reject all guarded tool calls (for CI)

# ── Offline / Local Mode ──────────────────────────────────────────
# AETHEER_OFFLINE_PROVIDER=ollama
# AETHEER_OFFLINE_MODEL=llama3
```

> **Tip:** You can set API keys interactively at any time from the CLI:
> ```
> AETHEERAI> add_api
> ```

---

## How to Run

AetheerAI has four ways to run — pick the one that fits your workflow:

### 1. Streamlit GUI Dashboard *(beginner-friendly)*

```bash
python launcher.py
# or
streamlit run app.py
```

Opens `http://localhost:8501` in your browser. Best for exploring agents visually.

### 2. CLI Interactive Mode

```bash
python main.py

# Connect to a specific provider at startup:
python main.py --provider github
python main.py --provider openai --model gpt-4o
```

Type `help` at the `AETHEERAI>` prompt to see all available commands.

### 3. FastAPI REST Server

```bash
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
# or
python api/server.py
```

Opens `http://localhost:8000/docs` — interactive Swagger UI for all endpoints.

### 4. Python Script (programmatic)

```python
from core.aetheerai_kernel import AetheerAiKernel
from agents.ceo_agent import CEOAgent

kernel = AetheerAiKernel(ai_provider="openai", model="gpt-4o")
ceo = CEOAgent(kernel, max_cost_usd=5.0, max_runtime_seconds=300)
result = ceo.run("Build a landing page for my SaaS product")
print(result.final_summary)
```

---

## Usage & Input / Output

### Input formats

| Interface | Input type | Example |
|---|---|---|
| CLI | Free-text command | `orchestrate "build a REST API for auth"` |
| Streamlit GUI | Text field in browser | Type your goal and click **Run Goal** |
| REST API | JSON body (POST) | `{"goal": "Write a competitor analysis report"}` |
| Python API | String argument | `ceo.run("Analyse Q1 sales data")` |

### Output formats

| Output | Where it appears | Format |
|---|---|---|
| Agent responses | Terminal / GUI panel | Plain text / Markdown |
| Written files | `workspace/` directory | `.py`, `.html`, `.md`, `.json`, etc. |
| API responses | HTTP JSON | `{"goal_id": "…", "status": "completed", "summary": "…"}` |
| Audit log | `memory/audit_log.jsonl` | Append-only JSONL |
| Task report | Returned object | `result.final_summary`, `result.completed_tasks` |

### CLI command reference

```
Agent management
  create_agent <name> <role>       Create a new agent
  list_agents                      List all registered agents
  agent_info <name>                Show agent details
  upgrade_agent <name>             AI-powered skill upgrade
  open_agent <name>                Open agent in a dedicated terminal window

Multi-agent workflows
  orchestrate "<goal>"             CEO decomposes and runs a full goal
  run_pipeline <team> "<goal>"     Sequential pipeline across a named team
  broadcast "<message>"            Send the same task to all agents
  vote "<question>"                Majority-vote between agents
  best_of "<task>"                 Run N agents, return the best result
  agent_debate <a> <b> "<topic>"   Head-to-head structured debate

AI systems
  create_ai_system                 Wizard designs a full agent roster
  ai_system_task <sys> "<task>"    Run a task on a named system

Provider switching
  switch_ai github                 Switch to GitHub Models (free)
  switch_ai openai gpt-4o          Switch provider + model at runtime
  add_api                          Interactive API key manager

Build & export
  build_application <name>         AI-powered app scaffold
  export_agent <name>              Standalone runnable folder
  export_system <sys> <agents>     Multi-agent bundle with Docker + launchers
```

### REST API — key endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/goals` | Submit a high-level goal |
| `GET`  | `/api/goals/{id}` | Monitor goal end-to-end |
| `GET`  | `/api/goals/{id}/tasks` | Task-level progress |
| `GET`  | `/api/goals/{id}/stream` | **SSE** — live progress stream |
| `WS`   | `/ws/goals/{id}` | **WebSocket** — live progress stream |
| `POST` | `/api/projects` | Submit goal → CEO runs it |
| `GET`  | `/api/projects/{id}` | Results + task breakdown |
| `POST` | `/api/agents` | Create a custom agent |
| `POST` | `/api/collaborations` | Multi-round collaboration session |
| `GET`  | `/api/system/status` | Runtime health check |
| `POST` | `/api/chat` | Direct AI chat (no CEO planning) |
| `GET`  | `/api/health` | Health check |
| `POST` | `/api/state/save` | Save agent + memory snapshot |
| `GET`  | `/api/state/snapshots` | List all saved snapshots |
| `POST` | `/api/state/load?filename=` | Restore agents from a snapshot |

**Example — submit a project via curl:**

```bash
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key-here" \
  -d '{
    "name": "My SaaS Landing Page",
    "goal": "Build a professional landing page for TaskFlow",
    "collaboration_mode": true,
    "background": true
  }'
```

**Example — stream live progress (SSE):**

```bash
curl -N http://localhost:8000/api/goals/<id>/stream
# → data: {"status":"running","progress":{"percent":40},"completed_tasks":2,...}
# → event: done
# → data: {"__done__":true,"status":"completed"}
```

**Example — connect via WebSocket (JavaScript):**

```js
const ws = new WebSocket('ws://localhost:8000/ws/goals/<id>');
ws.onmessage = ({ data }) => {
  const d = JSON.parse(data);
  console.log(d.status, d.progress?.percent + '%');
  if (d.__done__) ws.close();
};
```

**Example response:**

```json
{
  "project_id": "proj_abc123",
  "status": "completed",
  "completed_tasks": 5,
  "total_tasks": 5,
  "cost_usd": 0.07,
  "runtime_seconds": 8.2,
  "summary": "Landing page built and saved to workspace/..."
}
```

---

## Real-time Streaming

AetheerAI v2.1 ships two live-progress transports — choose either or both:

| Transport | Endpoint | Best for |
|---|---|---|
| **SSE** | `GET /api/goals/{id}/stream` | Dashboards, browser `EventSource`, curl |
| **WebSocket** | `ws://host/ws/goals/{id}` | React apps, mobile clients, bidirectional later |

Both emit incremental diffs at ~800 ms intervals and send a terminal `done` event when the goal finishes.  
The built-in web UI automatically connects SSE when you open a running goal's detail panel — look for the red **Live** indicator.

---

## Multi-user & API Key Auth

By default AetheerAI runs in open dev mode (no auth required).  
Set this env var to enforce authentication on all non-public endpoints:

```ini
# .env
AETHER_API_KEYS=sk-aether-prod-abc123,sk-aether-staging-xyz789
```

Clients pass the key as an HTTP header:

```
X-API-Key: sk-aether-prod-abc123
```

The built-in UI stores your key in `localStorage` and injects it automatically.  
In CI / headless mode, the key is passed on every request.

Public routes always available without a key: `/`, `/docs`, `/redoc`, `/api/health`, `/ui/*`.

---

## State Snapshots (Save / Load)

Preserve and restore your entire agent roster + global memory:

```bash
# Save
curl -X POST http://localhost:8000/api/state/save \
  -H "Content-Type: application/json" \
  -d '{"name": "production-v1"}'

# List
curl http://localhost:8000/api/state/snapshots

# Load (restores agents not already registered)
curl -X POST "http://localhost:8000/api/state/load?filename=production-v1_20260317_120000.json"
```

Snapshots are stored as plain JSON in `AetheerAI/memory/snapshots/` — fully auditable and version-controllable.

---

## Docker / Container deployment

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY AetheerAI/ ./AetheerAI/
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV AETHER_HOST=0.0.0.0 AETHER_PORT=8000
EXPOSE 8000
CMD ["python", "AetheerAI/start_api.py"]
```

```bash
docker build -t aetheerai:latest .
docker run -p 8000:8000 \
  -e AI_PROVIDER=openai \
  -e OPENAI_API_KEY=sk-... \
  -e AETHER_API_KEYS=sk-prod-key \
  aetheerai:latest
```

---

## Architecture

```
User / CLI / Web UI / Mobile
    │
    ▼
FastAPI Server  (start_api.py)
    ├── REST endpoints      ← /api/goals, /api/agents, /api/chat, /api/state…
    ├── SSE streaming       ← GET /api/goals/{id}/stream
    ├── WebSocket           ← ws://host/ws/goals/{id}
    └── API Key Middleware  ← X-API-Key header (opt-in via AETHER_API_KEYS)
    │
    ▼
AetheerAiKernel          ← Central boot & orchestration
    ├── AIAdapter         ← Unified LLM interface (litellm)
    ├── WorkflowEngine    ← Task execution, HITL checkpoints, async
    ├── Orchestrator      ← pipeline / broadcast / vote / debate / best-of
    ├── TeamManager       ← Named agent teams
    ├── AgentRegistry     ← Agent CRUD + JSON persistence
    ├── ToolManager       ← 45+ tools, RBAC enforcement
    ├── MemoryManager     ← Namespaced KV store + ChromaDB vector search
    ├── SkillEngine       ← Tiered skill catalogs, AI-driven upgrades
    ├── StateCheckpoint   ← Save / load / time-travel snapshots
    └── Security layer
            ├── PolicyEngine   ← tool authorisation (deny-by-default)
            ├── ApprovalGate   ← HITL gate for destructive/high-risk tools
            └── AuditLogger    ← Append-only JSONL audit trail
```

---

## AI Providers

| Provider | Model examples | Requirements |
|---|---|---|
| **GitHub Models** (free) | `gpt-4o`, `Llama-3-70b` | GitHub account — no billing |
| **OpenAI** | `gpt-4o`, `gpt-4-turbo` | `OPENAI_API_KEY` |
| **Anthropic Claude** | `claude-3-5-sonnet` | `ANTHROPIC_API_KEY` |
| **Google Gemini** | `gemini-1.5-pro` | `GEMINI_API_KEY` |
| **Ollama** (local) | any pulled model | Docker or native |
| **HuggingFace** | Inference API models | `HUGGINGFACE_API_KEY` |

Switch providers at runtime:
```
AETHEERAI> switch_ai github
AETHEERAI> switch_ai openai gpt-4o
```

Set API keys interactively:
```
AETHEERAI> add_api
```

---

## Key Features

### Agent management
```
create_agent ResearchBot "Research Specialist"
list_agents
agent_info ResearchBot
upgrade_agent ResearchBot
open_agent ResearchBot          # dedicated terminal window
```

### Multi-agent workflows
```
create_team myTeam agent1,agent2,agent3
run_pipeline myTeam "analyse Q1 sales data"
broadcast "summarise today's news"
vote "should we use PostgreSQL or MongoDB?"
best_of "write a product description for our SaaS"
agent_debate agent1 agent2 "is Python better than Rust?"
orchestrate "build a REST API for user auth"
```

### AI Systems
```
create_ai_system                         # wizard designs a full agent roster
ai_system_task MySystem "run Q2 report"
```

### Build & export
```
build_application my-app               # AI-powered app scaffold
export_agent ResearchBot               # standalone runnable folder
export_system MyAI agent1,agent2       # multi-agent bundle w/ Docker + launchers
```

---

## Security

- **RBAC levels 0–3** — each agent has a `permission_level`; tools require a minimum level  
- **ApprovalGate** — destructive tools (`file_writer`, `email_tool`) and high-risk tools (`code_runner`, `terminal_tool`, AWS/GCP/K8s) require explicit operator approval  
- **Audit log** — every guarded tool call is written to `memory/audit_log.jsonl` (append-only)  
- **Memory isolation** — agents operate in private namespaces; cannot read each other's memory  
- **Path traversal hardened** — agent names sanitised; all export paths confined to base directory  
- **Docker sandbox** — `code_runner` executes code in an isolated container (network-none, ro-fs, memory capped). Execution is blocked if Docker is unavailable.

---

## Tools (45+)

| Category | Tools |
|---|---|
| Utilities | calculator, datetime, hash, base64, regex, text_analyzer, json, markdown, url, template, diff, system_info |
| Web | web_search, http_client, browser, web_scraper_pro |
| Files | file_reader, file_writer, directory_scanner, local_file, csv, pdf |
| Dev | code_runner *(Docker required)*, terminal, code_analyzer, code_search, linter, formatter, github, playwright |
| AI / Media | vision, image_gen, speech |
| Communication | email, slack_discord |
| Cloud / Infra | aws_gcp, kubernetes, sql_db |
| Multi-agent | agent_ping |

---

## Self-Improvement Loop

1. `EvalRunner` runs benchmark cases against an agent with a configurable timeout  
2. `FailureClustering` groups failures by error type  
3. `SelfImproveCoordinator` proposes patches, optionally gated by a quality threshold  

---

## Project Layout

```
AetheerAI/
├── main.py              CLI entry point
├── app.py               Streamlit dashboard
├── launcher.py          Background launcher + splash
├── agents/              BaseAgent class
├── ai/                  AIAdapter (litellm)
├── cli/                 CommandInterface REPL, AgentWindow, ApiKeyManager
├── core/                Kernel, WorkflowEngine, Orchestrator, Exporter, SelfImprove…
├── evals/               BenchmarkRunner, FailureClustering, QualityGate
├── factory/             AgentFactory (8 presets + custom)
├── memory/              MemoryManager + ChromaDB store
├── registry/            AgentRegistry + registry_store.json
├── security/            ApprovalGate, PolicyEngine, AuditLogger
├── skills/              SkillEngine
├── templates/           Jinja2 export templates
├── tests/               pytest test suite
├── tools/               45+ tool implementations
└── utils/               JSON parser, path resolver
```

---

## Running Tests

```bash
pytest AetheerAI/tests/ -v

# With coverage
pytest AetheerAI/tests/ -v --tb=short --cov=AetheerAI

# Run a specific test file
pytest AetheerAI/tests/test_orchestrator.py -v
```

---

## Contributing

Contributions are welcome! Here is the workflow:

1. **Fork** the repository and create a new branch:
   ```bash
   git checkout -b feature/my-new-agent
   ```

2. **Make your changes** — follow the existing patterns in `agents/` or `tools/`.

3. **Add or update tests** in `tests/` for your changes.

4. **Run the test suite** to make sure nothing is broken:
   ```bash
   pytest AetheerAI/tests/ -v
   ```

5. **Open a Pull Request** with a clear description of what was added or fixed.

### Adding a new specialist agent

```python
# agents/my_agent.py
from agents.base_agent import BaseAgent

class MyAgent(BaseAgent):
    def __init__(self, name, tool_manager, ai_adapter):
        super().__init__(
            name=name,
            role="My Specialist",
            tools=["web_search", "file_writer"],
            permission_level=1,
            tool_manager=tool_manager,
            ai_adapter=ai_adapter,
        )
```

### Adding a new tool

```python
# tools/my_tool.py
from tools.tool_manager import register_tool

@register_tool(name="my_tool", risk="LOW", min_permission=1)
def my_tool(input_text: str) -> str:
    """One-line description of what the tool does."""
    return f"Processed: {input_text}"
```

### Reporting bugs

Open a GitHub Issue with:
- Python version (`python --version`)
- OS and version
- Full error traceback
- Minimal reproduction steps

---

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

---

<div align="center">
Built with Python 3.10+ &nbsp;|&nbsp; Powered by litellm &nbsp;|&nbsp; AetheerAI v2.0
</div>
