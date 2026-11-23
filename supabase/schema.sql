-- Optional Supabase mirror for Exam Monitor Ultimate (V7).
-- The application talks to Supabase ONLY from the backend with the service-role key (which bypasses RLS).
-- Row Level Security is enabled and NO policy is created for anon / authenticated users, so the public (anon) key can
-- neither read nor write anything. The mirror is a backup, never a public API (no bulk export of student data).
create table if not exists public.live_allotments (
    id bigint generated always as identity primary key,
    register_number text not null,
    exam_date date not null,
    session text not null check (session in ('FN', 'AN')),
    subject_code text not null default '',
    subject_name text,
    programme text,
    department text,
    hall text,
    seat text,
    status text not null,
    flags text,
    hall_page integer,
    seat_page integer,
    hall_source_url text,
    seat_source_url text,
    fingerprint text not null,
    revision integer not null default 1,
    is_current boolean not null default true,
    first_seen_at timestamptz,
    last_verified_at timestamptz,
    unique (register_number, exam_date, session, subject_code, fingerprint)
);
create index if not exists live_allotments_reg_idx on public.live_allotments (register_number, is_current);

alter table public.live_allotments enable row level security;
alter table public.live_allotments force row level security;
revoke all on public.live_allotments from anon, authenticated;
-- (intentionally no "create policy" statements)
