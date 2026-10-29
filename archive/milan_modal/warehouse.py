"""DuckDB warehouse for Milan search listings."""
from __future__ import annotations

from datetime import datetime

import duckdb
import pandas as pd

from config import duckdb_path


def connect() -> duckdb.DuckDBPyConnection:
    path = duckdb_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
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
    ):
        if col not in cols:
            con.execute(f"ALTER TABLE search_listings ADD COLUMN {col} {typ}")
    return con


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


def summary() -> dict:
    con = connect()
    try:
        n = int(con.execute("SELECT COUNT(*) FROM search_listings").fetchone()[0])
        u = int(con.execute("SELECT COUNT(DISTINCT property_url) FROM search_listings").fetchone()[0])
        return {"db": str(duckdb_path()), "search_listings": n, "unique_urls": u}
    finally:
        con.close()
