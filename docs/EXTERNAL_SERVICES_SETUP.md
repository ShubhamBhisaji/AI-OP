# External Services Setup Guide

This project includes modular wrappers for:

- Supabase (PostgreSQL, auth, realtime)
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

## 3. Sample Code

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

## 4. Implementation Map

- `AetheerAI/integrations/base_client.py`
- `AetheerAI/integrations/http.py`
- `AetheerAI/integrations/errors.py`
- `AetheerAI/integrations/supabase_client.py`
- `AetheerAI/integrations/infobip_client.py`
- `AetheerAI/integrations/payu_client.py`
- `AetheerAI/integrations/meta_api_client.py`
- `AetheerAI/integrations/vercel_client.py`
- `AetheerAI/integrations/service_factory.py`
- `AetheerAI/examples/external_services_demo.py`

## 5. Production Best Practices

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
