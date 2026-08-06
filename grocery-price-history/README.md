# HK Grocery Price History + Alerts (prototype)

Shows grocery price *history over time*, per supermarket, for products tracked by
the Consumer Council's Online Price Watch — the full archive back to
**2020-05-30**. Also flags "fake discounts" (promo tag but price never actually
dropped below its own recent median) and lists biggest genuine price drops.

**Competitor gap:** Handy lah, PriceMonHK, and the OPW site itself all show
current prices or today's sale flags only — none show longitudinal price
history, which is what you need to tell a real discount from a promo-priced
markup.

## Hosted

https://francoishideyoshi.github.io/hk-grocery-price-tracking/

Updated daily by `.github/workflows/daily-prices.yml`: fetches any new
snapshot, commits it to `raw/`, merges the change into `products.json`, and
redeploys to GitHub Pages (generating `products/*.json` + `index.json` at
deploy time).

## Architecture

- **`raw/`** — one CSV per day fetched from data.gov.hk's Historical Archive
  API, append-only, plain git blobs. Recent years live here loose; full past
  years are bundled as `raw-YYYY.tar.zst` assets on the GitHub Release
  `raw-archive` (see "Raw archive storage" below) to keep the repo small.
- **`products.json`** — the single committed state file: `{meta: {...},
  products: {<code>: {code, brand, name, category, last_seen,
  series: {STORE: [[date, price, promo], ...]}}}}`. The series is
  **sparse**: a point is only recorded when price or promo changed for that
  store (plus the first time the product/store combo is seen), because
  grocery prices barely move day to day — dense daily storage across 6 years
  would run into hundreds of MB, sparse storage is single-digit MB.
- **`products/<code>.json` + `index.json`** — **not committed.** Deploy-time
  site artifacts, generated from `products.json` by
  `backfill.py --export-site DIR`. `products/<code>.json` is one file per
  product (same shape as its `products.json` entry, minus `last_seen`).
  `index.json` holds the search list, badges (`fake:<store>`, `drop:<store>`
  per product), and a precomputed top-50 "biggest drops" list — all derived
  from `products.json`, regenerated in full on every run since the badges
  depend on a sliding 90-day window that shifts even without new data.
- **`index.html`** — one file, vanilla JS, no build step. Fetches
  `index.json` for search/badges/drops; fetches `products/<code>.json` on
  product click and renders a Chart.js stepped line per store. Chart.js is
  loaded on demand rather than from `<head>`, and the current view (filters +
  selected product) is mirrored into the query string — see "UI notes".

## UI notes

### First pass — 2026-08-06 UI/UX review

- **Drops first.** "Biggest drops" renders above the products list — it is the
  clearest demonstration of what this site does that the current prices sites
  don't, and it was previously below a list that scrolls most of a viewport.
- **Chart.js loads on demand.** ~250KB of Chart.js + date adapter used to block
  first paint from `<head>`; `loadChartLib()` now fetches them when the first
  product detail opens. If the CDN fails the price table still renders, only the
  chart area shows an error.
- **URL carries the view.** `?q=&cat=&stores=&sort=&lang=&p=` round-trips, so a
  product link is shareable and a refresh keeps its filters. Filter changes
  `replaceState`; opening a product `pushState`s, so Back closes the detail.
- **Store colors are theme-aware.** All nine clear WCAG's 3:1 non-text contrast
  floor in both themes. MANNINGS and SASA were darkened for light mode (they sat
  at 2.70:1 and 2.87:1 on white); AEON, DCHFOOD and LUNGFUNG get lighter dark-mode
  substitutes via `STORE_COLORS_DARK` (they sat at 2.25:1, 2.43:1 and 3.15:1 on
  `#111418`).
- **Social meta + favicon.** `description`, `og:*` and a data-URI SVG favicon.
  No `og:image` yet — that needs a real PNG, since Facebook/WhatsApp won't render
  an SVG card image.

### Second pass

