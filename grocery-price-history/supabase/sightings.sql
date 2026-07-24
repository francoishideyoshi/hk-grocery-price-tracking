-- Run once in the Supabase SQL editor for this project.
-- Crowd-sourced price sightings: users report where they found a lower
-- price in person; other users vote on and can report bad/spam entries.

create table public.sightings (
  id uuid primary key default gen_random_uuid(),
  product_code text not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  shop_name text not null,
  price numeric(10,2) not null check (price >= 0),
  district text not null,
  note text,
  created_at timestamptz not null default now()
);

create table public.sighting_votes (
  sighting_id uuid not null references public.sightings(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  vote smallint not null check (vote in (-1, 1)),
  created_at timestamptz not null default now(),
  primary key (sighting_id, user_id)
);

create table public.sighting_reports (
  sighting_id uuid not null references public.sightings(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (sighting_id, user_id)
);

alter table public.sightings enable row level security;
alter table public.sighting_votes enable row level security;
alter table public.sighting_reports enable row level security;

-- Anyone (including signed-out visitors) may read sightings; only the
-- reporting user may insert/delete their own.
create policy "sightings_select_public" on public.sightings
  for select using (true);

create policy "sightings_insert_own" on public.sightings
  for insert with check (auth.uid() = user_id);

create policy "sightings_delete_own" on public.sightings
  for delete using (auth.uid() = user_id);

create policy "sighting_votes_select_public" on public.sighting_votes
  for select using (true);

create policy "sighting_votes_insert_own" on public.sighting_votes
  for insert with check (auth.uid() = user_id);

create policy "sighting_votes_update_own" on public.sighting_votes
  for update using (auth.uid() = user_id);

create policy "sighting_votes_delete_own" on public.sighting_votes
  for delete using (auth.uid() = user_id);

create policy "sighting_reports_select_public" on public.sighting_reports
  for select using (true);

create policy "sighting_reports_insert_own" on public.sighting_reports
  for insert with check (auth.uid() = user_id);

create policy "sighting_reports_delete_own" on public.sighting_reports
  for delete using (auth.uid() = user_id);

-- security_invoker makes the view respect the querying user's RLS policies
-- (Postgres 15+ / Supabase), instead of running as the view owner.
create view public.sightings_public
with (security_invoker = on) as
select
  s.id, s.product_code, s.shop_name, s.price, s.district, s.note, s.created_at,
  coalesce(sum(v.vote), 0)::int as score,
  count(distinct r.user_id)::int as report_count
from public.sightings s
left join public.sighting_votes v on v.sighting_id = s.id
left join public.sighting_reports r on r.sighting_id = s.id
group by s.id;

grant select on public.sightings_public to anon, authenticated;

-- ponytail: auto-hide at report_count>=3 is brigade-abusable (3 sockpuppets
-- can silence a legit sighting) — upgrade to admin moderation if it matters.
