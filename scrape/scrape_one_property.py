"""
One Booking.com hotel page: name, address + postal code, amenities.

Default: DoubleTree By Hilton Milan, 24 Sep 2026, 1 night, 1 adult.

  python scrape/scrape_one_property.py
  python scrape/scrape_one_property.py --url "https://www.booking.com/hotel/it/doubletree.en-gb.html"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from playwright.async_api import async_playwright

import milan_listings as ml
from listing_columns import ALL_COLS, LISTING_COLS
from config import ROOT

OUT_DIR = ROOT / "outputs"
DEFAULT_URL = "https://www.booking.com/hotel/it/doubletree.en-gb.html"
DEFAULT_CIN = date(2026, 9, 24)
POSTAL_RE = re.compile(r"\b(\d{5})\b")

EXTRACT_JS = r"""
() => {
  const text = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, " ").trim();
  const uniq = (arr) => [...new Set(arr.filter(Boolean))];

  let parsed = [];
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try { parsed.push(JSON.parse(s.textContent)); } catch (e) {}
  }
  const hotels = [];
  const walk = (x) => {
    if (!x) return;
    if (Array.isArray(x)) { x.forEach(walk); return; }
    if (typeof x !== "object") return;
    const t = x["@type"];
    const types = Array.isArray(t) ? t : [t];
    if (types.some((ty) => ty && /Hotel|LodgingBusiness/i.test(String(ty)))) hotels.push(x);
    for (const v of Object.values(x)) if (v && typeof v === "object") walk(v);
  };
  walk(parsed);
  const hotel = hotels[0] || {};
  const addr = hotel.address && typeof hotel.address === "object" && !Array.isArray(hotel.address)
    ? hotel.address
    : {};
  const amenityFeature = Array.isArray(hotel.amenityFeature)
    ? hotel.amenityFeature.map((a) => (a && (a.name || a.value || a)) ).filter(Boolean).map(String)
    : [];

  const name =
    text(document.querySelector("#hp_hotel_name")) ||
    text(document.querySelector("[data-testid='header-title']")) ||
    text(document.querySelector("h2.pp-header__title")) ||
    hotel.name ||
    null;

  const addressDom =
    text(document.querySelector("[data-testid='PropertyHeaderAddressDesktop-address-wrapper']")) ||
    text(document.querySelector("span.hp_address_subtitle")) ||
    text(document.querySelector("[data-testid='address']")) ||
    text(document.querySelector("#showMap2 span.hp_address_subtitle")) ||
    null;

  const popWrap = document.querySelector("[data-testid='property-most-popular-facilities-wrapper']");
  let popular = [];
  if (popWrap) {
    popular = Array.from(popWrap.querySelectorAll("li, [data-testid*='facility']"))
      .map((el) => text(el))
      .filter((t) => t && t.length < 90 && !/most popular|see all|show more/i.test(t));
    if (!popular.length) {
      popular = popWrap.innerText.split("\n").map((t) => t.trim())
        .filter((t) => t && !/most popular|see all|show more/i.test(t));
    }
    popular = uniq(popular);
  }

  const facilities = [];
  const groupSels = [
    "#hp_facilities_box [data-testid='facility-group']",
    "[data-testid='property-facilities-block'] [data-testid='facility-group']",
    "#hp_facilities_box .hotel-facilities-group",
    "[role='dialog'] [data-testid='facility-group']",
  ];
  let groups = [];
  for (const sel of groupSels) {
    groups = Array.from(document.querySelectorAll(sel));
    if (groups.length) break;
  }
  for (const g of groups) {
    const heading = text(g.querySelector("h3, h2, [data-testid='facility-group-name'], .bui-title__text"));
    const items = Array.from(g.querySelectorAll("li, [data-testid='facility']"))
      .map((el) => text(el))
      .filter((t) => t && t !== heading && t.length < 120);
    for (const item of uniq(items)) facilities.push({ group: heading || "Facilities", amenity: item });
  }
  if (!facilities.length) {
    const box = document.querySelector("#hp_facilities_box, [data-testid='property-facilities-block']");
    if (box) {
      for (const t of box.innerText.split("\n").map((x) => x.trim())) {
        if (t && t.length < 80 && !/facilities of|see all|most popular/i.test(t)) {
          facilities.push({ group: "Facilities", amenity: t });
        }
      }
    }
  }

  const dialog = document.querySelector("[role='dialog']");
  let dialogText = dialog ? dialog.innerText : null;

  return {
    name,
    addressDom,
    streetAddress: addr.streetAddress || null,
    addressLocality: addr.addressLocality || null,
    addressRegion: addr.addressRegion || null,
    postalCode: addr.postalCode || null,
    addressCountry: (addr.addressCountry && (addr.addressCountry.name || addr.addressCountry)) || null,
    popular,
    amenityFeature,
    facilities,
    dialogText: dialogText ? dialogText.slice(0, 4000) : null,
    jsonldFound: !!hotels.length,
    reviewScore: (hotel.aggregateRating && (hotel.aggregateRating.ratingValue)) || null,
    reviewCount: (hotel.aggregateRating && (hotel.aggregateRating.reviewCount || hotel.aggregateRating.ratingCount)) || null,
    reviewWord: text(document.querySelector("[data-testid='review-score-word'], [data-testid='review-sub-score']")) || null,
    distance: (() => {
      const el = document.querySelector("[data-testid='distance'], [data-testid='PropertyHeaderAddressDesktop-distance']");
      const fromEl = text(el);
      if (fromEl) return fromEl;
      const m = (document.body.innerText || "").match(/([\d.,]+\s*km from (?:the )?(?:centre|center|Duomo)[^\n]*)/i);
      return m ? m[1].replace(/\s+/g, " ").trim() : null;
    })(),
    stars: (() => {
      const el = document.querySelector("[data-testid='rating-stars'], [data-testid='rating-squares']");
      if (!el) return null;
      const lab = el.getAttribute("aria-label") || "";
      const m = lab.match(/(\d+)/);
      return m ? Number(m[1]) : null;
    })(),
  };
}
"""


def property_url(base: str, cin: date, nights: int, adults: int) -> str:
    cout = cin + timedelta(days=nights)
    sep = "&" if "?" in base else "?"
    return (
        f"{base}{sep}checkin={cin.isoformat()}&checkout={cout.isoformat()}"
        f"&group_adults={adults}&no_rooms=1&group_children=0"
        f"&lang=en-gb&selected_currency=GBP"
    )


def slug_from_url(url: str) -> str:
    m = re.search(r"/hotel/[^/]+/([^/?#]+)", url.lower())
    slug = m.group(1) if m else "property"
    return re.sub(r"\.(?:[a-z]{2}-[a-z]{2})\.html$|\.html$", "", slug)


AMENITY_NOISE = re.compile(
    r"(see availability|missing some information|great facilities|review score|"
    r"^yes$|^/no$|^no$|additional charge|most popular facilities|^show more$)",
    re.I,
)
FACILITY_GROUPS = {
    "outdoors",
    "activities",
    "pets",
    "food & drink",
    "internet",
    "parking",
    "reception services",
    "cleaning services",
    "business facilities",
    "safety & security",
    "general",
    "accessibility",
    "wellness",
    "media & technology",
    "languages spoken",
    "bathroom",
    "bedroom",
    "kitchen",
    "living area",
    "room amenities",
}


def clean_address(raw: str | None) -> str | None:
    if not raw:
        return None
    t = " ".join(raw.split())
    t = re.sub(r"\s*[–—-]\s*(Good location.*|show map.*|Railway access.*)$", "", t, flags=re.I)
    t = re.sub(r"\bshow map\b", "", t, flags=re.I)
    t = t.replace("–", "-").strip(" -")
    return t or None


def parse_it_address(address: str | None) -> dict:
    out = {"street": None, "neighbourhood": None, "postal_code": None, "city": None, "country": None}
    if not address:
        return out
    full = re.match(
        r"^(?P<street>.+?),\s*(?P<neighbourhood>[^,]+),\s*(?P<postal>\d{5})\s+(?P<city>[A-Za-zÀ-ÿ .'-]+),\s*(?P<country>.+)$",
        address,
    )
    if full and not re.search(r"\d{5}", full.group("neighbourhood")):
        out.update(
            {
                "street": full.group("street").strip(),
                "neighbourhood": full.group("neighbourhood").strip(),
                "postal_code": full.group("postal"),
                "city": full.group("city").strip(),
                "country": full.group("country").strip(),
            }
        )
        return out
    short = re.match(
        r"^(?P<street>.+?),\s*(?P<postal>\d{5})\s+(?P<city>[A-Za-zÀ-ÿ .'-]+),\s*(?P<country>.+)$",
        address,
    )
    if short:
        out.update(
            {
                "street": short.group("street").strip(),
                "postal_code": short.group("postal"),
                "city": short.group("city").strip(),
                "country": short.group("country").strip(),
            }
        )
        return out
    out["postal_code"] = postal_from_text(address)
    mcity = re.search(r"\d{5}\s+([A-Za-zÀ-ÿ .'-]+)", address)
    if mcity:
        out["city"] = mcity.group(1).strip()
    return out


def clean_name(name: str | None) -> str | None:
    if not name:
        return None
    t = re.sub(r"^\s*Sustainability certification\s*", "", name, flags=re.I).strip()
    return t or name


def tidy_facilities(rows: list[dict]) -> list[dict]:
    current = "Facilities"
    out = []
    seen = set()
    for row in rows:
        amenity = (row.get("amenity") or "").strip()
        group = (row.get("group") or "Facilities").strip()
        if not amenity or AMENITY_NOISE.search(amenity):
            continue
        if amenity.lower() in FACILITY_GROUPS:
            current = amenity
            continue
        if group.lower() == "facilities":
            group = current
        key = (group, amenity)
        if key in seen:
            continue
        seen.add(key)
        out.append({"group": group, "amenity": amenity})
    return out


def postal_from_text(*parts: str | None) -> str | None:
    blob = " ".join(p for p in parts if p)
    m = POSTAL_RE.search(blob)
    return m.group(1) if m else None


async def open_browser(p):
    launch_kwargs = {"headless": True}
    proxy = ml.playwright_proxy()
    if proxy:
        launch_kwargs["proxy"] = proxy
    try:
        browser = await p.chromium.launch(**launch_kwargs)
    except Exception:
        launch_kwargs["channel"] = "chrome"
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


BED_SELS = (
    "[data-testid='bed-type']",
    "[data-testid='room-bed-info']",
    "[data-testid='bed-configuration']",
    ".hprt-roomtype-bed",
    ".rt-bed-type",
    "ul[class*='bed']",
    "span:has-text('bed')",
)


async def room_bits(root) -> dict:
    blob = ml.text_or_none(await root.inner_text()) or ""
    parsed = ml.parse_card_text(blob)
    title_el = root.locator(
        "[data-testid='room-card-title'], .hprt-roomtype-link, .hprt-roomtype-name"
    ).first
    title = ml.text_or_none(await title_el.inner_text()) if await title_el.count() else None
    price_el = root.locator("[data-testid='price-and-discounted-price']").first
    if not await price_el.count():
        price_el = root.locator(
            ".hprt-price-price-standard, .hprt-price, .bui-price-display__value, span:has-text('£')"
        ).first
    price = ml.text_or_none(await price_el.inner_text()) if await price_el.count() else None
    tax_el = root.locator("[data-testid='taxes-and-charges']").first
    if not await tax_el.count():
        tax_el = root.locator(":text-matches('tax', 'i')").first
    tax = ml.text_or_none(await tax_el.inner_text()) if await tax_el.count() else None
    bed = None
    for sel in BED_SELS:
        el = root.locator(sel).first
        if await el.count():
            bed = ml.text_or_none(await el.inner_text())
            if bed:
                break
    return {
        "room_type": title or parsed.get("room_type"),
        "price_current": parsed.get("price_current") or price,
        "bed_info": bed or parsed.get("bed_info"),
        "taxes_fees": ml.parse_taxes(tax) or ml.parse_taxes(blob) or tax,
    }


async def extract_rooms(page) -> list[dict]:
    rooms = []
    cards = page.locator("[data-testid='room-card']")
    n = await cards.count()
    for i in range(min(n, 8)):
        rooms.append(await room_bits(cards.nth(i)))
    if rooms:
        return rooms
    rows = page.locator("#hprt-form tr.hprt-table-tr, #hprt-form tr.js-rt-block-row")
    hr = await rows.count()
    for i in range(min(hr, 8)):
        rooms.append(await room_bits(rows.nth(i)))
    return rooms


def load_listing_rows(url: str, cin: date) -> list[dict]:
    path = OUT_DIR / "listings_from_duckdb.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    if df.empty or "property_url" not in df.columns:
        return []
    base = url.split("?")[0].rstrip("/").lower()
    df["_u"] = df["property_url"].astype(str).str.split("?").str[0].str.rstrip("/").str.lower()
    hit = df[df["_u"] == base]
    if "check_in" in hit.columns:
        hit = hit[hit["check_in"].astype(str).str.startswith(cin.isoformat())]
    if hit.empty:
        return []
    keys = [c for c in ("property_url", "check_in", "room_type") if c in hit.columns]
    hit = hit.drop_duplicates(subset=keys, keep="last")
    return hit.drop(columns=["_u"], errors="ignore").to_dict("records")


def amenities_text(prop: dict) -> str:
    values = (
        (prop.get("popular_facilities") or [])
        + (prop.get("amenities_jsonld") or [])
        + [x.get("amenity") for x in (prop.get("amenities_grouped") or []) if x.get("amenity")]
    )
    return "; ".join(dict.fromkeys([v for v in values if v]))


def combine_rows(prop: dict, listings: list[dict], rooms: list[dict], cin: date, nights: int, adults: int) -> list[dict]:
    extras = {
        "address": prop.get("address"),
        "street": prop.get("street"),
        "postal_code": prop.get("postal_code"),
        "city": prop.get("city"),
        "country": prop.get("country"),
        "popular_facilities": "; ".join(prop.get("popular_facilities") or []),
        "amenities": amenities_text(prop),
    }
    cout = (cin + timedelta(days=nights)).isoformat()
    if not listings:
        if not rooms:
            rooms = [{}]
        listings = []
        for room in rooms:
            listings.append(
                {
                    "check_in": cin.isoformat(),
                    "check_out": cout,
                    "title": prop.get("name"),
                    "property_url": prop.get("url"),
                    "room_type": room.get("room_type"),
                    "bed_info": room.get("bed_info"),
                    "price_current": room.get("price_current"),
                    "taxes_fees": room.get("taxes_fees"),
                    "review_score": prop.get("review_score"),
                    "review_word": prop.get("review_word"),
                    "review_count": prop.get("review_count"),
                    "distance": prop.get("distance"),
                    "neighbourhood": prop.get("neighbourhood"),
                    "stars": prop.get("stars"),
                    "nights": nights,
                    "adults": adults,
                    "captured_at": prop.get("captured_at"),
                }
            )
    rows = []
    for listing in listings:
        row = {c: listing.get(c) for c in LISTING_COLS}
        row["title"] = prop.get("name") or row.get("title")
        row["property_url"] = prop.get("url") or row.get("property_url")
        row["neighbourhood"] = prop.get("neighbourhood") or row.get("neighbourhood")
        if not row.get("review_score"):
            row["review_score"] = prop.get("review_score")
        if not row.get("review_word"):
            row["review_word"] = prop.get("review_word")
        if not row.get("review_count"):
            row["review_count"] = prop.get("review_count")
        if not row.get("distance"):
            row["distance"] = prop.get("distance")
        if not row.get("stars"):
            row["stars"] = prop.get("stars")
        if not row.get("bed_info"):
            row["bed_info"] = listing.get("bed_info")
        if not row.get("taxes_fees"):
            row["taxes_fees"] = listing.get("taxes_fees")
        row.update(extras)
        rows.append({c: row.get(c) for c in ALL_COLS})
    return rows


async def first_text(page, *sels: str) -> str | None:
    for sel in sels:
        el = page.locator(sel).first
        try:
            if await el.count():
                t = ml.text_or_none(await el.inner_text())
                if t:
                    return t
        except Exception:
            continue
    return None


async def open_facilities_modal(page) -> None:
    for sel in (
        "button:has-text('See all facilities')",
        "a:has-text('See all facilities')",
        "button:has-text('See all')",
        "[data-testid='facilities-see-more']",
        "button:has-text('Show all facilities')",
    ):
        btn = page.locator(sel).first
        try:
            if await btn.count() and await btn.is_visible():
                await btn.scroll_into_view_if_needed()
                await btn.click(timeout=4000)
                await page.wait_for_timeout(1500)
                return
        except Exception:
            continue


async def scrape(page, url: str, *, details_only: bool = False) -> dict:
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await ml.accept_cookies(page)
    await page.wait_for_timeout(2500)
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    html = await page.content()
    if ml.is_blocked(html):
        return {"blocked": True, "url": page.url}

    await ml.safe_scroll(page, 8)
    await page.wait_for_timeout(800)
    data = await page.evaluate(EXTRACT_JS)
    popular = data.get("popular") or []
    facilities = data.get("facilities") or []
    amenity_feature = data.get("amenityFeature") or []
    rooms: list[dict] = []
    extra = data
    if not details_only:
        rooms = await extract_rooms(page)
        await open_facilities_modal(page)
        extra = await page.evaluate(EXTRACT_JS)
        extra_fac = extra.get("facilities") or []
        if len(extra_fac) > len(facilities):
            facilities = extra_fac
        if extra.get("amenityFeature"):
            amenity_feature = extra.get("amenityFeature")
        if not popular:
            popular = extra.get("popular") or []

    address = clean_address(
        extra.get("addressDom")
        or data.get("addressDom")
        or extra.get("streetAddress")
        or data.get("streetAddress")
    )
    parsed_addr = parse_it_address(address)
    street = parsed_addr.get("street")
    if not street or re.search(r"\d{5}", street):
        raw_street = extra.get("streetAddress") or data.get("streetAddress")
        if raw_street and not re.search(r"\d{5}", str(raw_street)):
            street = raw_street
        elif not street:
            street = raw_street
    city = parsed_addr.get("city")
    loc = extra.get("addressLocality") or data.get("addressLocality")
    if not city and loc and not re.match(r"(?i)(via|viale|piazza|corso)\b", str(loc)):
        city = loc
    neighbourhood = parsed_addr.get("neighbourhood")
    region = extra.get("addressRegion") or data.get("addressRegion")
    country = parsed_addr.get("country") or extra.get("addressCountry") or data.get("addressCountry")
    postal = (
        parsed_addr.get("postal_code")
        or extra.get("postalCode")
        or data.get("postalCode")
        or postal_from_text(address, street, city)
    )

    if address and postal and postal not in address:
        address = f"{address}, {postal}"

    name = extra.get("name") or data.get("name") or await first_text(
        page, "#hp_hotel_name", "[data-testid='header-title']", "h2.pp-header__title"
    )
    name = clean_name(name)
    facilities = tidy_facilities(facilities)
    popular = [a for a in popular if a and not AMENITY_NOISE.search(a)]

    return {
        "blocked": False,
        "url": page.url.split("?")[0],
        "name": name,
        "address": address,
        "street": street,
        "neighbourhood": neighbourhood,
        "city": city,
        "region": region,
        "postal_code": postal,
        "country": country,
        "popular_facilities": popular,
        "amenities_jsonld": amenity_feature,
        "amenities_grouped": facilities,
        "rooms": rooms,
        "review_score": extra.get("reviewScore") or data.get("reviewScore"),
        "review_word": extra.get("reviewWord") or data.get("reviewWord"),
        "review_count": extra.get("reviewCount") or data.get("reviewCount"),
        "distance": extra.get("distance") or data.get("distance"),
        "stars": extra.get("stars") or data.get("stars"),
        "jsonld_found": extra.get("jsonldFound") or data.get("jsonldFound"),
        "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def save(prop: dict, rows: list[dict], slug: str) -> tuple[Path, Path, Path]:
    OUT_DIR.mkdir(exist_ok=True)
    json_path = OUT_DIR / f"property_{slug}.json"
    payload = {**prop, "rows": rows}
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    df = pd.DataFrame(rows)
    for c in ALL_COLS:
        if c not in df.columns:
            df[c] = None
    df = df[ALL_COLS]
    csv_path = OUT_DIR / f"property_{slug}.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    amenity_rows = []
    for a in prop.get("popular_facilities") or []:
        amenity_rows.append({"source": "most_popular", "group": "Most popular facilities", "amenity": a})
    for a in prop.get("amenities_jsonld") or []:
        amenity_rows.append({"source": "jsonld", "group": "amenityFeature", "amenity": a})
    for x in prop.get("amenities_grouped") or []:
        amenity_rows.append({"source": "facilities_section", "group": x.get("group"), "amenity": x.get("amenity")})
    xlsx_path = OUT_DIR / f"property_{slug}.xlsx"
    with pd.ExcelWriter(xlsx_path) as writer:
        df.to_excel(writer, index=False, sheet_name="listing")
        pd.DataFrame(amenity_rows).drop_duplicates().to_excel(writer, index=False, sheet_name="amenities")
    return json_path, csv_path, xlsx_path


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--from-date", default=DEFAULT_CIN.isoformat())
    parser.add_argument("--nights", type=int, default=1)
    parser.add_argument("--adults", type=int, default=1)
    args = parser.parse_args()
    cin = date.fromisoformat(args.from_date)
    url = property_url(args.url, cin, args.nights, args.adults)
    slug = slug_from_url(args.url)

    print(f"One property | {args.url} | {cin} | nights={args.nights} | adults={args.adults} | proxy={ml.describe_proxy()}", flush=True)

    async with async_playwright() as p:
        browser, page = await open_browser(p)
        try:
            prop = await scrape(page, url)
        finally:
            await browser.close()

    if prop.get("blocked"):
        print("Captcha / bot check. Partial: none saved.", flush=True)
        return

    listings = load_listing_rows(args.url, cin)
    rows = combine_rows(prop, listings, prop.get("rooms") or [], cin, args.nights, args.adults)
    json_path, csv_path, xlsx_path = save(prop, rows, slug)
    print(f"Name:     {prop.get('name')}", flush=True)
    print(f"Address:  {prop.get('address')}", flush=True)
    print(f"Postal:   {prop.get('postal_code')}", flush=True)
    print(f"Tax:      {(rows[0].get('taxes_fees') if rows else None)}", flush=True)
    print(f"Listing rows merged: {len(listings)} | output rows: {len(rows)}", flush=True)
    print(f"Columns:  {', '.join(ALL_COLS)}", flush=True)
    print(f"Popular:  {prop.get('popular_facilities')}", flush=True)
    print(f"JSON  {json_path}", flush=True)
    print(f"CSV   {csv_path}", flush=True)
    print(f"Excel {xlsx_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