Larger than the first, and grouped by area.

**Search and filters**

- **Token-based fuzzy matching.** Every word in the query must match a product
  as a word-prefix, a substring, or within one edit (for tokens of four or more
  characters) — so "mozzarella cheese" finds "Mozzarella Shredded Cheese" even
  though the words aren't adjacent, and a typo like "mozarella" still matches.
  Matching is a strict AND across tokens with no partial-match fallback: a query
  that matches three of four words returns nothing rather than noise.
- **Relevance ranking while searching.** With a query active, results sort by
  match quality and the chosen sort (price, name, drop) becomes the tie-break;
  with no query, the chosen sort is the only order.
- **Search debounced at 150ms**, so typing doesn't re-filter and re-render the
  list on every keystroke.
- **Sticky filter bar** under the header, so the filters stay reachable while
  scrolling the list. Its offset is measured with a `ResizeObserver` rather than
  hard-coded, because the header's height changes with viewport width, language
  and whether the badge legend is dismissed.
- **Keyboard-usable filter menus.** The store and category menus got
  `role="menu"` / `role="menuitemcheckbox"`, arrow-key navigation, and focus
  returned to the trigger on close.
- **A way out of a dead end.** A clear-all control, plus a real empty state that
  says nothing matched and offers to clear the filters, instead of an empty
  list.

**Product list**

- **Rows lead with the low price and the chain holding it** — the number people
  actually want. That needed a new per-product `cheapest: [STORE, price]` field
  in the `index.json` export (see `build_index` in `backfill.py`), since the
  index previously carried only a price range and the per-store series lives in
  the per-product files. The page falls back to the old price-range rendering
  when the field is absent, so a stale `index.json` still renders.
- **Unit price shows whenever it's parseable**, not only when sorting by it —
  it was already computed, and hiding it behind a sort mode meant most visitors
  never saw the one number that makes different pack sizes comparable.
- **Tabular numerals on prices**, so digits line up column-wise.
- **The nested scroll region is gone.** The products list had its own scrollbar
  to leave room for the drops panel; the drops panel now sits above it, so the
  page scrolls as one document.
- **50-row pagination with a "show more" control** replaces the hard 200-row
  cap. This is pagination, not virtualization: paging through thousands of rows
  still accumulates that many DOM nodes. It bounds the *initial* render, not the
  worst case.

**Typography and IA**

- **A four-step type scale** on CSS custom properties (`--text-meta`,
  `--text-sm`, `--text-base`, `--text-lg`) replaces roughly eight ad-hoc sizes
  scattered between .7 and .9rem. Body text went from about 14px to 16px.
- **A plain-language tagline in the header**, with the stats line demoted below
  it — the counts were the most prominent text on the page and explained
  nothing about what the site is for.
- **A dismissible badge legend** explaining "promo, not cheaper". That
  explanation previously existed only as a `title` tooltip, which is invisible
  on touch devices.
- **Readable section headings**, and the drops methodology moved behind a
  disclosure rather than sitting inline.
- **Footer carries last-updated, the source link, and a summary of the known
  data limits**, so the caveats aren't only in this README.
- **Loading skeletons** while the 1.1MB `index.json` fetches, and a busy state
  on the language toggle, which pulls a 554KB `names_tc.json`.
- **English chain display names** (`PARKnSHOP`, `Wellcome`, …) instead of the
  raw OPW codes, which are all-caps machine identifiers.

**Chart and detail**

- **DOM legend toggles per series**, keyboard-reachable. Chart.js draws its
  legend into the canvas, which is not reachable by keyboard at all.
- **Per-store dash patterns**, so nine lines stay distinguishable without
  relying on colour alone.
- **The detail skeleton matches the final panel's shape**, so opening a product
  settles once instead of reflowing as each piece arrives.
- **Chart respects reduced motion.**
- **The price table** gained `caption`/`thead`/`tbody`, is sortable with
  `aria-sort` reflecting the current column, and defaults to cheapest first.
