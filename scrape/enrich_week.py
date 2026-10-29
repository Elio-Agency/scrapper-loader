"""
Fill address + amenities on week listing CSVs.

Opens each unique hotel page once (same method as DoubleTree), caches results,
and writes enriched CSV/Excel. Safe to re-run; already-cached URLs are skipped.

  python scrape/enrich_week.py --dir outputs
  python scrape/enrich_week.py --dir outputs --limit 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

import pandas as pd
from playwright.async_api import async_playwright

import scrape_one_property as one
from listing_columns import ALL_COLS, PROPERTY_COLS
from config import ROOT

DEFAULT_DIR = ROOT / "outputs"
CACHE_NAME = "property_enrich_cache.json"
PATTERN = "listings_2026-09-??_to_2026-09-??.csv"


def norm_url(url: str) -> str:
    return str(url).split("?")[0].rstrip("/")


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(path: Path, cache: dict) -> None:
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def listing_csvs(folder: Path) -> list[Path]:
    return sorted(folder.glob(PATTERN))


def unique_urls(files: list[Path]) -> list[str]:
    seen = []
    got = set()
    for path in files:
        df = pd.read_csv(path, usecols=["property_url"])
        for raw in df["property_url"].dropna().astype(str):
            url = norm_url(raw)
            if url and url not in got:
                got.add(url)
                seen.append(url)
    return seen


def extras_from_prop(prop: dict) -> dict:
    return {
        "address": prop.get("address"),
        "street": prop.get("street"),
        "postal_code": prop.get("postal_code"),
        "city": prop.get("city"),
        "country": prop.get("country"),
        "popular_facilities": "; ".join(prop.get("popular_facilities") or []),
        "amenities": one.amenities_text(prop),
    }


def apply_cache(df: pd.DataFrame, cache: dict) -> pd.DataFrame:
    out = df.copy()
    keys = out["property_url"].astype(str).map(norm_url)
    for col in PROPERTY_COLS:
        out[col] = keys.map(lambda u, c=col: (cache.get(u) or {}).get(c))
    for col in ALL_COLS:
        if col not in out.columns:
            out[col] = None
    extra = [c for c in out.columns if c not in ALL_COLS]
    return out[ALL_COLS + extra]


async def enrich_urls(urls: list[str], cache: dict, cache_path: Path, cin: date) -> None:
    async with async_playwright() as p:
        browser, page = await one.open_browser(p)
        try:
            for i, url in enumerate(urls, 1):
                if cache.get(url) and cache[url].get("address"):
                    print(f"[{i}/{len(urls)}] skip {url}", flush=True)
                    continue
                stay = one.property_url(url, cin, 1, 1)
                print(f"[{i}/{len(urls)}] {url}", flush=True)
                try:
                    prop = await one.scrape(page, stay)
                except Exception as exc:
                    print(f"  error {exc}", flush=True)
                    save_cache(cache_path, cache)
                    continue
                if prop.get("blocked"):
                    print("  captcha / bot check — cache saved. Re-run later.", flush=True)
                    save_cache(cache_path, cache)
                    return
                cache[norm_url(prop.get("url") or url)] = extras_from_prop(prop)
                if i % 5 == 0:
                    save_cache(cache_path, cache)
                await page.wait_for_timeout(700)
        finally:
            await browser.close()
    save_cache(cache_path, cache)


def write_enriched(files: list[Path], cache: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in files:
        df = pd.read_csv(path)
        filled = apply_cache(df, cache)
        csv_path = out_dir / path.name
        xlsx_path = out_dir / path.with_suffix(".xlsx").name
        filled.to_csv(csv_path, index=False, encoding="utf-8-sig")
        filled.to_excel(xlsx_path, index=False)
        n = filled["address"].fillna("").astype(str).str.len().gt(0).sum()
        print(f"  wrote {csv_path.name}  {n}/{len(filled)} rows have address", flush=True)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=str(DEFAULT_DIR), help="Folder with listings_2026-09-* CSVs")
    parser.add_argument("--limit", type=int, default=0, help="Only first N unique hotels (0 = all)")
    parser.add_argument("--from-date", default="2026-09-24")
    parser.add_argument("--part", type=int, default=0, help="Shard index (0-based)")
    parser.add_argument("--parts", type=int, default=1, help="How many shards")
    parser.add_argument("--apply", action="store_true", help="Only merge caches into CSV/Excel, no scrape")
    args = parser.parse_args()
    folder = Path(args.dir)
    files = listing_csvs(folder)
    if not files:
        print(f"No {PATTERN} in {folder}", flush=True)
        print("Unzip outputs-week.zip into that folder first.", flush=True)
        return
    urls = unique_urls(files)
    if args.parts > 1:
        urls = urls[args.part :: args.parts]
    if args.limit:
        urls = urls[: args.limit]
    if args.parts > 1:
        cache_path = folder / f"property_enrich_cache.p{args.part}.json"
    else:
        cache_path = folder / CACHE_NAME

    def merged_cache() -> dict:
        out = {}
        for p in sorted(folder.glob("property_enrich_cache*.json")):
            out.update(load_cache(p))
        return out

    if args.apply:
        cache = merged_cache()
        print(f"apply only | {len(cache)} hotels in cache", flush=True)
        write_enriched(files, cache, folder / "enriched")
        print("Done. Enriched files in", folder / "enriched", flush=True)
        return

    cache = load_cache(cache_path)
    print(
        f"{len(files)} files | shard {args.part}/{args.parts} | "
        f"{len(urls)} hotels this shard | {len(cache)} cached",
        flush=True,
    )
    await enrich_urls(urls, cache, cache_path, date.fromisoformat(args.from_date))
    if args.parts > 1:
        print(f"shard {args.part} finished. Run --apply after all shards.", flush=True)
        return
    cache = merged_cache()
    write_enriched(files, cache, folder / "enriched")
    print("Done. Enriched files in", folder / "enriched", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
