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
  product click and renders a Chart.js stepped line per store.

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
