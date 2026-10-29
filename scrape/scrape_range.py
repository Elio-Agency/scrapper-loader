"""
Fast Milan search scrape for a date range. Writes CSV + Excel. No DuckDB.

Default stay: check-in 24 Sep 2026 through 30 Sep 2026 (7 nights), 1 night, 1 adult.

Fast (default): unfiltered Booking list only — minutes per night, not a full census.
Full: same slices as the warehouse scrape — more hotels, much slower.

  python scrape/scrape_range.py
  python scrape/scrape_range.py --full
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from playwright.async_api import async_playwright

import milan_listings as ml
from listing_columns import ALL_COLS as COLS
from config import ROOT

OUT_DIR = ROOT / "outputs"
DEFAULT_START = date(2026, 9, 24)
DEFAULT_END = date(2026, 9, 30)


def check_ins(start: date, end: date) -> list[date]:
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


def save(rows: list[dict], start: date, end: date) -> tuple[Path, Path]:
    OUT_DIR.mkdir(exist_ok=True)
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=COLS)
    for c in COLS:
        if c not in df.columns:
            df[c] = None
    extra = [c for c in df.columns if c not in COLS and c != "card_text"]
    df = df[COLS + extra]
    csv_path = OUT_DIR / f"listings_{start.isoformat()}_to_{end.isoformat()}.csv"
    xlsx_path = OUT_DIR / f"listings_{start.isoformat()}_to_{end.isoformat()}.xlsx"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_excel(xlsx_path, index=False)
    return csv_path, xlsx_path


async def harvest(page, seen: set[str], bucket: list[dict]) -> tuple[int, bool]:
    html = await page.content()
    if ml.is_blocked(html):
        print("  captcha / bot check", flush=True)
        return (0, True)
    await ml.safe_scroll(page, 8)
    cards = await ml.extract_cards(page)
    new_n = 0
    for r in cards:
        url = r.get("property_url")
        key = f"{url}|{r.get('check_in')}|{r.get('room_type') or ''}"
        if not url or key in seen:
            continue
        seen.add(key)
        bucket.append(r)
        new_n += 1
    return (new_n, False)


async def scrape_slice(page, nflt, seen, bucket) -> bool:
    label = nflt or "all"
    print(f"  slice {label} unique={len(seen)}", flush=True)
    stale = 0
    for offset in range(0, ml.MAX_OFFSET + ml.PAGE_SIZE, ml.PAGE_SIZE):
        await page.goto(ml.search_url(offset, nflt), wait_until="domcontentloaded", timeout=45000)
        await ml.accept_cookies(page)
        await page.wait_for_timeout(ml.PAUSE_MS)
        new_n, blocked = await harvest(page, seen, bucket)
        print(f"    offset={offset} new={new_n} rows={len(bucket)}", flush=True)
        if blocked:
            return True
        if new_n == 0:
            clicked = await ml.click_load_more_or_next(page)
            if clicked:
                extra, blocked = await harvest(page, seen, bucket)
                print(f"    load-more extra={extra} rows={len(bucket)}", flush=True)
                if blocked:
                    return True
                if extra:
                    stale = 0
                    continue
            stale += 1
            if stale >= ml.STALE_TO_STOP:
                break
        else:
            stale = 0
    return False


async def scrape_stay(page, cin: date, bucket: list[dict], slices: list) -> bool:
    ml.CIN = cin
    ml.COUT = cin + timedelta(days=1)
    print(f"\n=== {ml.CIN} -> {ml.COUT} ===", flush=True)
    await ml.print_booking_total(page)
    seen: set[str] = set()
    for nflt in slices:
        if await scrape_slice(page, nflt, seen, bucket):
            return True
    print(f"  stay unique keys={len(seen)} total rows={len(bucket)}", flush=True)
    return False


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full",
        action="store_true",
        help="Use property-type / stars / price slices (slower, more hotels)",
    )
    parser.add_argument("--from-date", default=DEFAULT_START.isoformat(), help="First check-in YYYY-MM-DD")
    parser.add_argument("--to-date", default=DEFAULT_END.isoformat(), help="Last check-in YYYY-MM-DD")
    parser.add_argument(
        "--max-offset",
        type=int,
        default=None,
        help="Stop after this search offset (0 = first page only). Sample before a full run.",
    )
    args = parser.parse_args()
    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)

    if args.full:
        slices = ml.SLICES
        ml.PAUSE_MS = 1800
        ml.MAX_OFFSET = 100
    else:
        slices = [None]
        ml.PAUSE_MS = 800
        ml.MAX_OFFSET = 250
        ml.STALE_TO_STOP = 2
    if args.max_offset is not None:
        ml.MAX_OFFSET = args.max_offset
        ml.STALE_TO_STOP = 1

    stays = check_ins(start, end)
    print(
        f"Milan range scrape -> CSV/Excel | {start} to {end} "
        f"({len(stays)} nights) | adults=1 | "
        f"{'FULL slices' if args.full else 'FAST unfiltered'} | "
        f"proxy={ml.describe_proxy()}",
        flush=True,
    )
    print("Not using DuckDB. Files land in outputs/ after each stay.", flush=True)

    bucket: list[dict] = []
    async with async_playwright() as p:
        browser, page = await ml.open_browser(p)
        try:
            for cin in stays:
                blocked = await scrape_stay(page, cin, bucket, slices)
                csv_path, xlsx_path = save(bucket, start, end)
                print(f"  saved {len(bucket)} rows -> {csv_path.name}", flush=True)
                if blocked:
                    print("Stopped on captcha. Partial files are still saved.", flush=True)
                    break
        finally:
            await browser.close()

    csv_path, xlsx_path = save(bucket, start, end)
    print(f"\nDone. {len(bucket)} rows", flush=True)
    print(f"CSV   {csv_path}", flush=True)
    print(f"Excel {xlsx_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
