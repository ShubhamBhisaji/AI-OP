# Observability Stack

This project now includes an optional, self-hosted observability profile with:

- Prometheus for metrics scraping
- Loki for centralized log storage
- Promtail for log shipping
- Grafana for dashboards and log exploration

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

Grafana credentials are controlled by:

- GRAFANA_ADMIN_USER (default: admin)
- GRAFANA_ADMIN_PASSWORD (default: admin)

## What is collected

- Metrics scraped from /api/metrics (Prometheus format)
- Rotated app logs from shared volume /app/logs via Promtail

## Notes

- LOG_JSON defaults to 1 in docker-compose for API and worker so logs are structured.
- To run only app services without observability profile, use docker compose up -d.
- To stop and remove all services:

```bash
docker compose --profile observability down
```
