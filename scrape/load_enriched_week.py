"""Merge enriched week CSVs into one file and load dashboard/booking.duckdb."""
from __future__ import annotations

from datetime import datetime

import duckdb
import pandas as pd

from listing_columns import ALL_COLS
from config import ROOT

SRC = ROOT / "outputs" / "enriched"
OUT_CSV = ROOT / "dashboard" / "listings_week_merged.csv"
OUT_XLSX = ROOT / "dashboard" / "listings_week_merged.xlsx"
DB_PATHS = [
    ROOT / "dashboard" / "booking.duckdb",
]


def main() -> None:
    files = sorted(SRC.glob("listings_2026-09-??_to_2026-09-??.csv"))
    if not files:
        raise SystemExit(f"No enriched CSVs in {SRC}")
    frames = [pd.read_csv(p, dtype={"postal_code": "string"}) for p in files]
    df = pd.concat(frames, ignore_index=True)
    df["ingested_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if "city" in df.columns:
        df["city"] = df["city"].fillna("Milan")
    if "postal_code" in df.columns:
        df["postal_code"] = (
            df["postal_code"]
            .astype(str)
            .str.replace(r"\.0+$", "", regex=True)
            .replace({"nan": None, "None": None, "": None})
        )
    keep = [c for c in ALL_COLS if c in df.columns]
    extra = [c for c in df.columns if c not in keep]
    df = df[keep + extra]
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    df.to_excel(OUT_XLSX, index=False)
    print(f"Merged {len(files)} files -> {len(df)} rows")
    print(f"CSV   {OUT_CSV}")
    print(f"Excel {OUT_XLSX}")
    n_addr = df["address"].fillna("").astype(str).str.len().gt(0).sum() if "address" in df.columns else 0
    print(f"Rows with address: {n_addr}/{len(df)}")

    for db in DB_PATHS:
        db.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(db))
        con.register("week_df", df)
        con.execute("DROP TABLE IF EXISTS search_listings")
        con.execute("CREATE TABLE search_listings AS SELECT * FROM week_df")
        con.close()
        print(f"DuckDB {db}")


if __name__ == "__main__":
    main()