- **A screen-reader summary of the chart**, since the canvas itself conveys
  nothing to assistive tech.
- **Decorative `alt=""` on product thumbnails** — the product name is already
  adjacent text, so alt text there would just repeat it.
- **Range chips disable when they exceed a product's available history**, with a
  note saying how much history exists, rather than silently drawing a 5-year
  range over 8 months of data.

**Community sightings and accounts**

- **Visible labels on every sighting field**, replacing placeholder-only
  labelling — a placeholder disappears as soon as you type, so the field loses
  its label exactly when you need to check what you're filling in.
- **The shop field is a proper combobox** with arrow-key selection of the
  geocoder suggestions. Selecting a suggestion was previously mouse-only.
- **A district fallback selector**, built from the existing district list. If
  you free-type a shop name instead of picking a geocoder suggestion, there is
  no district to derive, and the sighting used to post with an empty one.
- **Submit, vote and report failures are visible.** They previously rolled the
  optimistic UI back silently, which is indistinguishable from the action having
  worked and then undone itself. Submit also disables while in flight.
- **Reporting takes a confirmation step**, because it is irreversible and three
  reports hide a sighting.
- **The auth modal is a real dialog**: `role="dialog"`, `aria-modal`, a labelled
  heading, a focus trap, and a visible close control.
- **Password field has a show/hide toggle and correct `autocomplete` values**,
  so password managers can fill and save.
- **Supabase errors are mapped to translated text** instead of surfacing the raw
  English API message.

Known UI gaps after both passes:

- **None of this was verified in a browser.** There is no test infrastructure in
  this repo. Verification was `node --check` on the extracted inline script,
  `T.en`/`T.tc` key parity, and unit tests of the pure helpers (search scoring,
  pagination, table sort, district resolution, Supabase error mapping) sliced
  verbatim out of the page source. Layout, focus behaviour, and anything
  DOM-dependent are unverified.
- **`og:image` still needs a real PNG** — carried over from the first pass.
- **The sightings list rebuilds the whole form on an unrelated vote**, so text
  typed into an open sighting form is lost if someone's vote re-renders the
  list.
- **The fuzzy matcher uses Levenshtein, not Damerau-Levenshtein**, so
  transpositions cost two edits: "mikl" does not match "milk".

## Raw archive storage

`raw/` grows ~1MB/day as plain git blobs — fine short-term, but unbounded
growth eventually bloats the repo and every future clone. Once a calendar
year is complete, roll it up into a single compressed asset on the
`raw-archive` GitHub Release instead of carrying thousands of loose CSVs in
git history forever:

```
cd grocery-price-history
tar --zstd -cf /tmp/raw-2027.tar.zst raw/2027-*.csv
gh release upload raw-archive /tmp/raw-2027.tar.zst
git rm --cached raw/2027-*.csv
mkdir -p raw-archive && mv raw/2027-*.csv raw-archive/   # keep locally for --rebuild (gitignored)
```

**Restoring for `--fetch`/`--rebuild`:** download the year(s) you need from
the `raw-archive` release, then either `tar --zstd -xf raw-YYYY.tar.zst`
from inside `grocery-price-history/` (bundles contain `raw/...` paths), or
copy `raw-archive/*.csv` back into `raw/`.

## Run it locally

```
python3 backfill.py --fetch --start 2020-05-30   # one-time: populate raw/ (slow, ~2000 downloads)
python3 backfill.py --rebuild                     # build products.json from raw/
python3 backfill.py --export-site .               # generate index.json + products/ for local preview
python3 -m http.server 8000
```

Then open http://localhost:8000/index.html

`--fetch` and `--rebuild` need the full CSV history available locally
(loose in `raw/` and/or restored from the `raw-archive` release bundles —
see "Raw archive storage" above). `--update` (what CI runs daily) does not —
it never opens an existing `raw/*.csv`, only `products.json` plus whatever
new day(s) it fetches fresh over HTTP. `index.json`/`products/` are
gitignored and regenerated in place by `--export-site .` for local preview.

