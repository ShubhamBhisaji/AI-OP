# External Services Setup Guide

This project includes modular wrappers for:

- Supabase (PostgreSQL, auth, realtime)
- Upstash Redis (queue backend for async jobs)
- Infobip (WhatsApp, email, notifications)
- PayU Money (checkout, verification, payment links)
- Meta Graph API (Facebook Pages, Instagram Business, Messenger)
- Vercel (projects, deployments, serverless env vars)

The wrappers are implemented under `AetheerAI/integrations/` and can be used directly or through a replaceable service factory.

## 1. Required Environment Variables

### Supabase

- `DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY` (optional for frontend use)
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY` (required for admin writes)
- `SUPABASE_SCHEMA` (default: `public`)
- `SUPABASE_TIMEOUT_SECONDS` (default: `20`)
- `SUPABASE_JOBS_TABLE` (default: `ai_jobs`)
- `SUPABASE_JOBS_ID_COLUMN` (default: `id`)

### Upstash Redis (Async Queue)

- `UPSTASH_REDIS_URL` (required, use Redis `rediss://...` URL)
- `UPSTASH_REDIS_QUEUE_NAME` (default: `job_queue`)
- `UPSTASH_REDIS_DLQ_NAME` (default: `job_queue_dlq`)
- `UPSTASH_REDIS_POP_TIMEOUT_SECONDS` (default: `30`)
- `UPSTASH_REDIS_SOCKET_TIMEOUT_SECONDS` (default: `90`)
- `AETHEER_JOB_MAX_RETRIES` (default: `3`)
- `AETHEER_JOB_CLAIM_LEASE_SECONDS` (default: `1800`, distributed execution-claim lease to avoid duplicate multi-worker execution)
- `AETHEER_JOB_RUNNING_TIMEOUT_SECONDS` (default: `1800`)
- `AETHEER_STALE_SCAN_INTERVAL_SECONDS` (default: `30`)
- `AETHEER_STALE_SCAN_BATCH_SIZE` (default: `50`)
- `AETHEER_WORKER_METRICS_LOG_INTERVAL_SECONDS` (default: `30`, periodic queue/throughput telemetry log interval; `0` disables)
- `AETHEER_DISABLE_VERCEL_DIRECT_GOALS` (default: `1`, blocks direct long-running `/api/goals` calls when `VERCEL=1`)
- `AETHEER_WORKER_AUTOSCALE` (default: `1`, enables queue-depth based worker autoscaling)
- `AETHEER_WORKER_MIN_PROCESSES` (default: `1`, minimum worker replicas)
- `AETHEER_WORKER_MAX_PROCESSES` (default: CPU cores capped at `16`, maximum worker replicas)
- `AETHEER_WORKER_TARGET_QUEUE_DEPTH_PER_WORKER` (default: `4`, queue depth target per worker)
- `AETHEER_WORKER_SCALE_INTERVAL_SECONDS` (default: `5.0`, autoscale sampling interval)
- `AETHEER_WORKER_SCALE_DOWN_COOLDOWN_SECONDS` (default: `45.0`, queue-empty cooldown before scale-down)
- `AETHEER_WORKER_PROCESSES` (default: `1`, fixed replicas when autoscaling is disabled)
- `AETHEER_WORKER_MAX_CONCURRENCY` (default: `1`, thread concurrency per worker process)
- `JOB_API_MAX_TASK_PAYLOAD_BYTES` (default: `262144`, max serialized bytes for `task_data` on queue create APIs)
- `JOB_API_MAX_METADATA_BYTES` (default: `65536`, max serialized bytes for `metadata` on queue create APIs)

### Async Job Table Schema (Supabase)

Expected columns for `ai_jobs`:

- `id` text/uuid primary key
- `status` text (`queued`, `running`, `completed`, `failed`)
- `task_type` text
- `task_payload` json/jsonb
- `result` json/jsonb nullable
- `error` text nullable
- `metadata` json/jsonb nullable
- `created_at`, `updated_at`, `started_at`, `completed_at` timestamptz

The worker stores retry/dead-letter lifecycle details in `metadata`, including:

- `retry_count`
- `max_retries`
- `last_failure_reason`
- `dead_lettered`
- `dead_letter_queue`
- `dead_lettered_at`

### Infobip

- `INFOBIP_BASE_URL`
- `INFOBIP_API_KEY`
- `INFOBIP_WHATSAPP_SENDER`
- `INFOBIP_EMAIL_SENDER`
- `INFOBIP_TIMEOUT_SECONDS` (default: `20`)

### PayU Money

- `PAYU_BASE_URL` (test: `https://test.payu.in`, prod: `https://secure.payu.in`)
- `PAYU_MERCHANT_KEY`
- `PAYU_MERCHANT_SALT`
- `PAYU_PAYMENT_PATH` (default: `/_payment`)
- `PAYU_POSTSERVICE_PATH` (default: `/merchant/postservice?form=2`)
- `PAYU_SUCCESS_URL`
- `PAYU_FAILURE_URL`
- `PAYU_TIMEOUT_SECONDS` (default: `20`)

### Meta Graph API

- `META_GRAPH_BASE_URL` (default: `https://graph.facebook.com/v20.0`)
- `META_ACCESS_TOKEN`
- `META_APP_ID`
- `META_APP_SECRET`
- `META_WEBHOOK_VERIFY_TOKEN`
- `META_DEFAULT_PAGE_ID`
- `META_DEFAULT_INSTAGRAM_BUSINESS_ID`
- `META_TIMEOUT_SECONDS` (default: `20`)

Meta webhook callback configuration:

