"""DuckDB warehouse for scrape outputs."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from config import ROOT, duckdb_path


def connect() -> duckdb.DuckDBPyConnection:
    path = duckdb_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS quotes (
            property_slug VARCHAR,
            check_in VARCHAR,
            check_out VARCHAR,
            nights INTEGER,
            room_name_raw VARCHAR,
            status VARCHAR,
            price_text VARCHAR,
            total_gbp DOUBLE,
            nightly_gbp DOUBLE,
            url VARCHAR,
            captured_at VARCHAR,
            source VARCHAR,
            ingested_at VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS search_listings (
            title VARCHAR,
            price VARCHAR,
            distance VARCHAR,
            review_block VARCHAR,
            property_url VARCHAR,
            sponsored BOOLEAN,
            availability_hint VARCHAR,
            check_in VARCHAR,
            check_out VARCHAR,
            captured_at VARCHAR,
            ingested_at VARCHAR,
            city VARCHAR,
            stars INTEGER,
            genius BOOLEAN,
            review_score VARCHAR,
            review_word VARCHAR,
            review_count VARCHAR,
            neighbourhood VARCHAR,
            sustainability VARCHAR,
            room_type VARCHAR,
            bed_info VARCHAR,
            rooms_left_hint VARCHAR,
            nights INTEGER,
            adults INTEGER,
            price_original VARCHAR,
            price_current VARCHAR,
            taxes_fees VARCHAR,
            members_only_price BOOLEAN,
            card_text VARCHAR
        )
        """
    )
    cols = [r[0] for r in con.execute("DESCRIBE search_listings").fetchall()]
    for col, typ in (
        ("city", "VARCHAR"),
        ("stars", "INTEGER"),
        ("genius", "BOOLEAN"),
        ("review_score", "VARCHAR"),
        ("review_word", "VARCHAR"),
        ("review_count", "VARCHAR"),
        ("neighbourhood", "VARCHAR"),
        ("sustainability", "VARCHAR"),
        ("room_type", "VARCHAR"),
        ("bed_info", "VARCHAR"),
        ("rooms_left_hint", "VARCHAR"),
        ("nights", "INTEGER"),
        ("adults", "INTEGER"),
        ("price_original", "VARCHAR"),
        ("price_current", "VARCHAR"),
        ("taxes_fees", "VARCHAR"),
        ("members_only_price", "BOOLEAN"),
        ("card_text", "VARCHAR"),
        ("address", "VARCHAR"),
        ("street", "VARCHAR"),
        ("postal_code", "VARCHAR"),
        ("country", "VARCHAR"),
        ("popular_facilities", "VARCHAR"),
        ("amenities", "VARCHAR"),
    ):
        if col not in cols:
            con.execute(f"ALTER TABLE search_listings ADD COLUMN {col} {typ}")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS property_rooms (
            property_name VARCHAR,
            property_url VARCHAR,
            room_name VARCHAR,
            price VARCHAR,
            sold_out BOOLEAN,
            layout VARCHAR,
            review VARCHAR,
            check_in VARCHAR,
            check_out VARCHAR,
            captured_at VARCHAR,
            ingested_at VARCHAR
        )
        """
    )
    return con


def _slug_from_url(url: str | None) -> str:
    if not url:
        return ""
    m = re.search(r"/hotel/[^/]+/([^/?#]+)", url.lower())
    slug = m.group(1) if m else ""
    return re.sub(r"\.(?:[a-z]{2}-[a-z]{2})\.html$|\.html$", "", slug)


def append_quotes(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    out = df.copy()
    if "property_slug" not in out.columns:
        out["property_slug"] = out.get("url", pd.Series(dtype=str)).fillna("").map(_slug_from_url)
    out["ingested_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cols = [
        "property_slug",
        "check_in",
        "check_out",
        "nights",
        "room_name_raw",
        "status",
        "price_text",
        "total_gbp",
        "nightly_gbp",
        "url",
        "captured_at",
        "source",
        "ingested_at",
    ]
    for col in cols:
        if col not in out.columns:
            out[col] = None
    out = out[cols]
    con = connect()
    try:
        con.register("quotes_in", out)
        con.execute("INSERT INTO quotes SELECT * FROM quotes_in")
        return len(out)
    finally:
        con.close()


LISTING_COLS = [
    "title",
    "price",
    "distance",
    "review_block",
    "property_url",
    "sponsored",
    "availability_hint",
    "check_in",
    "check_out",
    "captured_at",
    "ingested_at",
    "city",
    "stars",
    "genius",
    "review_score",
    "review_word",
    "review_count",
    "neighbourhood",
    "sustainability",
    "room_type",
    "bed_info",
    "rooms_left_hint",
    "nights",
    "adults",
    "price_original",
    "price_current",
    "taxes_fees",
    "members_only_price",
    "card_text",
]


def upsert_search_listings(df: pd.DataFrame, city: str = "Milan") -> int:
    if df is None or df.empty:
        return 0
    out = df.copy()
    out["city"] = city
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if "ingested_at" not in out.columns:
        out["ingested_at"] = now
    if "captured_at" not in out.columns:
        out["captured_at"] = now
    out = out[out["property_url"].notna() & (out["property_url"].astype(str) != "")]
    if out.empty:
        return 0
    for col in LISTING_COLS:
        if col not in out.columns:
            out[col] = None
    out = out[LISTING_COLS]
    con = connect()
    try:
        con.register("listings_in", out)
        con.execute(
            f"INSERT INTO search_listings ({', '.join(LISTING_COLS)}) SELECT * FROM listings_in"
        )
        return len(out)
    finally:
        con.close()


def existing_listing_urls(city: str, check_in: str) -> set[str]:
    con = connect()
    try:
        rows = con.execute(
            """
            SELECT DISTINCT property_url
            FROM search_listings
            WHERE city = ? AND check_in = ? AND property_url IS NOT NULL
            """,
            [city, check_in],
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        con.close()


def ingest_quotes_csv(csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    df = pd.read_csv(csv_path)
    return append_quotes(df)


def ingest_feasibility_json(json_path: Path) -> tuple[int, int]:
    if not json_path.exists():
        return (0, 0)
    report = json.loads(json_path.read_text(encoding="utf-8"))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    check_in = report.get("checkin")
    check_out = report.get("checkout")

    listings = pd.DataFrame(report.get("search", {}).get("sample_cards") or [])
    n_listings = 0
    n_rooms = 0
    con = connect()
    try:
        if not listings.empty:
            listings = listings.drop_duplicates(subset=["property_url", "title", "price"])
            listings["check_in"] = check_in
            listings["check_out"] = check_out
            listings["captured_at"] = now
            listings["ingested_at"] = now
            for col in (
                "title",
                "price",
                "distance",
                "review_block",
                "property_url",
                "sponsored",
                "availability_hint",
                "check_in",
                "check_out",
                "captured_at",
                "ingested_at",
            ):
                if col not in listings.columns:
                    listings[col] = None
            listings = listings[
                [
                    "title",
                    "price",
                    "distance",
                    "review_block",
                    "property_url",
                    "sponsored",
                    "availability_hint",
                    "check_in",
                    "check_out",
                    "captured_at",
                    "ingested_at",
                ]
            ]
            con.register("listings_in", listings)
            con.execute("INSERT INTO search_listings SELECT * FROM listings_in")
            n_listings = len(listings)

        room_rows = []
        for prop in report.get("properties") or []:
            for room in prop.get("rooms_sample") or []:
                room_rows.append(
                    {
                        "property_name": prop.get("name"),
                        "property_url": prop.get("requested_url") or prop.get("final_url"),
                        "room_name": room.get("name"),
                        "price": room.get("price"),
                        "sold_out": room.get("sold_out"),
                        "layout": room.get("layout"),
                        "review": prop.get("review"),
                        "check_in": check_in,
                        "check_out": check_out,
                        "captured_at": now,
                        "ingested_at": now,
                    }
                )
        if room_rows:
            rooms = pd.DataFrame(room_rows).drop_duplicates(
                subset=["property_url", "room_name", "price", "layout"]
            )
            con.register("rooms_in", rooms)
            con.execute("INSERT INTO property_rooms SELECT * FROM rooms_in")
            n_rooms = len(rooms)
        return (n_listings, n_rooms)
    finally:
        con.close()


def ingest_existing() -> dict:
    quotes_n = 0
    for csv_path in list(ROOT.glob("Booking_*_chunked.csv")) + list((ROOT / "archive").glob("Booking_*_chunked.csv")):
        quotes_n += ingest_quotes_csv(csv_path)

    json_path = ROOT / "archive" / "milan_probe" / "milan_feasibility_report.json"
    listings_n, rooms_n = ingest_feasibility_json(json_path)
    return {
        "db": str(duckdb_path()),
        "quotes": quotes_n,
        "search_listings": listings_n,
        "property_rooms": rooms_n,
    }


def summary() -> dict:
    con = connect()
    try:
        def count(table: str) -> int:
            return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        return {
            "db": str(duckdb_path()),
            "quotes": count("quotes"),
            "search_listings": count("search_listings"),
            "property_rooms": count("property_rooms"),
        }
    finally:
        con.close()
