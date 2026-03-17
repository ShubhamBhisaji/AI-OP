# Vercel Env Setup (Production + Preview)

This file provides copy-paste PowerShell commands to set the async queue env vars
for the Vercel API gateway.

## 1) Prerequisites

1. Install and login:

~~~powershell
npm i -g vercel
vercel login
~~~

2. Link this repo to your Vercel project from the repo root:

~~~powershell
vercel link
~~~

## 2) Fill Values Once

Replace placeholder values before running the command blocks.

~~~powershell
$VALUES = @{
  LOG_LEVEL = "info"
  JWT_SECRET = "replace-with-long-random-secret"
  CORS_ORIGINS = "https://your-ui-domain.com"
  AETHER_API_KEYS = "reader:replace-reader,writer:replace-writer,admin:replace-admin"

  UPSTASH_REDIS_URL = "rediss://default:replace-password@replace-host:6379"
  UPSTASH_REDIS_QUEUE_NAME = "job_queue"
  UPSTASH_REDIS_SOCKET_TIMEOUT_SECONDS = "90"

  SUPABASE_URL = "https://replace-project-ref.supabase.co"
  SUPABASE_ANON_KEY = "replace-anon-key"
  SUPABASE_SERVICE_ROLE_KEY = "replace-service-role-key"
  SUPABASE_SCHEMA = "public"
  SUPABASE_TIMEOUT_SECONDS = "20"
  SUPABASE_JOBS_TABLE = "ai_jobs"
  SUPABASE_JOBS_ID_COLUMN = "id"

  AETHEER_DISABLE_VERCEL_DIRECT_GOALS = "1"
}
~~~

## 3) Set Production Vars

~~~powershell
$VALUES.GetEnumerator() | ForEach-Object {
  $_.Value | vercel env add $_.Key production
}
~~~

## 4) Set Preview Vars

~~~powershell
$VALUES.GetEnumerator() | ForEach-Object {
  $_.Value | vercel env add $_.Key preview
}
~~~

## 5) Verify

~~~powershell
vercel env ls
~~~

## 6) Deploy

~~~powershell
vercel --prod
~~~

## Optional: Update Existing Vars

If a var already exists, remove then re-add.

~~~powershell
vercel env rm SUPABASE_SERVICE_ROLE_KEY production
$VALUES.SUPABASE_SERVICE_ROLE_KEY | vercel env add SUPABASE_SERVICE_ROLE_KEY production
~~~
