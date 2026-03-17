-- 202603170002_ai_jobs_reliability_indexes.sql
-- Supports stale-running timeout scans and queue recovery lookups.

create index if not exists ai_jobs_status_started_at_idx
    on public.ai_jobs (status, started_at asc);

comment on index public.ai_jobs_status_started_at_idx is
'Optimizes worker stale-running timeout detection (status=running and started_at threshold).';
