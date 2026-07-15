# HK Grocery Price Tracking

Longitudinal price history per supermarket chain for 2,200+ products, sourced from the
Consumer Council Online Price Watch and backfilled to 2020-05-30. Flags fake discounts
(a promo tag on a price that's still &ge; its 90-day median) and surfaces the biggest
real drops each day.

**Live site:** https://francoishideyoshi.github.io/hk-grocery-price-tracking/

## Why

The official [Online Price Watch site](https://data.gov.hk/en-data/dataset/cc-pricewatch-pricewatch),
[Handy lah](https://apps.apple.com/hk/app/handy-lah-grocery-price-watch/id1413159670?l=en),
and PriceMonHK all show current prices only — no history. There's no way to tell a real
discount from a promo-priced markup without knowing what the item actually sold for over
the past few months.

## Data source

[Consumer Council Online Price Watch](https://data.gov.hk/en-data/dataset/cc-pricewatch-pricewatch)
daily CSV, plus the data.gov.hk Historical Archive API for backfilling snapshots before
this project started tracking.

## How it works

A daily GitHub Action fetches the new OPW snapshot, updates `products.json` (sparse
per-store price series so unchanged prices don't re-store a point every day), and
deploys the static site to GitHub Pages. Full architecture in
[grocery-price-history/README.md](grocery-price-history/README.md).
