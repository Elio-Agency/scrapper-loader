"""Dump search_listings from DuckDB to CSV + Excel. No scrape."""
from __future__ import annotations

import duckdb
import pandas as pd

from config import ROOT

CANDIDATES = [
    ROOT / "dashboard" / "booking.duckdb",
    ROOT / "booking.duckdb",
    ROOT / "archive" / "modal" / "booking.duckdb",
]


def main():
    db = next((p for p in CANDIDATES if p.exists()), None)
    if not db:
        raise SystemExit("No booking.duckdb found")
    out = ROOT / "outputs"
    out.mkdir(exist_ok=True)
    con = duckdb.connect(str(db), read_only=True)
    df = con.execute("SELECT * FROM search_listings").fetchdf()
    con.close()
    csv_path = out / "listings_from_duckdb.csv"
    xlsx_path = out / "listings_from_duckdb.xlsx"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    slim = df.drop(columns=["card_text"], errors="ignore")
    slim.to_excel(xlsx_path, index=False)
    print(f"Read {db}  rows={len(df)}")
    print(f"CSV   {csv_path}")
    print(f"Excel {xlsx_path}")


if __name__ == "__main__":
    main()
