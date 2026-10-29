"""
Paginate Booking.com Milan search and upsert unique listings into DuckDB.

Booking often repeats the first page if you only click Next, and it usually
won't expose all ~3.7k properties in one unfiltered list. We:

1) navigate by offset (full page load)
2) click Load more / Next when present
3) split by property type, stars, and price so more hotels become visible
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime
from urllib.parse import urlencode

import pandas as pd
from playwright.async_api import async_playwright

from config import describe_proxy, playwright_proxy
from warehouse import existing_listing_urls, summary, upsert_search_listings

CITY = "Milan"
DEST_ID = "-121726"
PAGE_SIZE = 25
MAX_OFFSET = 100
PAUSE_MS = 2200
STALE_TO_STOP = 2

# One night only: 24 Sep 2026
CIN = date(2026, 9, 24)
COUT = date(2026, 9, 25)
ADULTS = 1

# Overlaps are fine; we dedupe on property_url.
SLICES = [None]
SLICES += [f"ht_id={x}" for x in (201, 203, 204, 206, 208, 212, 213, 216, 219, 220, 221, 222, 223)]
SLICES += [f"class={x}" for x in (1, 2, 3, 4, 5)]
SLICES += [
    f"price=GBP-{lo}-{hi}-1"
    for lo, hi in (
        (0, 70),
        (70, 110),
        (110, 160),
        (160, 220),
        (220, 300),
        (300, 450),
        (450, 700),
        (700, 1200),
        (1200, 5000),
    )
]


def search_url(offset: int = 0, nflt: str | None = None) -> str:
    params = {
        "ss": CITY,
        "ssne": CITY,
        "ssne_untouched": CITY,
        "dest_id": DEST_ID,
        "dest_type": "city",
        "checkin": CIN.isoformat(),
        "checkout": COUT.isoformat(),
        "group_adults": ADULTS,
        "no_rooms": 1,
        "group_children": 0,
        "selected_currency": "GBP",
        "lang": "en-gb",
        "sb_price_type": "total",
        "offset": str(offset),
        "rows": str(PAGE_SIZE),
    }
    if nflt:
        params["nflt"] = nflt
    return "https://www.booking.com/searchresults.en-gb.html?" + urlencode(params)


def text_or_none(s: str | None) -> str | None:
    if not s:
        return None
    t = " ".join(s.split())
    return t or None


async def accept_cookies(page):
    for sel in (
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
    ):
        try:
            if await page.is_visible(sel, timeout=1200):
                await page.click(sel)
                break
        except Exception:
            pass


async def safe_scroll(page, times: int = 10):
    for _ in range(times):
        try:
            await page.evaluate(
                """() => {
                    if (document.body) window.scrollBy(0, document.body.scrollHeight || 1400);
                    else window.scrollBy(0, 1400);
                }"""
            )
        except Exception:
            break
        await page.wait_for_timeout(250)


def is_blocked(html: str) -> bool:
    return bool(
        re.search(
            r"verify you|security check|are you a robot|captcha|challenge-platform|"
            r"access denied|unusual traffic",
            html,
            re.I,
        )
    )


def parse_taxes(text: str | None) -> str | None:
    blob = text or ""
    if not blob.strip():
        return None
    if re.search(r"includes?\s+taxes(?:\s+and\s+(?:charges|fees))?", blob, re.I):
        return "Included"
    if re.search(r"taxes?\s+and\s+(?:charges|fees)\s+included", blob, re.I):
        return "Included"
    tax_m = re.search(
        r"\+?\s*£\s*([\d,]+(?:\.\d{2})?)\s*taxes(?:\s+and\s+(?:charges|fees))?",
        blob,
        re.I,
    )
    if tax_m:
        return f"+£{tax_m.group(1)} taxes and fees"
    return None


def parse_card_text(raw: str | None) -> dict:
    text = raw or ""
    pounds = re.findall(r"£\s*([\d,]+(?:\.\d{2})?)", text)
    prices = [f"£{p}" for p in pounds]
    tax_m = re.search(
        r"\+?\s*£\s*([\d,]+(?:\.\d{2})?)\s*taxes(?:\s+and\s+(?:charges|fees))?",
        text,
        re.I,
    )
    if tax_m and prices:
        tax_val = f"£{tax_m.group(1)}"
        prices = [p for p in prices if p != tax_val]
    left_m = re.search(
        r"(we have\s+\d+\s+left[^\n]*|only\s+\d+\s+left[^\n]*|\d+\s+left at this price)",
        text,
        re.I,
    )
    score_m = re.search(
        r"\b(\d(?:\.\d)?)\s+(Good|Very good|Fabulous|Superb|Excellent|Exceptional)\b",
        text,
        re.I,
    )
    count_m = re.search(r"([\d,]+)\s+reviews", text, re.I)
    bed_m = re.search(
        r"(\d+\s+(?:extra[- ]large\s+)?(?:large\s+)?(?:twin|double|single|king|queen|sofa|bunk)?\s*beds?)",
        text,
        re.I,
    )
    nights_m = re.search(r"(\d+)\s+night", text, re.I)
    adults_m = re.search(r"(\d+)\s+adult", text, re.I)
    room_m = re.search(
        r"(Economy Single Room|Standard Single Room|Single Room|Double Room|Twin Room|"
        r"Quadruple Room|Family Room|Deluxe Room|Superior Room|Studio|Apartment|Suite)",
        text,
        re.I,
    )
    area_m = re.search(r"([^\n]+,\s*Milan)", text, re.I)
    return {
        "price_original": prices[0] if len(prices) >= 2 else None,
        "price_current": prices[-1] if prices else None,
        "taxes_fees": parse_taxes(text),
        "rooms_left_hint": text_or_none(left_m.group(0)) if left_m else None,
        "review_score": score_m.group(1) if score_m else None,
        "review_word": score_m.group(2) if score_m else None,
        "review_count": count_m.group(1).replace(",", "") if count_m else None,
        "bed_info": text_or_none(bed_m.group(1)) if bed_m else None,
        "room_type": text_or_none(room_m.group(0)) if room_m else None,
        "neighbourhood": text_or_none(area_m.group(1)) if area_m else None,
        "nights_from_card": int(nights_m.group(1)) if nights_m else None,
        "adults_from_card": int(adults_m.group(1)) if adults_m else None,
        "genius": bool(re.search(r"\bgenius\b", text, re.I)),
        "sustainability": "Sustainability certification"
        if re.search(r"sustainability", text, re.I)
        else None,
        "members_only_price": bool(re.search(r"members-only|sign in for this", text, re.I)),
    }


async def extract_cards(page) -> list[dict]:
    cards = page.locator("[data-testid='property-card'], [data-testid='property-card-container']")
    n = await cards.count()
    rows = []
    for i in range(n):
        card = cards.nth(i)

        async def grab(sel, root=card):
            el = root.locator(sel).first
            if await el.count():
                return text_or_none(await el.inner_text())
            return None

        title = await grab("[data-testid='title']")
        score = await grab("[data-testid='review-score']")
        if not score:
            score = await grab("[data-testid='review-score-link']")
        price = await grab("[data-testid='price-and-discounted-price']")
        if not price:
            price = await grab("span:has-text('£')")
        tax_dom = await grab("[data-testid='taxes-and-charges']")
        if not tax_dom:
            tax_dom = await grab("[data-testid='price-taxes-and-charges']")
        distance = await grab("[data-testid='distance']")
        neighbourhood = await grab("[data-testid='address']")
        room_type = await grab(
            "[data-testid='recommended-units'] [data-testid='title'], "
            "[data-testid='property-card-unit-name']"
        )
        url = None
        link = card.locator("a[data-testid='title-link'], a[href*='/hotel/']").first
        if await link.count():
            href = await link.get_attribute("href")
            if href:
                url = href.split("?")[0]
                if url.startswith("/"):
                    url = "https://www.booking.com" + url
        if not url:
            continue
        sponsored = await card.locator("text=/Sponsored|Ad\\b/i").count() > 0
        avail = await grab("[data-testid='availability-cta']")

        stars = None
        stars_el = card.locator("[data-testid='rating-stars'], [data-testid='rating-squares']").first
        if await stars_el.count():
            label = await stars_el.get_attribute("aria-label")
            m = re.search(r"(\d+)", label or "")
            if m:
                stars = int(m.group(1))
            else:
                n_icons = await stars_el.locator("span, svg").count()
                stars = n_icons or None

        card_text = text_or_none(await card.inner_text())
        parsed = parse_card_text(card_text)
        rows.append(
            {
                "title": title,
                "price": parsed.get("price_current") or price,
                "distance": distance,
                "review_block": score,
                "property_url": url,
                "sponsored": sponsored,
                "availability_hint": avail or parsed.get("rooms_left_hint"),
                "check_in": CIN.isoformat(),
                "check_out": COUT.isoformat(),
                "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "stars": stars,
                "genius": parsed.get("genius"),
                "review_score": parsed.get("review_score"),
                "review_word": parsed.get("review_word"),
                "review_count": parsed.get("review_count"),
                "neighbourhood": neighbourhood or parsed.get("neighbourhood"),
                "sustainability": parsed.get("sustainability"),
                "room_type": parsed.get("room_type") or room_type,
                "bed_info": parsed.get("bed_info"),
                "rooms_left_hint": parsed.get("rooms_left_hint"),
                "nights": parsed.get("nights_from_card") or (COUT - CIN).days,
                "adults": parsed.get("adults_from_card") or ADULTS,
                "price_original": parsed.get("price_original"),
                "price_current": parsed.get("price_current") or price,
                "taxes_fees": parsed.get("taxes_fees") or parse_taxes(tax_dom) or tax_dom,
                "members_only_price": parsed.get("members_only_price"),
                "card_text": card_text,
            }
        )
    return rows


async def click_load_more_or_next(page) -> bool:
    for sel in (
        "button:has-text('Load more results')",
        "button:has-text('See more results')",
        "button:has-text('Load more')",
        'button[aria-label="Next page"]',
        'a[aria-label="Next page"]',
        'button:has-text("Next")',
    ):
        btn = page.locator(sel).last
        try:
            if not await btn.count():
                continue
            if not await btn.is_enabled():
                continue
            aria = await btn.get_attribute("aria-disabled")
            if aria == "true":
                continue
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await page.wait_for_timeout(PAUSE_MS)
            return True
        except Exception:
            continue
    return False


async def open_browser(p):
    launch_kwargs = {"headless": True}
    proxy = playwright_proxy()
    if proxy:
        launch_kwargs["proxy"] = proxy
    browser = await p.chromium.launch(**launch_kwargs)
    context = await browser.new_context(
        locale="en-GB",
        timezone_id="Europe/London",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1360, "height": 900},
    )
    page = await context.new_page()
    return browser, page


async def harvest_page(page, seen: set[str]) -> tuple[int, bool]:
    html = await page.content()
    if is_blocked(html):
        print("  captcha / bot check", flush=True)
        return (0, True)
    await safe_scroll(page, 10)
    cards = await extract_cards(page)
    new_unique = 0
    if cards:
        upsert_search_listings(pd.DataFrame(cards), city=CITY)
        for r in cards:
            url = r.get("property_url")
            if url and url not in seen:
                seen.add(url)
                new_unique += 1
    return (new_unique, False)


async def print_booking_total(page) -> str | None:
    await page.goto(search_url(0), wait_until="domcontentloaded", timeout=45000)
    await accept_cookies(page)
    await page.wait_for_timeout(PAUSE_MS)
    header = None
    for sel in ("h1", "[data-testid='property-list-header']"):
        el = page.locator(sel).first
        if await el.count():
            header = text_or_none(await el.inner_text())
            if header:
                break
    n = None
    if header:
        m = re.search(r"([\d,]+)\s+propert", header, re.I)
        if m:
            n = m.group(1).replace(",", "")
    if n:
        print(f"Booking.com total properties found: {n}", flush=True)
        print(f"Header: {header}", flush=True)
    else:
        print(f"Booking.com total properties found: (not parsed) header={header!r}", flush=True)
    return header


async def scrape_slice(page, nflt: str | None, seen: set[str]) -> bool:
    label = nflt or "all"
    print(f"\n--- slice {label} | unique so far {len(seen)} ---", flush=True)
    stale = 0
    blocked = False
    for offset in range(0, MAX_OFFSET + PAGE_SIZE, PAGE_SIZE):
        await page.goto(search_url(offset, nflt), wait_until="domcontentloaded", timeout=45000)
        await accept_cookies(page)
        await page.wait_for_timeout(PAUSE_MS)
        new_n, blocked = await harvest_page(page, seen)
        print(f"  offset={offset} new={new_n} unique={len(seen)}", flush=True)
        if blocked:
            return True
        if new_n == 0:
            clicked = await click_load_more_or_next(page)
            if clicked:
                extra, blocked = await harvest_page(page, seen)
                print(f"  load-more extra={extra} unique={len(seen)}", flush=True)
                if blocked:
                    return True
                if extra:
                    stale = 0
                    continue
            stale += 1
            if stale >= STALE_TO_STOP:
                break
        else:
            stale = 0
    return False


async def main():
    print(
        f"Milan listings -> DuckDB | {CIN} to {COUT} | adults={ADULTS} | proxy={describe_proxy()}",
        flush=True,
    )
    seen = existing_listing_urls(CITY, CIN.isoformat())
    print(f"Already in DB for this stay: {len(seen)}", flush=True)

    async with async_playwright() as p:
        browser, page = await open_browser(p)
        try:
            print("Opening Milan search (before load)...", flush=True)
            await print_booking_total(page)
            for nflt in SLICES:
                blocked = await scrape_slice(page, nflt, seen)
                if blocked:
                    break
        finally:
            await browser.close()

    print(f"\nDone. Unique Milan listings: {len(seen)}", flush=True)
    print("DuckDB totals:", summary(), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
