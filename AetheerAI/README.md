# AetheerAI — An AI Master!!

An autonomous, multi-agent AI Operating System written in Python 3.10+.  
It manages AI agents the way an OS manages processes — with scheduling, security, memory, tools, and self-improvement built in.

---

## Quick Start

### Windows (one-click)
```
launchers\Start_AetheerAi.bat
```
Opens the Streamlit dashboard in your browser automatically.

### Manual
```bash
pip install -r requirements.txt
python launcher.py          # Streamlit GUI  (recommended)
python main.py              # CLI / headless mode
```

---

## Architecture

```
User / CLI
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

## Requirements

- Python 3.10+  
- Docker Desktop (required for `code_runner` sandboxed execution)  
- See `requirements.txt` for Python dependencies  

### Optional
- `chromadb` — semantic / RAG memory search  
- `pysqlite3-binary` — ChromaDB on Linux with older sqlite3  

---

## Project layout

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
```
