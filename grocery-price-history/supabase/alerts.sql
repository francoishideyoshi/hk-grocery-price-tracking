-- Run in the Supabase SQL editor for this project. Re-runnable: every
-- statement is idempotent, so it is safe to re-run after an update.
-- Email-alert prefs: one row per user, an opt-out flag. Absence of a row
-- means "alerts on", so the recipients view below coalesces to the default.

create table if not exists public.alert_prefs (
  user_id uuid not null primary key references auth.users(id) on delete cascade,
  email_enabled boolean not null default true,
  updated_at timestamptz not null default now()
);

alter table public.alert_prefs enable row level security;

-- Authenticated users may only read/write their own row.
drop policy if exists "alert_prefs_select_own" on public.alert_prefs;
create policy "alert_prefs_select_own" on public.alert_prefs
  for select using (auth.uid() = user_id);

drop policy if exists "alert_prefs_insert_own" on public.alert_prefs;
create policy "alert_prefs_insert_own" on public.alert_prefs
  for insert with check (auth.uid() = user_id);

drop policy if exists "alert_prefs_update_own" on public.alert_prefs;
create policy "alert_prefs_update_own" on public.alert_prefs
  for update using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Who to email: every watchlist row joined to the user's email and alert
-- prefs. Users with no alert_prefs row are still included (default on);
-- users who never confirmed their email are excluded.
create or replace view public.alert_recipients as
select w.user_id, u.email, w.product_code
from public.watchlist w
join auth.users u on u.id = w.user_id
left join public.alert_prefs p on p.user_id = w.user_id
where coalesce(p.email_enabled, true) and u.email is not null
  and u.email_confirmed_at is not null;

-- CRITICAL: this view exposes user email addresses. It deliberately does NOT
-- use security_invoker — it must run with owner rights to read auth.users,
-- which anon/authenticated can never hold. So revoke it from every client
-- role and grant select only to service_role: the CI alert job's service-role
-- key is the sole reader.
revoke all on public.alert_recipients from anon, authenticated;
grant select on public.alert_recipients to service_role;