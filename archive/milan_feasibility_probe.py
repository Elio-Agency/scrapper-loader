"""
Milan feasibility probe — inspect what Booking.com exposes on:
1) city search/results
2) property detail / room rates
No warehouse storage in the probe itself; results can be loaded into DuckDB via load_warehouse.py.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

from config import describe_proxy, playwright_proxy
from warehouse import ingest_feasibility_json

OUT = Path("milan_probe")
OUT.mkdir(exist_ok=True)

CIN = date.today() + timedelta(days=14)
COUT = CIN + timedelta(days=2)

MILAN_SEARCH = (
    "https://www.booking.com/searchresults.en-gb.html?"
    + urlencode(
        {
            "ss": "Milan",
            "ssne": "Milan",
            "ssne_untouched": "Milan",
            "dest_type": "city",
            "checkin": CIN.isoformat(),
            "checkout": COUT.isoformat(),
            "group_adults": 2,
            "no_rooms": 1,
            "group_children": 0,
            "selected_currency": "GBP",
            "lang": "en-gb",
        }
    )
)


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
        "button:has-text('I Agree')",
    ):
        try:
            if await page.is_visible(sel, timeout=1500):
                await page.click(sel)
                break
        except Exception:
            pass


async def safe_scroll(page, times: int = 6):
    for _ in range(times):
        try:
            await page.evaluate(
                """() => {
                    if (document.body) {
                        window.scrollBy(0, document.body.scrollHeight || 1200);
                    } else {
                        window.scrollBy(0, 1200);
                    }
                }"""
            )
        except Exception:
            break
        await page.wait_for_timeout(400)


async def page_signals(page) -> dict:
    html = ""
    try:
        html = await page.content()
    except Exception as e:
        html = f"<!-- content_error: {e} -->"
    title = ""
    try:
        title = await page.title()
    except Exception:
        pass
    return {
        "title": title,
        "url": page.url,
        "html_len": len(html),
        "captcha": bool(
            re.search(
                r"verify you|security check|are you a robot|captcha|challenge-platform",
                html,
                re.I,
            )
        ),
        "blocked_hint": bool(
            re.search(r"access denied|unusual traffic|pardon our interruption", html, re.I)
        ),
        "html_snippet": re.sub(r"\s+", " ", html)[:500],
        "html": html,
    }


async def probe_search(page) -> dict:
    try:
        await page.goto(MILAN_SEARCH, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        sig = await page_signals(page)
        (OUT / "milan_search.html").write_text(sig["html"], encoding="utf-8")
        try:
            await page.screenshot(path=str(OUT / "milan_search.png"), full_page=False)
        except Exception:
            pass
        return {
            "url_final": page.url,
            "goto_error": str(e),
            "captcha": sig["captcha"],
            "blocked_hint": sig["blocked_hint"],
            "page_title": sig["title"],
            "html_len": sig["html_len"],
            "html_snippet": sig["html_snippet"],
            "property_cards_found": 0,
            "hotel_link_count": 0,
            "result_header": None,
            "field_presence_in_first_n": {},
            "sample_cards": [],
        }

    await accept_cookies(page)
    await page.wait_for_timeout(3000)
    await safe_scroll(page, 6)

    try:
        await page.screenshot(path=str(OUT / "milan_search.png"), full_page=False)
    except Exception:
        pass
    sig = await page_signals(page)
    html = sig["html"]
    (OUT / "milan_search.html").write_text(html, encoding="utf-8")

    captcha = sig["captcha"]
    cards = page.locator(
        "[data-testid='property-card'], [data-testid='property-card-container']"
    )
    n = await cards.count()
    hotel_links = page.locator("a[href*='/hotel/it/']")
    hotel_link_count = await hotel_links.count()

    sample = []
    field_presence = {
        "title": 0,
        "address": 0,
        "review_score": 0,
        "price": 0,
        "distance": 0,
        "stars_or_rating": 0,
        "property_url": 0,
        "badge_sponsored": 0,
        "availability_nudge": 0,
    }

    for i in range(min(n, 12)):
        card = cards.nth(i)

        async def grab(sel, root=card):
            el = root.locator(sel).first
            if await el.count():
                return text_or_none(await el.inner_text())
            return None

        title = await grab("[data-testid='title']")
        address = await grab("[data-testid='address']")
        score = await grab("[data-testid='review-score']")
        if not score:
            score = await grab("[data-testid='review-score-link']")
        price = await grab("[data-testid='price-and-discounted-price']")
        if not price:
            price = await grab("span:has-text('£')")
        distance = await grab("[data-testid='distance']")
        stars = await grab("[data-testid='rating-stars'], [data-testid='rating-squares']")
        url = None
        link = card.locator("a[data-testid='title-link'], a[href*='/hotel/']").first
        if await link.count():
            href = await link.get_attribute("href")
            if href:
                url = href.split("?")[0]
                if url.startswith("/"):
                    url = "https://www.booking.com" + url

        sponsored = await card.locator("text=/Sponsored|Ad\\b/i").count() > 0
        avail = await grab("[data-testid='availability-cta'], [data-testid='availability']")
        if not avail:
            for phrase in ("Only ", "left at", "booked", "rooms left"):
                if await card.locator(f"text=/{phrase}/i").count():
                    avail = phrase
                    break

        sample.append(
            {
                "title": title,
                "address": address,
                "review_block": score,
                "price": price,
                "distance": distance,
                "stars_block": stars,
                "property_url": url,
                "sponsored": sponsored,
                "availability_hint": avail,
            }
        )
        if title:
            field_presence["title"] += 1
        if address:
            field_presence["address"] += 1
        if score:
            field_presence["review_score"] += 1
        if price:
            field_presence["price"] += 1
        if distance:
            field_presence["distance"] += 1
        if stars:
            field_presence["stars_or_rating"] += 1
        if url:
            field_presence["property_url"] += 1
        if sponsored:
            field_presence["badge_sponsored"] += 1
        if avail:
            field_presence["availability_nudge"] += 1

    if not sample and hotel_link_count:
        seen = set()
        for i in range(min(hotel_link_count, 20)):
            href = await hotel_links.nth(i).get_attribute("href")
            if not href:
                continue
            clean = href.split("?")[0]
            if clean.startswith("/"):
                clean = "https://www.booking.com" + clean
            if clean in seen:
                continue
            seen.add(clean)
            title = text_or_none(await hotel_links.nth(i).inner_text())
            sample.append(
                {
                    "title": title,
                    "address": None,
                    "review_block": None,
                    "price": None,
                    "distance": None,
                    "stars_block": None,
                    "property_url": clean,
                    "sponsored": False,
                    "availability_hint": None,
                    "source": "hotel_link_fallback",
                }
            )
            if title:
                field_presence["title"] += 1
            field_presence["property_url"] += 1

    result_count_text = None
    for sel in ("h1", "[data-testid='property-list-header']"):
        el = page.locator(sel).first
        if await el.count():
            t = text_or_none(await el.inner_text())
            if t and ("propert" in t.lower() or "milan" in t.lower() or "milano" in t.lower()):
                result_count_text = t[:200]
                break

    return {
        "url_final": page.url,
        "captcha": captcha,
        "blocked_hint": sig["blocked_hint"],
        "page_title": sig["title"],
        "html_len": sig["html_len"],
        "html_snippet": sig["html_snippet"],
        "property_cards_found": n,
        "hotel_link_count": hotel_link_count,
        "result_header": result_count_text,
        "field_presence_in_first_n": field_presence,
        "sample_cards": sample,
    }


async def probe_property(page, url: str, label: str) -> dict:
    sep = "&" if "?" in url else "?"
    full = (
        f"{url}{sep}checkin={CIN.isoformat()}&checkout={COUT.isoformat()}"
        f"&group_adults=2&no_rooms=1&group_children=0"
        f"&sb_price_type=total&lang=en-gb&selected_currency=GBP"
    )
    try:
        await page.goto(full, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        sig = await page_signals(page)
        (OUT / f"{label}.html").write_text(sig["html"], encoding="utf-8")
        return {
            "requested_url": url,
            "final_url": page.url,
            "goto_error": str(e),
            "captcha": sig["captcha"],
            "blocked_hint": sig["blocked_hint"],
            "redirected_off_property": "/hotel/" not in page.url,
            "name": None,
            "address": None,
            "review": None,
            "stars": None,
            "room_card_count": 0,
            "hprt_row_count": 0,
            "rooms_sample": [],
            "facilities_section_present": False,
            "map_entry_present": False,
            "policies_section_present": False,
            "jsonld_types": [],
            "html_snippet": sig["html_snippet"],
        }

    await accept_cookies(page)
    await page.wait_for_timeout(2500)
    await safe_scroll(page, 5)

    try:
        await page.screenshot(path=str(OUT / f"{label}.png"), full_page=False)
    except Exception:
        pass
    sig = await page_signals(page)
    html = sig["html"]
    (OUT / f"{label}.html").write_text(html, encoding="utf-8")

    captcha = sig["captcha"]
    redirected = "/hotel/" not in page.url

    async def first_text(*sels):
        for sel in sels:
            el = page.locator(sel).first
            if await el.count():
                t = text_or_none(await el.inner_text())
                if t:
                    return t
        return None

    name = await first_text("#hp_hotel_name", "h2.pp-header__title", "h2", "h1")
    address = await first_text(
        "[data-testid='PropertyHeaderAddressDesktop-address-wrapper']",
        "#showMap2",
        "span.hp_address_subtitle",
    )
    review = await first_text(
        "[data-testid='review-score-component']",
        "[data-testid='review-score-right-component']",
        "#reviewScoreRightComponent",
    )
    stars = await first_text(
        "[data-testid='rating-stars']",
        "[data-testid='rating-squares']",
        "span.bui-rating",
    )

    room_cards = page.locator("[data-testid='room-card']")
    rc = await room_cards.count()
    rooms = []
    for i in range(min(rc, 8)):
        card = room_cards.nth(i)
        title_el = card.locator("[data-testid='room-card-title']").first
        title = text_or_none(await title_el.inner_text()) if await title_el.count() else None
        price_el = card.locator("[data-testid='price-and-discounted-price']").first
        if not await price_el.count():
            price_el = card.locator("span:has-text('£')").first
        price = text_or_none(await price_el.inner_text()) if await price_el.count() else None
        sold = await card.locator("text=/sold out|unavailable|fully booked|not available/i").count() > 0
        rooms.append({"layout": "room-card", "name": title, "price": price, "sold_out": sold})

    hprt_rows = page.locator("#hprt-form tr.hprt-table-tr, #hprt-form tr.js-rt-block-row")
    hr = await hprt_rows.count()
    for i in range(min(hr, 8)):
        row = hprt_rows.nth(i)
        name_el = row.locator(".hprt-roomtype-link, .hprt-roomtype-name").first
        rname = text_or_none(await name_el.inner_text()) if await name_el.count() else None
        price_el = row.locator(
            ".hprt-price-price-standard, .hprt-price, .bui-price-display__value"
        ).first
        if not await price_el.count():
            price_el = row.locator("span:has-text('£')").first
        price = text_or_none(await price_el.inner_text()) if await price_el.count() else None
        sold = await row.locator("text=/sold out|unavailable|fully booked|not available/i").count() > 0
        rooms.append({"layout": "hprt", "name": rname, "price": price, "sold_out": sold})

    facilities_present = (
        await page.locator(
            "[data-testid='property-most-popular-facilities-wrapper'], "
            "[data-testid='property-highlights'], #property_description_content, .hp_desc_main_content"
        ).count()
        > 0
    )
    map_present = (
        await page.locator(
            "#hotel_sidebar_static_map, [data-testid='map-entry-point'], a:has-text('Show on map')"
        ).count()
        > 0
    )
    policies = (
        await page.locator(
            "#hp_policies_box, [data-testid='property-section--content'], #hotelPoliciesInc"
        ).count()
        > 0
    )

    jsonld = []
    for el in await page.locator('script[type="application/ld+json"]').all():
        raw = await el.inner_text()
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                jsonld.append({"@type": data.get("@type"), "keys": sorted(list(data.keys()))[:30]})
            elif isinstance(data, list) and data and isinstance(data[0], dict):
                jsonld.append(
                    {"@type": data[0].get("@type"), "keys": sorted(list(data[0].keys()))[:30]}
                )
        except Exception:
            pass

    return {
        "requested_url": url,
        "final_url": page.url,
        "captcha": captcha,
        "blocked_hint": sig["blocked_hint"],
        "redirected_off_property": redirected,
        "page_title": sig["title"],
        "html_len": sig["html_len"],
        "name": name,
        "address": address,
        "review": review,
        "stars": stars,
        "room_card_count": rc,
        "hprt_row_count": hr,
        "rooms_sample": rooms,
        "facilities_section_present": facilities_present,
        "map_entry_present": map_present,
        "policies_section_present": policies,
        "jsonld_types": jsonld,
    }


async def main():
    report = {
        "scope": "Milan feasibility",
        "checkin": CIN.isoformat(),
        "checkout": COUT.isoformat(),
        "search_url_template": MILAN_SEARCH,
    }

    async with async_playwright() as p:
        print(f"Proxy: {describe_proxy()}", flush=True)
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

        print("Probing Milan search...", flush=True)
        search = await probe_search(page)
        report["search"] = search
        print(
            f"Search cards={search['property_cards_found']} links={search.get('hotel_link_count')} "
            f"captcha={search['captcha']} title={search.get('page_title')!r}",
            flush=True,
        )

        targets = []
        for c in search.get("sample_cards") or []:
            if c.get("property_url") and not c.get("sponsored"):
                targets.append(c["property_url"])
            if len(targets) >= 2:
                break
        if not targets:
            targets = [
                "https://www.booking.com/hotel/it/nh-milano-congress-centre.en-gb.html",
                "https://www.booking.com/hotel/it/milan-marriott.en-gb.html",
            ]

        props = []
        for i, url in enumerate(targets):
            print(f"Probing property {i+1}: {url}", flush=True)
            props.append(await probe_property(page, url, f"property_{i+1}"))
            print(
                f"  name={props[-1].get('name')!r} rooms={props[-1]['room_card_count']}+{props[-1]['hprt_row_count']} "
                f"captcha={props[-1]['captcha']}",
                flush=True,
            )
        report["properties"] = props
        await browser.close()

    search_ok = (report["search"]["property_cards_found"] or 0) > 0 and not report["search"]["captcha"]
    link_ok = (report["search"].get("hotel_link_count") or 0) > 0 and not report["search"]["captcha"]
    prop_ok = any(
        (not p["captcha"])
        and (not p["redirected_off_property"])
        and (p["room_card_count"] + p["hprt_row_count"] > 0 or p["name"])
        for p in report["properties"]
    )
    rooms_with_price = sum(
        1
        for p in report["properties"]
        for r in p["rooms_sample"]
        if r.get("price") and not r.get("sold_out")
    )

    report["verdict"] = {
        "milan_search_cards_scrapable": search_ok,
        "milan_hotel_urls_discoverable": search_ok or link_ok,
        "property_page_scrapable": prop_ok,
        "room_prices_observed": rooms_with_price > 0,
        "notes": [],
    }
    if report["search"]["captcha"] or report["search"].get("blocked_hint"):
        report["verdict"]["notes"].append("Search hit captcha/bot check or block page")
    if any(p["captcha"] or p.get("blocked_hint") for p in report["properties"]):
        report["verdict"]["notes"].append("Property page hit captcha/bot check or block page")
    if not (search_ok or link_ok):
        report["verdict"]["notes"].append("Could not enumerate Milan hotels from search")
    if rooms_with_price == 0:
        report["verdict"]["notes"].append(
            "No priced rooms observed in property samples (sold out / layout miss / block)"
        )

    out_json = OUT / "milan_feasibility_report.json"
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    listings_n, rooms_n = ingest_feasibility_json(out_json)
    print(f"\nWrote {out_json}", flush=True)
    print(f"DuckDB: listings={listings_n} rooms={rooms_n}", flush=True)
    print(json.dumps(report["verdict"], indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