- Callback URL: `https://<your-domain>/api/meta/webhook`
- Verify token: must exactly match `META_WEBHOOK_VERIFY_TOKEN`
- Event delivery: `POST /api/meta/webhook` validates `X-Hub-Signature-256` when `META_APP_SECRET` is set

### Vercel

- `VERCEL_API_BASE_URL` (default: `https://api.vercel.com`)
- `VERCEL_API_TOKEN`
- `VERCEL_TEAM_ID`
- `VERCEL_PROJECT_ID`
- `VERCEL_TIMEOUT_SECONDS` (default: `20`)

## 2. Setup Instructions

1. Install dependencies:

```bash
pip install -r AetheerAI/requirements.txt
```

2. Create your runtime env file:

```bash
copy AetheerAI/.env.example AetheerAI/.env
```

3. Fill your real credentials in `AetheerAI/.env`.

4. Run sample integration usage:

```bash
cd AetheerAI
python examples/external_services_demo.py
```

5. To run live API calls in the demo:

```bash
set RUN_LIVE_EXAMPLES=1
python examples/external_services_demo.py
```

6. Run the persistent queue worker supervisor (for long-running jobs):

```bash
cd AetheerAI
python start_worker.py
```

Force fixed replicas (autoscaling off):

```bash
python start_worker.py --no-autoscale --workers 3
```

Tune autoscaling behavior:

```bash
python start_worker.py --autoscale --min-workers 1 --max-workers 8 --target-queue-depth-per-worker 3
```

Optional one-shot smoke test:

```bash
python workers/upstash_job_worker.py --once
```

## 3. Async Queue API (Vercel)

- `POST /api/queue/jobs`
: Creates a Supabase job row, pushes `{ jobId, taskType, task }` into Redis list `job_queue`, and returns immediately.

- `GET /api/queue/jobs/{job_id}`
: Polls Supabase for the latest status (`queued`, `running`, `completed`, `failed`) and result/error payload.

- `GET /api/queue/metrics` (admin)
: Returns queue depth by lane, DLQ depth, status counts, and stale-running probe count.

Worker reliability behavior:

- On execution failure, jobs are requeued until `AETHEER_JOB_MAX_RETRIES` is exhausted.
- When retries are exhausted, the job is published to `UPSTASH_REDIS_DLQ_NAME` and marked `failed` with dead-letter metadata.
- Running jobs older than `AETHEER_JOB_RUNNING_TIMEOUT_SECONDS` are treated as stale and automatically recovered by retry/DLQ logic.

Example create payload:

```json
{
    "task_type": "goal",
    "task_data": {
        "goal": "Research competitors and draft a launch strategy",
        "context": {"region": "US"},
        "parallel": true,
        "collaboration_mode": true
    },
    "metadata": {
        "source": "vercel-api",
        "requested_by": "user_123"
    }
}
```

## 4. Sample Code

### Direct Clients

```python
from integrations import SupabaseClient, InfobipClient, PayUClient, MetaAPIClient, VercelClient

supabase = SupabaseClient()
rows = supabase.query_rows(table="profiles", limit=5, use_service_role=True)

infobip = InfobipClient()
infobip.send_whatsapp_text(to_number="+15551234567", text="Hello from AetheerAI")

payu = PayUClient()
checkout = payu.build_checkout_payload(
    amount=499.0,
    product_info="AetheerAI Plan",
    first_name="Alex",
    email="alex@example.com",
)

meta = MetaAPIClient()
pages = meta.get_managed_pages()

vercel = VercelClient()
projects = vercel.list_projects(limit=5)
```

### Replaceable/Modular Factory

```python
from integrations import IntegrationFactory

clients = IntegrationFactory().create()

# Access strongly typed clients
clients.supabase.query_rows(table="profiles", limit=5)
clients.infobip.send_notification(channel="email", destination="ops@example.com", message="Done")
```

### Swapping Providers in Tests

```python
class FakeMessagingClient:
    def send_notification(self, *, channel, destination, message, subject=""):
        return {"ok": True, "channel": channel, "destination": destination}

factory = IntegrationFactory(overrides={
    "infobip": FakeMessagingClient,
})
clients = factory.create()
```

## 5. Implementation Map

- `AetheerAI/integrations/base_client.py`
- `AetheerAI/integrations/http.py`
- `AetheerAI/integrations/errors.py`
- `AetheerAI/integrations/supabase_client.py`
- `AetheerAI/integrations/upstash_redis_queue.py`
- `AetheerAI/integrations/config/upstash_redis_config.py`
- `AetheerAI/api/async_jobs.py`
- `AetheerAI/api/queue_router.py`
- `AetheerAI/workers/upstash_job_worker.py`
- `AetheerAI/start_worker.py`
- `AetheerAI/integrations/infobip_client.py`
- `AetheerAI/integrations/payu_client.py`
- `AetheerAI/integrations/meta_api_client.py`
- `AetheerAI/integrations/vercel_client.py`
- `AetheerAI/integrations/service_factory.py`
- `AetheerAI/examples/external_services_demo.py`

## 6. Production Best Practices

- Keep all secrets in runtime env vars only. Do not commit `.env`.
- Rotate any key immediately if exposed in chat, logs, screenshots, or commits.
- Use `SUPABASE_SERVICE_ROLE_KEY` only on trusted backend services.
- Enforce Row Level Security (RLS) in Supabase and least-privilege API scopes for all providers.
- Add network retries with jitter for transient `429` and `5xx` responses.
- Add webhook signature verification for payment and social callbacks.
- Add request id correlation and structured logs for all external API calls.
- Keep separate credentials and projects for dev/staging/prod.
- Store long-lived secrets in a managed secret store (Vercel env vars, cloud secret manager, vault).
- Add synthetic health checks for each external integration path.
