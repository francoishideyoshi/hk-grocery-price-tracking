# Setting up accounts + watchlist (Supabase)

Optional. Without this the site works exactly as before, with no account UI.

1. Create a free project at [supabase.com](https://supabase.com).
2. In **Project Settings → API Keys** (older projects: **Settings → API**), copy
   the **Project URL** and the **anon/public** key (newer dashboards label it
   "publishable" / "anon (legacy)"; either works with supabase-js v2).
3. Open **SQL Editor**, paste in the contents of `supabase/schema.sql`, and run it.
   This creates the `watchlist` table with row-level security so each user can
   only see/change their own tracked products.
4. In **Authentication → Providers**, confirm **Email** is enabled (it is by
   default). The free tier's built-in email sender has low send-rate limits —
   fine for testing, but consider a custom SMTP provider before real traffic.
5. In **Authentication → URL Configuration**, set **Site URL** to wherever you
   deploy this site (e.g. `https://yourdomain.example`). This is the link used
   in the "confirm your email" message sent after sign-up.
6. Open `index.html`, find the two constants near the top of the `<script>`
   block, and paste in your values:

   ```js
   const SUPABASE_URL = 'https://xxxxx.supabase.co';
   const SUPABASE_ANON_KEY = 'eyJ...';
   ```

   The anon key is safe to expose in client-side code — it only grants what
   the RLS policies in `schema.sql` allow (each user reading/writing their own
   watchlist rows).

That's it — reload the page and an account button appears in the header.

## OAuth: Google + Apple sign-in

The auth modal has "Continue with Google" / "Continue with Apple" buttons
above the email/password form. They only do something once the matching
provider is enabled in Supabase — until then they'll surface an error via
`signInWithOAuth`. Steps current as of mid-2026 dashboards; provider config
may appear under **Authentication → Providers** or under a newer
**Third-party auth** section depending on your project's dashboard version.

### Google (free)

1. In [Google Cloud Console](https://console.cloud.google.com), create (or
   pick) a project.
2. **APIs & Services → OAuth consent screen** — configure it, adding the
   `email` and `profile` scopes.
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**,
   application type **Web application**.
4. Under **Authorized redirect URIs**, add exactly:
   `https://<project-ref>.supabase.co/auth/v1/callback`
   (find `<project-ref>` in your Supabase project URL).
5. Copy the generated **Client ID** and **Client Secret**.
6. In Supabase, **Authentication → Providers → Google**: enable, paste both
   values, save.

### Apple (requires paid Apple Developer Program, $99/yr)

1. In the [Apple Developer portal](https://developer.apple.com/account):
   create an **App ID** if you don't have one, then create a **Services ID**
   — this Services ID string is what you'll use as the OAuth client ID.
2. On that Services ID, enable **Sign in with Apple** and configure it with
   the same Supabase callback URL as above:
   `https://<project-ref>.supabase.co/auth/v1/callback`.
3. Create a **Sign in with Apple private key** (a `.p8` file). Note its
   **Key ID**, and your account's **Team ID**.
4. Generate the ES256 client-secret JWT Supabase expects: `iss` = Team ID,
   `sub` = Services ID, `aud` = `https://appleid.apple.com`, `exp` ≤ 6 months.
   Supabase's docs include a generator script for this — search their Apple
   provider guide. **This secret expires and must be regenerated roughly
   every 6 months.**
5. In Supabase, **Authentication → Providers → Apple**: enable, paste the
   Services ID (as client ID) and the generated secret JWT, save.

### Both providers

Add this site's deployed URL to **Authentication → URL Configuration →
Redirect URLs** — the `redirectTo` value the app sends
(`window.location.origin + window.location.pathname`) must be allowlisted
there or the OAuth redirect will be rejected.
