# Setting up daily email price alerts (Resend + Supabase)

Optional, and it builds on the accounts/watchlist setup in `SETUP-AUTH.md` —
alerts email users who have starred products, so that needs to be working
first. Until the secrets below are added, the workflow prints
`alerts disabled (missing X)` and deploys as before.

1. Open **SQL Editor**, paste in the contents of `supabase/alerts.sql`, and run
   it. This creates the `alert_prefs` table (one row per user, an opt-out
   flag; no row means alerts on) and the `alert_recipients` view (every
   watchlist row joined to its owner's email). The view is **service-role
   only** — it exposes user email addresses, so the anon and authenticated
   roles are revoked and the service-role key is its sole reader.
2. Create a free account at [resend.com](https://resend.com), verify a sending
   domain, and create an **API key**. Without a verified domain Resend only
   delivers to your own account's email address — real users get nothing until
   the domain is verified. The free tier is roughly 3,000 emails/month
   (confirm on Resend's pricing page before relying on the exact figure).
3. In this repo, **Settings → Secrets and variables → Actions**, add these
   repository secrets:
   - **`SUPABASE_URL`** — the project URL, from **Project Settings → API
     Keys** (older projects: **Settings → API**).
   - **`SUPABASE_SERVICE_ROLE_KEY`** — the **service_role** key from the same
     page. It bypasses RLS entirely, so it must never go in `index.html` or
     any other client-side file — the CI alert job is its only reader.
   - **`RESEND_API_KEY`** — the API key from Resend.
   - **`ALERT_FROM`** — the "From" address shown in email, e.g.
     `"HK Grocery Prices <alerts@yourdomain.com>"`. The domain must be the one
     verified in step 2.
   - **`SITE_URL`** (optional) — the site URL used in email links; defaults to
     the GitHub Pages URL.
4. Trigger the **daily-prices** workflow (**Actions → daily-prices → Run
   workflow**). The run claims the alert window **before** sending anything:
   expand the **Claim daily alert window** step, which prints one of:
   - `claimed alerts for <date> (since <date>)` — the window is now pending.
   - `alerts already claimed for <date>` — that day is already pending,
     nothing to do.
   Then expand **Send daily price alerts** (after the commit step), which
   prints one of:
   - `alerts disabled (missing X)` — the secrets aren't all set (step 3); the
     step is skipped entirely when `RESEND_API_KEY` isn't configured.
   - `nothing pending` — no claimed window to send.
   - `N changes, M users emailed, K failures` — the real run.
5. Behaviour notes: each user gets **one** digest email per claimed window;
   an alert fires when a starred product's price went up, went down, or its
   promo text changed since the previous recorded price (the series is sparse
   — OPW has gaps — so the change may span several days, and the email shows
   the date the previous price was recorded); users opt out via the
   **Account** modal on the site. `alert_state.json` is the per-day watermark
   the CI job commits — `last_sent_date` only advances on a successful send,
   so a day that was claimed but never sent stays inside the next window and
   still fires; the catch-up window is capped at 7 days. Deleting the file
   makes the next run a first run (only the newest day is alerted).

That's it — from the next scheduled run, anyone who starred a product with a
price or promo change gets a digest.