## Data sources

- Live CSV: https://online-price-watch.consumer.org.hk/opw/opendata/pricewatch_en.csv
- Historical snapshots: data.gov.hk Historical Archive API
  (`list-file-versions` / `get-file` against the CSV URL above).
  `list-file-versions` windows are capped at roughly a year, so
  `backfill.py` chunks multi-year requests.

## How backfill.py works

Four modes (stdlib only):

- **`--fetch --start YYYY-MM-DD [--end YYYY-MM-DD]`** — downloads missing
  daily snapshots into `raw/` (resumable, skips days already cached). Used
  once locally to populate 2020-05-30 onward; a rare/manual operation.
- **`--rebuild`** — regenerates `products.json` from every CSV in `raw/`.
  Rare/local; needed after `--fetch` or if the sparse format's logic
  changes.
- **`--update`** — what CI runs daily: reads `products.json`'s last
  processed date, fetches only the days since (always over the network —
  never trusts a locally cached `raw/*.csv`), merges each new day into
  `products.json`, and updates its `meta`. Exits 0 even if the archive API
  fails, so a bad day never breaks the deploy. If `products.json` exists but
  fails to parse, the run hard-fails (`sys.exit(1)`) instead of silently
  starting from an empty state — that would otherwise let CI commit away
  all price history.
- **`--export-site DIR`** — regenerates `products/<code>.json` +
  `index.json` (deploy-time site artifacts) from `products.json` into
  `DIR`. Run by CI into `dist/` right before the Pages upload; nothing it
  writes is committed to git.

## Real CSV schema (verified, not assumed)

Two schemas exist in the archive, both handled transparently by
`normalize_rows()`:

- **Long format** (2020-07-29 onward, current):
  `Category 1,Category 2,Category 3,Product Code,Brand,Product Name,Supermarket Code,Price,Offers`
- **Wide format** (2020-05-30 to ~2020-07-28): one `Price (Store)` /
  `Offers (Store)` column pair per store instead of `Supermarket Code`/
  `Price` rows, covering 6 stores (Wellcome, PARKnSHOP, Market Place by
  Jasons, Watsons, AEON, DCH Food Mart).

Supermarket codes seen in the long format: `AEON, DCHFOOD, JASONS,
LUNGFUNG, MANNINGS, PARKNSHOP, SASA, WATSONS, WELLCOME` (added over time —
broader than the 6 stores tracked in the original wide-format era). Product
names/offers can contain commas, so parsing uses Python's `csv` module, not
`str.split(',')`.

## Known limits

- Archive snapshots aren't daily — some days have no version (site wasn't
  scraped), so gaps exist in `raw/`'s date coverage. `meta.snapshot_count`
  in `index.json` reflects what's actually cached, not calendar days.
- "Fake discount" and "biggest drop" badges use a 90-day sliding window,
  reconstructed from each product's *sparse* series by carrying the last
  known price forward through the window (not a true daily average — a
  stdlib-only, close-enough approximation for a prototype).
- Category is a flattened "Category 1 / Category 2 / Category 3" string,
  not a real taxonomy.
- A product's chart line is extended to its `last_seen` date (from
  `index.json`) with a flat point, so a still-current product with no
  recent price change still draws to "now" — but a delisted product
  correctly stops at its actual last-seen date instead of drawing a
  misleading flat line to today.
- `raw/` grows ~1MB/day as plain git blobs until the yearly rollup moves
  the year to the `raw-archive` release bundle — see "Raw archive storage"
  above.
- GitHub Actions `schedule` cron is best-effort — GitHub can delay or drop a
  scheduled run under load, so a day's snapshot can occasionally be missed.
  `--update` catches up automatically on the next run (it fetches every day
  since the last processed one, not just "yesterday"). `workflow_dispatch`
  lets you trigger a catch-up run manually too.
