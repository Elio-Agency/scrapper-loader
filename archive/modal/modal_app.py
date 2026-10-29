"""
Modal app: daily Booking.com listings for tomorrow's check-in (1 night, 1 adult).

DuckDB lives on a Modal Volume so it persists between scheduled runs.

From this folder:
  pip install modal
  modal setup
  modal deploy modal_app.py
  modal run modal_app.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "playwright>=1.40.0",
        "pandas>=2.0.0",
        "duckdb>=1.0.0",
        "python-dotenv>=1.0.0",
    )
    .run_commands("playwright install --with-deps chromium")
    .add_local_dir(HERE, remote_path="/app")
)

app = modal.App("listings-daily")
# Volume name is unchanged so previously collected data stays attached.
volume = modal.Volume.from_name("milan-listings-duckdb", create_if_missing=True)


def _run_scrape():
    os.environ["DUCKDB_PATH"] = "/data/booking.duckdb"
    os.chdir("/app")
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")

    import asyncio
    import listings

    listings.set_stay_for_tomorrow()
    asyncio.run(listings.main())
    volume.commit()
    return listings.summary()


@app.function(
    image=image,
    volumes={"/data": volume},
    timeout=2 * 60 * 60,
    memory=4096,
    retries=0,
)
def scrape_tomorrow_checkin():
    return _run_scrape()


@app.function(image=image, volumes={"/data": volume}, timeout=60)
def peek_duckdb():
    os.environ["DUCKDB_PATH"] = "/data/booking.duckdb"
    os.chdir("/app")
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    import duckdb
    from config import duckdb_path

    con = duckdb.connect(str(duckdb_path()))
    return con.execute(
        """
        SELECT check_in, COUNT(*) AS rows, COUNT(DISTINCT property_url) AS unique_urls
        FROM search_listings
        GROUP BY 1
        ORDER BY 1 DESC
        """
    ).fetchall()


@app.local_entrypoint()
def main():
    print(scrape_tomorrow_checkin.remote())


@app.function(
    image=image,
    volumes={"/data": volume},
    timeout=2 * 60 * 60,
    memory=4096,
    schedule=modal.Cron("0 6 * * *"),
)
def daily_tomorrow_checkin():
    return _run_scrape()
