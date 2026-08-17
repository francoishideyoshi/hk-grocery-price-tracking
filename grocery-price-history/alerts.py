#!/usr/bin/env python3
"""Daily email price alerts for starred (watchlist) products.

Reads products.json (the sparse per-store series committed by
backfill.py --update), detects which starred products changed price/offer
since the last alert, and emails each affected user a single digest via
Resend. In CI the claim half runs after backfill.py --update and the send half
after the snapshot commit.

Feature-flag style, same spirit as index.html's AUTH_ENABLED: missing env
vars print "alerts disabled (...)" and exit 0 so the workflow still deploys.

Storage:
  alert_state.json  per-day watermark with the claimed window. The run is
                    split so the day is claimed in the repo BEFORE any email
                    is sent (a failed commit/push then aborts the job with
                    nothing sent instead of re-emailing every user):
                    --claim writes {"last_sent_date", "pending_until"} (or
                    just {"pending_until"} on the very first run) and sends
                    nothing; --send consumes that window and rewrites the
                    file as {"last_sent_date": <day>} without pending_until.
                    last_sent_date only ever moves on a successful send, so a
                    day that was claimed but never sent stays inside the next
                    window and still fires.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
PRODUCTS_JSON = ROOT / "products.json"
ALERT_STATE_JSON = ROOT / "alert_state.json"
DEFAULT_SITE_URL = "https://francoishideyoshi.github.io/hk-grocery-price-tracking/"
# ponytail: Resend's default account rate limit is 2 requests/second — the
# ceiling. 0.2s (5/s) would burst past it and start landing 429s, silently
# dropping those users' digests; 0.6s (~1.7/s) stays under the limit.
SEND_SLEEP_SECS = 0.6

# ponytail: ceiling on the catch-up window — after an outage longer than a
# week, the older changes are silently skipped rather than emailing weeks of
# history (0.6s per email, so a week of busy markets is already a lot).
MAX_BACKLOG_DAYS = 7

# OPW Supermarket Codes -> display names, mirroring index.html's CHAIN_EN so
# email bodies read like the site; unknown codes fall through to the code.
STORE_NAMES = {
    "PARKNSHOP": "PARKnSHOP", "WELLCOME": "Wellcome", "AEON": "AEON",
    "WATSONS": "Watsons", "MANNINGS": "Mannings", "JASONS": "Market Place",
    "DCHFOOD": "DCH Food Mart", "LUNGFUNG": "Lung Fung", "SASA": "Sasa",
}

KIND_LABEL = {"down": "price DOWN", "up": "price UP", "promo": "new promo"}


def normalize_offer(offer: str | None) -> str | None:
    """Compare-form of a promo string: strip, collapse internal whitespace,
    drop leading/trailing '/' (the source data occasionally appends a bare
    '/' to an otherwise identical offer). None stays None so None and "" are
    still distinct from a real promo. The original text is what the email
    shows; this is only for deciding whether the promo actually changed."""
    if offer is None:
        return None
    return " ".join(offer.strip().strip("/").split())


def detect_changes(state: dict, since: str, until: str) -> list[dict]:
    """Which (product, store) pairs changed within the window, the sparse way.

    backfill.py appends a series point only when price or offer differs from
    the previous point (or on a store's first sighting), so a change landed
    since `since` is exactly: the latest point is dated in (since, until]
    AND the series has >= 2 points (a lone first sighting has no baseline to
    compare against). `since` is an open bound — a day an earlier run already
    alerted must not re-alert; `until` is closed. since == until is the very
    first run (no prior watermark): only the newest day is considered, so a
    first run never blasts out months of backlog.
    Returns one dict per change: {code, name, brand, store, old_price,
    new_price, old_offer, new_offer, old_date, kind} with kind in {"down",
    "up", "promo"}.
    """
    changes: list[dict] = []
    for product in state["products"].values():
        for store, series in product["series"].items():
            if len(series) < 2:
                continue
            last_date = series[-1][0]
            # First run (since == until): only the newest day counts; any
            # later run: strictly after the previous watermark, up to today.
            in_window = since < last_date <= until or (since == until and last_date == until)
            if not in_window:
                continue
            prev, cur = series[-2], series[-1]
            old_price, new_price, old_offer, new_offer = prev[1], cur[1], prev[2], cur[2]
            if old_price is not None and new_price is not None and old_price != new_price:
                kind = "down" if new_price < old_price else "up"
            elif normalize_offer(old_offer) != normalize_offer(new_offer):
                kind = "promo"
            else:
                continue  # nothing observable changed
            changes.append({
                "code": product["code"], "name": product["name"],
                "brand": product["brand"], "store": store,
                "old_price": old_price, "new_price": new_price,
                "old_offer": old_offer, "new_offer": new_offer,
                "old_date": prev[0], "kind": kind,
            })
    return changes


def fmt_price(price: float | None) -> str:
    return f"${price:.2f}" if price is not None else "—"


def render_email(products: list[tuple[str, list[dict]]], site_url: str) -> tuple[str, str]:
    """One product block per (code, changes), one store line each. Returns
    (html, text). All CSV-derived text is html.escape()d in the HTML body —
    it comes from a third-party dataset, never trusted. Each line carries the
    previous point's date: the series is sparse, so the change may have
    happened days or weeks before the latest snapshot."""
    html_blocks, text_blocks = [], []
    for code, changes in products:
        name = html.escape(changes[0]["name"])
        brand = html.escape(changes[0]["brand"])
        href = f"{html.escape(site_url, quote=True)}?p={html.escape(code, quote=True)}"
        html_lines, text_lines = [], []
        for c in changes:
            label = KIND_LABEL[c["kind"]]
            store = html.escape(STORE_NAMES.get(c["store"], c["store"]))
            since = f" (since {c['old_date']})"
            if c["kind"] == "promo":
                detail = f'new promo: "{html.escape(c["new_offer"] or "")}"'
                text_detail = f'new promo: "{c["new_offer"] or ""}"'
                if c["old_offer"]:
                    detail += f' (was "{html.escape(c["old_offer"])}")'
                    text_detail += f' (was "{c["old_offer"]}")'
            else:
                detail = text_detail = f"{label}: {fmt_price(c['old_price'])} -> {fmt_price(c['new_price'])}"
                if normalize_offer(c["old_offer"]) != normalize_offer(c["new_offer"]):
                    detail += f' — new promo "{html.escape(c["new_offer"] or "")}"'
                    text_detail += f' — new promo "{c["new_offer"] or ""}"'
            detail += since
            text_detail += since
            html_lines.append(f"<li>{store} — {detail}</li>")
            text_lines.append(f"  {store} — {text_detail}")
        html_blocks.append(
            f'<li><a href="{href}">{name}</a>'
            + (f" ({brand})" if brand else "")
            + f"<ul>{''.join(html_lines)}</ul></li>",
        )
        text_blocks.append(
            f"- {changes[0]['name']}"
            + (f" ({changes[0]['brand']})" if changes[0]["brand"] else "")
            + "\n" + "\n".join(text_lines),
        )

    footer_html = (
        f'<p>You are getting this because you starred these products. '
        f'Turn it off in <a href="{html.escape(site_url, quote=True)}">Account</a>.</p>'
    )
    footer_text = (
        "---\nYou are getting this because you starred these products. "
        f"Turn it off in Account: {site_url}"
    )
    return "<ul>" + "".join(html_blocks) + "</ul>" + footer_html, "\n".join(text_blocks) + "\n\n" + footer_text


def fetch_recipients(supabase_url: str, service_key: str) -> list[dict]:
    """Every row of the alert_recipients view. Supabase caps GETs at 1000
    rows, so page with the Range header until a short page comes back."""
    url = f"{supabase_url}/rest/v1/alert_recipients?select=user_id,email,product_code"
    base_headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    rows: list[dict] = []
    offset = 0
    while True:
        headers = {**base_headers, "Range": f"{offset}-{offset + 999}"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = json.loads(resp.read())
        rows.extend(page)
        if len(page) < 1000:
            return rows
        offset += 1000


def send_email(from_addr: str, to: str, subject: str, html_body: str, text_body: str, api_key: str) -> None:
    """POST one digest email to Resend. Raises on failure — the caller counts
    it and keeps going."""
    payload = json.dumps({
        "from": from_addr, "to": [to], "subject": subject,
        "html": html_body, "text": text_body,
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a killed mid-write run never
    leaves a truncated alert_state.json that re-triggers a duplicate send."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def load_watermark() -> dict | None:
    """Parsed alert_state.json, or None when the file is absent. A corrupt
    file is treated as nothing-pending: alerts are an optional feature, so a
    broken watermark must not fail the whole workflow (and the Pages deploy),
    and re-sending every user would be worse."""
    if not ALERT_STATE_JSON.exists():
        return None
    try:
        wm = json.loads(ALERT_STATE_JSON.read_text())
        if not isinstance(wm, dict) or not (wm.keys() & {"last_sent_date", "pending_until"}):
            raise KeyError("no watermark fields")
        return wm
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"alert_state.json corrupt ({exc}) — treating as already sent, no alerts today", file=sys.stderr)
        sys.exit(0)


def resolve_since(wm: dict | None, until: str) -> str:
    """Window's open lower bound: the previous last_sent_date, capped at
    MAX_BACKLOG_DAYS back from `until` so a long outage can't blast weeks of
    backlog, or `until` itself when there is no last_sent_date (very first
    run — only the newest day is alerted, never months of backlog)."""
    if wm is None or "last_sent_date" not in wm:
        return until
    since = wm["last_sent_date"]
    floor = (date.fromisoformat(until) - timedelta(days=MAX_BACKLOG_DAYS)).isoformat()
    return since if since >= floor else floor


def plan_claim(wm: dict | None, until: str) -> dict | None:
    """Watermark to write when claiming `until`, or None when that day is
    already pending (nothing to do). Keeps last_sent_date untouched — only a
    successful send ever advances it — and sets pending_until = until."""
    if wm is not None and wm.get("pending_until") == until:
        return None
    out = {}
    if wm is not None and "last_sent_date" in wm:
        out["last_sent_date"] = wm["last_sent_date"]
    out["pending_until"] = until
    return out


def cmd_claim() -> None:
    """--claim: write the pending window into alert_state.json, send nothing.
    Runs before the commit step so the claimed day reaches origin before any
    email is sent; a later push failure then aborts the job with nothing
    emailed. last_sent_date is left unchanged, so a day that was claimed but
    never sent (crash, 5xx, cancelled job) stays inside the next window and
    still gets emailed."""
    state = json.loads(PRODUCTS_JSON.read_text())
    until = state["meta"]["window_end"]
    write = plan_claim(load_watermark(), until)
    if write is None:
        print(f"alerts already claimed for {until}")
        sys.exit(0)
    atomic_write_text(ALERT_STATE_JSON, json.dumps(write))
    print(f"claimed alerts for {until} (since {resolve_since(write, until)})")


def send_window(state: dict, env: dict, site_url: str, since: str, until: str) -> None:
    """Fetch recipients, email digests for the window, then write the
    watermark without pending_until. Exits (not returns) on fatal conditions;
    per-user send failures are counted and swallowed."""
    changes = detect_changes(state, since, until)
    users_emailed = failures = 0
    if changes:
        try:
            recipients = fetch_recipients(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"])
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 404):
                # misconfigured key or a missing alert_recipients view — be
                # loud during setup; this is a config error, not a blip.
                print(f"recipients fetch failed (HTTP {exc.code}): check SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and that supabase/alerts.sql was run", file=sys.stderr)
                sys.exit(1)
            print(f"recipients fetch failed: {exc}", file=sys.stderr)
            sys.exit(0)  # transient — the claim is untouched, so the next run retries
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            print(f"recipients fetch failed: {exc}", file=sys.stderr)
            sys.exit(0)  # transient — the claim is untouched, so the next run retries

        by_code = {}
        for c in changes:
            by_code.setdefault(c["code"], []).append(c)
        by_user: dict[str, dict] = {}
        for r in recipients:
            entry = by_user.setdefault(r["user_id"], {"email": r["email"], "codes": []})
            entry["codes"].append(r["product_code"])

        for entry in by_user.values():
            products = [(code, by_code[code]) for code in entry["codes"] if code in by_code]
            if not products:
                continue
            kinds = [c["kind"] for _, cs in products for c in cs]
            if all(k == "promo" for k in kinds):
                subject = f"{len(products)} of your tracked items have a new promo"
            else:
                subject = f"{len(products)} of your tracked items changed price"
            html_body, text_body = render_email(products, site_url)
            try:
                send_email(env["ALERT_FROM"], entry["email"], subject, html_body, text_body,
                           env["RESEND_API_KEY"])
            except (urllib.error.URLError, OSError) as exc:
                print(f"email to {entry['email']} failed: {exc}", file=sys.stderr)
                failures += 1
                continue
            users_emailed += 1
            time.sleep(SEND_SLEEP_SECS)

    # ponytail: the watermark records the window as sent even when an
    # individual send failed — re-running the same day would re-email every
    # user who already got a digest, and the failed recipient's alert is lost
    # either way (state is per-day, not per-user). A claimed day that never
    # reaches here at all (crash / cancelled job) is untouched and stays
    # pending, so tomorrow's window still covers it.
    atomic_write_text(ALERT_STATE_JSON, json.dumps({"last_sent_date": until}))
    print(f"{len(changes)} changes, {users_emailed} users emailed, {failures} failures")


def cmd_send(env: dict, site_url: str) -> None:
    """--send: email the window claimed by an earlier --claim, then drop
    pending_until so a re-run finds nothing pending. A claimed but never-sent
    day keeps its pending_until and stays inside the next window."""
    wm = load_watermark()
    if wm is None or "pending_until" not in wm:
        print("nothing pending")
        sys.exit(0)
    until = wm["pending_until"]
    state = json.loads(PRODUCTS_JSON.read_text())
    send_window(state, env, site_url, resolve_since(wm, until), until)


def run_selftest() -> None:
    """Synthetic products.json exercises detect_changes with no env/network."""
    day = "2026-01-02"

    def p(code: str, series: list[list]) -> dict:
        return {"code": code, "brand": "Brand", "name": "Product", "category": [],
                "series": {"WELLCOME": series}}

    # First run: since == until == the newest day; only that day's changes.
    state = {"meta": {"window_end": day}, "products": {
        "down": p("down", [["2026-01-01", 10.0, ""], [day, 9.0, ""]]),
        "up": p("up", [["2026-01-01", 10.0, ""], [day, 11.0, ""]]),
        "promo": p("promo", [["2026-01-01", 10.0, ""], [day, 10.0, "2 for $15"]]),
        "single": p("single", [[day, 9.0, ""]]),  # first sighting, no baseline
        "stale": p("stale", [["2025-12-31", 9.0, ""], ["2026-01-01", 10.0, ""]]),  # predates the window
    }}
    changes = detect_changes(state, day, day)
    by_code = {c["code"]: c for c in changes}
    assert by_code["down"]["kind"] == "down"
    assert by_code["down"]["old_price"] == 10.0 and by_code["down"]["new_price"] == 9.0
    assert by_code["up"]["kind"] == "up"
    assert by_code["promo"]["kind"] == "promo"
    assert "single" not in by_code and "stale" not in by_code
    assert len(changes) == 3

    # A later run: the window is (since, until] — strictly after the previous
    # watermark, up to and including the newest day.
    window_state = {"meta": {"window_end": day}, "products": {
        "between": p("between", [["2025-12-29", 10.0, ""], ["2025-12-31", 9.0, ""]]),  # strictly inside
        "onsince": p("onsince", [["2025-12-29", 10.0, ""], ["2025-12-30", 9.0, ""]]),  # last == since
        "onuntil": p("onuntil", [["2025-12-31", 10.0, ""], [day, 9.0, ""]]),  # last == until
    }}
    wc = {c["code"]: c for c in detect_changes(window_state, "2025-12-30", day)}
    assert wc["between"]["kind"] == "down"   # 2025-12-31 in (2025-12-30, 2026-01-02]
    assert "onsince" not in wc               # 2025-12-30 is not > since
    assert wc["onuntil"]["kind"] == "down"   # 2026-01-02 == until still fires

    # FIX C: cosmetic promo rewording is not a change; a real promo change is.
    promo_state = {"meta": {"window_end": day}, "products": {
        "cosmetic": p("cosmetic", [["2025-12-31", 10.0, "Buy 2 item(s)  for $36.00 /"], [day, 10.0, "Buy 2 item(s) for $36.00"]]),
        "realpromo": p("realpromo", [["2025-12-31", 10.0, "Buy 2 for $15"], [day, 10.0, "Buy 2 for $12"]]),
    }}
    pc = {c["code"]: c for c in detect_changes(promo_state, "2025-12-31", day)}
    assert "cosmetic" not in pc
    assert pc["realpromo"]["kind"] == "promo"

    # FIX 1: a claim keeps last_sent_date untouched, so a day that was claimed
    # but never sent stays inside the next window. The 2026-01-02 digest went
    # out; 2026-01-04 was claimed and the send never completed; the next run
    # still emails the missed 2026-01-03 change.
    assert plan_claim({"last_sent_date": "2026-01-02", "pending_until": "2026-01-03"}, "2026-01-04") \
        == {"last_sent_date": "2026-01-02", "pending_until": "2026-01-04"}
    wm_pending = {"last_sent_date": "2026-01-02", "pending_until": "2026-01-04"}
    missed_state = {"meta": {"window_end": "2026-01-04"}, "products": {
        "missed": p("missed", [["2026-01-01", 10.0, ""], ["2026-01-03", 9.0, ""]]),
    }}
    missed_since = resolve_since(wm_pending, "2026-01-04")
    assert missed_since == "2026-01-02"      # not advanced by the claim
    assert {c["code"] for c in detect_changes(missed_state, missed_since, "2026-01-04")} == {"missed"}
    assert plan_claim(wm_pending, "2026-01-04") is None          # already claimed
    assert resolve_since({"pending_until": "2026-01-04"}, "2026-01-04") == "2026-01-04"  # first run

    # FIX 2: the catch-up window is capped at MAX_BACKLOG_DAYS.
    assert resolve_since({"last_sent_date": "2026-01-01", "pending_until": "2026-02-10"}, "2026-02-10") \
        == "2026-02-03"                       # 2026-02-10 - 7 days
    assert resolve_since({"last_sent_date": "2026-02-09", "pending_until": "2026-02-10"}, "2026-02-10") \
        == "2026-02-09"                       # recent enough, no cap


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true", help="run built-in change-detection checks")
    parser.add_argument("--claim", action="store_true", help="claim the day in alert_state.json, send nothing")
    parser.add_argument("--send", action="store_true", help="send emails for the pending claimed window")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        print("selftest ok")
        return

    if args.claim:
        cmd_claim()
        return

    env = {name: os.environ.get(name, "").strip() for name in
           ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "RESEND_API_KEY", "ALERT_FROM")}
    for name, value in env.items():
        if not value:
            print(f"alerts disabled (missing {name})")
            sys.exit(0)

    site_url = os.environ.get("SITE_URL", "").strip() or DEFAULT_SITE_URL

    if args.send:
        cmd_send(env, site_url)
        return

    # no mode: claim-then-send in one shot, for local use.
    state = json.loads(PRODUCTS_JSON.read_text())
    until = state["meta"]["window_end"]
    write = plan_claim(load_watermark(), until)
    if write is None:
        print(f"alerts already claimed for {until}")
        sys.exit(0)
    atomic_write_text(ALERT_STATE_JSON, json.dumps(write))
    send_window(state, env, site_url, resolve_since(write, until), until)


if __name__ == "__main__":
    main()