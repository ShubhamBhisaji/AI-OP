-- 202603180001_ai_jobs_dlq_and_tenant_indexes.sql
-- Improves DLQ analysis and tenant-scoped job listing performance.

create index if not exists ai_jobs_failed_dead_lettered_completed_at_idx
    on public.ai_jobs (completed_at desc)
    where status = 'failed'
      and coalesce((metadata->>'dead_lettered')::boolean, false);

comment on index public.ai_jobs_failed_dead_lettered_completed_at_idx is
'Optimizes admin dead-letter queries over failed jobs by completed_at.';

create index if not exists ai_jobs_owner_status_created_at_idx
    on public.ai_jobs (((metadata->>'owner_user_id')), status, created_at desc)
    where metadata ? 'owner_user_id';

comment on index public.ai_jobs_owner_status_created_at_idx is
'Optimizes tenant-scoped job polling and status listings using owner metadata.';
