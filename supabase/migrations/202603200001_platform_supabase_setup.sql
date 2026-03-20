-- 202603200001_platform_supabase_setup.sql
-- Platform bootstrap schema for AetheerAI Supabase.

create table if not exists public.aetheer_customer_supabase_configs (
    id bigserial primary key,
    user_id bigint not null unique,
    username text,
    customer_supabase_url text not null,
    customer_supabase_anon_key text not null,
    customer_supabase_service_role_key text,
    customer_supabase_schema text not null default 'public',
    setup_completed boolean not null default true,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.aetheer_user_account_logs (
    id bigserial primary key,
    user_id bigint not null,
    username text,
    event_type text not null,
    action text not null,
    status text not null default 'ok',
    provider text,
    model text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.aetheer_user_token_usage (
    id bigserial primary key,
    user_id bigint not null,
    username text,
    provider text not null,
    model text not null default '',
    prompt_tokens bigint not null default 0,
    completion_tokens bigint not null default 0,
    total_tokens bigint not null default 0,
    last_event_at timestamptz not null default timezone('utc', now()),
    unique (user_id, provider, model)
);

create table if not exists public.aetheer_user_agent_profiles (
    id bigserial primary key,
    user_id bigint not null,
    username text,
    agent_name text not null,
    role text,
    source text not null default 'manual',
    tools jsonb not null default '[]'::jsonb,
    skills jsonb not null default '[]'::jsonb,
    objectives jsonb not null default '[]'::jsonb,
    permission_level integer,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    unique (user_id, agent_name)
);

create index if not exists idx_aetheer_customer_supabase_configs_user_id
    on public.aetheer_customer_supabase_configs (user_id);

create index if not exists idx_aetheer_user_account_logs_user_id
    on public.aetheer_user_account_logs (user_id);

create index if not exists idx_aetheer_user_account_logs_event_type
    on public.aetheer_user_account_logs (event_type);

create index if not exists idx_aetheer_user_account_logs_created_at
    on public.aetheer_user_account_logs (created_at desc);

create index if not exists idx_aetheer_user_token_usage_user_id
    on public.aetheer_user_token_usage (user_id);

create index if not exists idx_aetheer_user_token_usage_provider
    on public.aetheer_user_token_usage (provider);

create index if not exists idx_aetheer_user_agent_profiles_user_id
    on public.aetheer_user_agent_profiles (user_id);

create index if not exists idx_aetheer_user_agent_profiles_agent_name
    on public.aetheer_user_agent_profiles (agent_name);
