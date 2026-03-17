# Production Readiness Guide

This document covers the runtime controls, observability endpoints, and configuration
knobs available for running AetheerAI in production environments.

---

## Table of Contents

1. [Concurrency & Load Control](#concurrency--load-control)
2. [Rate Limiting](#rate-limiting)
3. [AI Failover](#ai-failover)
4. [Observability Endpoints](#observability-endpoints)
5. [Response Compression](#response-compression)
6. [Uvicorn Tuning](#uvicorn-tuning)
7. [Environment Variable Reference](#environment-variable-reference)
8. [Docker Health Checks](#docker-health-checks)

---

## Concurrency & Load Control

Every incoming request passes through an `asyncio.Semaphore` that bounds
the number of requests actively being processed. When the semaphore is full,
new requests queue for up to `AETHEER_REQUEST_QUEUE_TIMEOUT_SECONDS` before
receiving a **503 Service Unavailable** response.

| Variable | Default | Description |
|---|---|---|
| `AETHEER_MAX_CONCURRENT_REQUESTS` | `64` | Maximum in-flight requests |
| `AETHEER_REQUEST_QUEUE_TIMEOUT_SECONDS` | `2.0` | Seconds to wait in queue before 503 |

The middleware automatically skips throttling for lightweight paths
(`/api/health`, `/api/ready`, `/api/metrics`, `/api/docs`, `/api/openapi.json`).

---

## Rate Limiting

A per-client sliding-window rate limiter enforces a maximum requests-per-minute ceiling.
The client is identified by `X-API-Key` header (or `"anon"` for unauthenticated callers).
When exceeded, the server returns **429 Too Many Requests** with a `Retry-After` header.

| Variable | Default | Description |
|---|---|---|
| `AETHEER_RATE_LIMIT_RPM` | `0` (disabled) | Max requests per minute per client |

Set to `0` to disable rate limiting entirely (suitable for internal networks).

---

## AI Failover

When the primary AI provider fails repeatedly, the runtime can automatically switch
to a fallback provider/model. The state machine works as follows:

1. Each AI call failure that matches a transient error pattern
   (timeout, connection, rate-limit, 429, 503, gateway, etc.) increments a streak counter.
2. When the streak reaches the **threshold**, a failover activation is triggered.
3. After activation, the AI adapter is reconfigured to use the fallback provider/model.
4. A **cooldown** window prevents repeated activations.
5. A successful AI call resets the failure streak to zero.

| Variable | Default | Description |
|---|---|---|
| `AETHEER_FAILOVER_PROVIDER` | `""` (disabled) | Fallback provider name (e.g. `anthropic`, `openai`) |
| `AETHEER_FAILOVER_MODEL` | `""` | Fallback model name (e.g. `claude-3-5-sonnet`, `gpt-4o`) |
| `AETHEER_FAILOVER_FAILURE_THRESHOLD` | `3` | Consecutive failures before activation |
| `AETHEER_FAILOVER_COOLDOWN_SECONDS` | `30.0` | Seconds to wait before allowing another activation |

Failover is **disabled** when `AETHEER_FAILOVER_PROVIDER` is empty.

---

## Observability Endpoints

### `GET /api/health`

Liveness probe. Returns `200 OK` with instance ID, uptime, load metrics,
and failover state. Cached with a configurable TTL.

### `GET /api/ready`

Deep readiness probe. Checks:
- Database connectivity (SQLAlchemy session)
- Kernel initialization status
- Load saturation (in-flight requests vs. semaphore capacity)

Returns **200** when all subsystems are healthy, **503** when degraded.
Suitable for Kubernetes `readinessProbe` or load-balancer health checks.

### `GET /api/metrics`

Prometheus-compatible text format export. Exposes:
- `aetheer_requests_total` — total processed HTTP requests
- `aetheer_errors_total` — total 5xx responses
- `aetheer_rejected_total` — requests rejected by rate limiter / backpressure
- `aetheer_request_latency_ms_avg` — average request latency
- `aetheer_requests_in_flight` — current concurrent requests
- `aetheer_uptime_seconds` — process uptime
- `aetheer_failover_activations_total` — automatic failover activations
- `aetheer_failover_enabled` — whether failover is configured
- `aetheer_http_responses_total{status="2xx"}` — per-status-class counts

### `GET /api/system/traces`

Returns the most recent request traces (up to `trace_buffer_size`).
Each trace includes: timestamp, request ID, client, method, path, status code,
latency, and error text.

Query parameter: `?limit=N` (default 100)

### `GET /api/system/failover`

Returns the current failover configuration and state: enabled, configured
provider/model, active provider/model, failure streak, threshold, cooldown,
activation history.

### `GET /api/system/status` and `GET /status`

Extended system status including runtime metrics, failover state, model info,
and kernel state. Cached with a configurable TTL.

---

## Response Compression

GZip compression is applied to all responses above a configurable size threshold.

| Variable | Default | Description |
|---|---|---|
| `AETHEER_GZIP_MIN_BYTES` | `1024` | Minimum response size in bytes for gzip |

---

## Uvicorn Tuning

The `start_server()` function (and `start_api.py` CLI) accept tuning parameters:

| Variable | Default | Description |
|---|---|---|
| `AETHER_WORKERS` / `AETHEER_WORKERS` | `1` | Number of uvicorn worker processes |
| `AETHER_LIMIT_CONCURRENCY` | (unset) | Uvicorn `limit_concurrency` override |
| `AETHER_BACKLOG` | `2048` | TCP listen backlog |
| `AETHER_KEEPALIVE_SECONDS` | `30` | HTTP keep-alive timeout |

For multi-core hosts, set `AETHER_WORKERS` to the number of CPU cores.

---

## Environment Variable Reference

All variables support both `AETHEER_` and `AETHER_` prefixes (the `AETHEER_`
variant takes priority when both are set).

| Variable | Type | Default | Min |
|---|---|---|---|
| `AETHEER_MAX_CONCURRENT_REQUESTS` | int | 64 | 1 |
| `AETHEER_REQUEST_QUEUE_TIMEOUT_SECONDS` | float | 2.0 | 0.05 |
| `AETHEER_RATE_LIMIT_RPM` | int | 0 | 0 |
| `AETHEER_TRACE_BUFFER_SIZE` | int | 300 | 25 |
| `AETHEER_FAILOVER_FAILURE_THRESHOLD` | int | 3 | 1 |
| `AETHEER_FAILOVER_COOLDOWN_SECONDS` | float | 30.0 | 1.0 |
| `AETHEER_FAILOVER_PROVIDER` | str | `""` | — |
| `AETHEER_FAILOVER_MODEL` | str | `""` | — |
| `AETHEER_GZIP_MIN_BYTES` | int | 1024 | — |
| `AETHEER_INSTANCE_ID` | str | auto-generated | — |
| `AETHEER_HEALTH_CACHE_TTL_SECONDS` | float | 2.0 | — |
| `AETHEER_STATUS_CACHE_TTL_SECONDS` | float | 5.0 | — |
| `AETHER_WORKERS` / `AETHEER_WORKERS` | int | 1 | 1 |
| `AETHER_LIMIT_CONCURRENCY` | int | (unset) | — |
| `AETHER_BACKLOG` | int | 2048 | — |
| `AETHER_KEEPALIVE_SECONDS` | int | 30 | — |

---

## Docker Health Checks

The Dockerfile and `docker-compose.yml` use `/api/health` as the liveness
probe. For orchestrators like Kubernetes, use `/api/ready` as the
readiness probe to prevent routing traffic to instances that are still
initializing or under heavy load:

```yaml
# Kubernetes example
livenessProbe:
  httpGet:
    path: /api/health
    port: 8000
  initialDelaySeconds: 15
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /api/ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

For Docker Compose, the existing healthcheck targets `/api/health`, which is
sufficient for single-node deployments.
