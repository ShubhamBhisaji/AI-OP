-- 202603170003_ai_jobs_operational_indexes.sql
-- Supports fast retention cleanup scans over terminal jobs.

create index if not exists ai_jobs_terminal_completed_at_idx
    on public.ai_jobs (completed_at asc)
    where status in ('completed', 'failed');

comment on index public.ai_jobs_terminal_completed_at_idx is
'Optimizes cleanup of old terminal jobs by completed_at threshold.';
