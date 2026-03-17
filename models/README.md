# models/

> **No model download required to run AetheerAI.**
>
> AetheerAI's AI layer is **API-backed**. All inference is handled by cloud or local
> providers through the `AIAdapter` → `ModelRouter` pipeline. Point it at a free
> GitHub PAT and `python main.py` works out of the box — no weights, no GPU, no setup.

---

## How models work in AetheerAI

```
Your goal / prompt
        │
        ▼
  ModelRouter  ─── scores task complexity (SIMPLE / MODERATE / COMPLEX)
        │                 heuristic (free) or AI-scored (~50 tokens)
        ▼
  AIAdapter    ─── litellm-backed, multi-provider abstraction
        │
        ├─► GitHub Models  (free — just needs a GitHub PAT)
        ├─► OpenAI         (gpt-4o, gpt-4o-mini, gpt-4.1 …)
        ├─► Anthropic      (claude-sonnet, claude-haiku …)
        ├─► Google         (gemini-2.5-pro, gemini-flash …)
        └─► Ollama         (llama3, mistral, qwen2.5-coder — fully local / offline)
```

The **ModelOptimizer** tracks real-world latency and success rates per model and
re-ranks the routing table automatically so the fastest, cheapest model that works
is always tried first.

---

## Key source files

| File | Purpose |
|---|---|
| `AetheerAI/ai/ai_adapter.py` | Unified AI provider interface (litellm) |
| `AetheerAI/core/model_router.py` | Task-complexity → model selection |
| `AetheerAI/core/model_optimizer.py` | Perf tracking, persistence, adaptive tuning |
| `AetheerAI/api/predict.py` | REST endpoints — `POST /api/predict`, `POST /api/compare` |
| `models/configs/model_registry.yaml` | Logical model name → provider/model_id map |
| `models/configs/model_config.yaml` | Runtime defaults (temperature, retries, budget caps …) |

---

## This directory layout

```
models/
├── configs/
│   ├── model_config.yaml     ← runtime defaults — edit this to change provider/model
│   └── model_registry.yaml   ← maps logical names to provider + model_id
├── trained/                  ← fine-tuned weight files go here (git-ignored)
└── checkpoints/              ← training checkpoints go here (git-ignored)
```

| Sub-directory  | What goes here                                   | Checked-in to git? |
|----------------|--------------------------------------------------|--------------------|
| `configs/`     | `model_config.yaml`, `model_registry.yaml`       | ✅ Yes             |
| `trained/`     | Fine-tuned `.bin` / `.safetensors` / `.gguf`     | ❌ No (too large)  |
| `checkpoints/` | Epoch snapshots, best-model saves                | ❌ No (too large)  |

---

## Quickest start (no API key, no GPU)

```bash
# 1. Generate a free GitHub PAT at https://github.com/settings/tokens
#    (no scopes needed — click Generate)
# 2. Add it to your .env:
echo "GITHUB_TOKEN=ghp_yourtoken" >> AetheerAI/.env

# 3. Run:
python AetheerAI/main.py --provider github
```

This uses GitHub Models (gpt-4.1 free tier) — zero cost, no billing setup.

---

## Using a local model (fully offline)

[Install Ollama](https://ollama.com), then:

```bash
ollama pull llama3.2:3b       # one-time download (~2 GB)
python AetheerAI/main.py --provider ollama --model llama3.2:3b
```

---

## Storing fine-tuned weights

If you fine-tune a model, place the final weights in `trained/` and register it in
`configs/model_registry.yaml`:

```yaml
- name: my-finetuned-model
  provider: ollama
  model_id: my-finetuned-model
  local: true
  path: models/trained/my-finetuned-model.gguf
```

For files > 100 MB use [Git LFS](https://git-lfs.github.com/) or host on HuggingFace
Hub / S3 and record the download URL under `path:`.
