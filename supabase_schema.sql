-- ACE Audit AI — Supabase schema
-- Run once in the Supabase dashboard: SQL Editor → New query → paste → Run.

create table if not exists public.reports (
    id          bigint generated always as identity primary key,
    created_at  timestamptz not null default now(),
    title       text        not null,
    label1      text,
    label2      text,
    period1     text,
    period2     text,
    currency    text,
    file1_name  text,
    file2_name  text,
    model       text,
    data1       jsonb       not null,
    data2       jsonb       not null,
    metrics     jsonb       not null,
    alerts      jsonb       not null,
    summary     text
);

create index if not exists reports_created_at_idx on public.reports (created_at desc);

-- Lock the table down. The app connects with the service_role key from the Streamlit
-- server, which bypasses RLS; with RLS enabled and no policies, nobody else can read
-- or write these rows — not even someone who finds your anon key.
alter table public.reports enable row level security;
