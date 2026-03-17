-- 202603170001_create_ai_jobs.sql
-- Async jobs table for Upstash queue + worker execution lifecycle.

create table if not exists public.ai_jobs (
    id uuid primary key,
    status text not null default 'queued'
        check (status in ('queued', 'running', 'completed', 'failed')),
    task_type text not null,
    task_payload jsonb not null default '{}'::jsonb,
    result jsonb,
    error text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    started_at timestamptz,
    completed_at timestamptz
);

create index if not exists ai_jobs_status_created_at_idx
    on public.ai_jobs (status, created_at desc);

create index if not exists ai_jobs_updated_at_idx
    on public.ai_jobs (updated_at desc);

create index if not exists ai_jobs_task_type_idx
    on public.ai_jobs (task_type);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_ai_jobs_set_updated_at on public.ai_jobs;
create trigger trg_ai_jobs_set_updated_at
before update on public.ai_jobs
for each row execute function public.set_updated_at();

comment on table public.ai_jobs is
'Queue-backed async AI jobs: queued -> running -> completed/failed.';
