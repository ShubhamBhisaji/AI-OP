# Observability Stack

This project includes a self-hosted observability profile with operational evidence for:

- Metrics collection (runtime + queue)
- Queue monitoring (depth, DLQ, stale jobs, latency)
- Performance dashboards (Grafana, auto-provisioned)
- Alerting system (runtime webhook + Prometheus alert rules)

## Start

From the workspace root:

```bash
docker compose --profile observability up -d --build
```

Services:

- API: http://localhost:8000
- Prometheus: http://localhost:9090
- Loki: http://localhost:3100
- Grafana: http://localhost:3001

Grafana credentials:

- GRAFANA_ADMIN_USER (default: admin)
- GRAFANA_ADMIN_PASSWORD (default: admin)

## Metrics Collection

Prometheus scrapes `GET /api/metrics` and now receives:

- Runtime HTTP metrics (`aetheer_requests_total`, `aetheer_error_rate_pct`, latency, failover)
- Queue metrics (`aetheer_queue_depth_total`, `aetheer_queue_depth`, `aetheer_queue_dlq_depth`, stale-running, queue latency)

Quick verification:

```bash
curl -s http://localhost:8000/api/metrics | grep -E "aetheer_(requests_total|queue_depth_total|queue_dlq_depth|queue_wait_ms_p95)"
```

## Queue Monitoring

Queue health is exposed through two interfaces:

- Prometheus series from `/api/metrics`
- API payloads:
  - `GET /api/system/status` (includes `queue_monitoring`)
  - `GET /api/system/observability` (includes `queue_metrics`)
  - `GET /api/queue/metrics` (admin route with full queue metrics response)

Queue monitoring coverage includes:

- Per-lane depth (`high`, `normal`, `low`)
- DLQ depth
- Job store status counts (`queued`, `running`, `completed`, `failed`)
- Stale-running jobs above timeout
- Queue wait and execution latency (avg + p95)

## Dashboards

Grafana dashboards are provisioned automatically from:

- `ops/observability/grafana/provisioning/dashboards/dashboards.yml`
- `ops/observability/grafana/dashboards/aetheer-runtime-queue.json`

Default dashboard:

- **AetheerAI Runtime and Queue**

This dashboard includes:

- Request rate, error rate, and API p95 latency
- Queue depth by lane and total depth
- DLQ depth and stale-running trend
- Queue wait/execution p95 latency
- Live logs from Loki

## Alerting System

Two alerting paths are available:

1. Runtime webhook alerts from the API process
	- Configure `AETHEER_ALERT_WEBHOOK_URL`
	- Triggered from runtime thresholds (error rate, p95 latency, saturation)

2. Prometheus rule-based alerts
	- Rule file: `ops/observability/alerts.yml`
	- Loaded by `ops/observability/prometheus.yml`
	- Includes API and queue alerts (error rate, p95 latency, queue backlog, DLQ, stale-running, queue metric scrape failure)

Quick verification:

```bash
curl -s http://localhost:9090/api/v1/rules | grep -E "Aetheer(Api|Queue)"
curl -s http://localhost:9090/api/v1/alerts | jq
```

## Notes

- `LOG_JSON` defaults to `1` for API and worker so logs are structured.
- To run app services without observability profile: `docker compose up -d`.
- To stop and remove observability profile:

```bash
docker compose --profile observability down
```
