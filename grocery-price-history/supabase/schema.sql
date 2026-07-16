-- Run once in the Supabase SQL editor for this project.
-- Stores which product codes each signed-in user is tracking.

create table public.watchlist (
  user_id uuid not null references auth.users(id) on delete cascade,
  product_code text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, product_code)
);

alter table public.watchlist enable row level security;

-- Authenticated users may only read/write their own rows.
create policy "watchlist_select_own" on public.watchlist
  for select using (auth.uid() = user_id);

create policy "watchlist_insert_own" on public.watchlist
  for insert with check (auth.uid() = user_id);

create policy "watchlist_delete_own" on public.watchlist
  for delete using (auth.uid() = user_id);
