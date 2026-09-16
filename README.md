# Booking.com listings — Modal job

Daily scrape of Booking.com search results. Each run looks up **tomorrow’s check-in**, **1 night**, **1 adult**, and **appends** rows into DuckDB. Duplicates are kept in the warehouse; the Streamlit dashboard (`../dashboard`) shows unique properties.

## How it works

1. Modal runs `listings.py` on a schedule (`06:00 UTC` by default).
2. Playwright opens Booking.com search, paginates (offset / load more / filter slices), and extracts listing cards.
3. Rows are written to DuckDB at `/data/booking.duckdb` on a **Modal Volume** (`milan-listings-duckdb`). The volume persists between runs so history is not wiped.
4. `volume.commit()` saves the file after the scrape.

The scraper does not talk to an official Booking API. It reads the public search page.

DuckDB is a **file**, not a server. The dashboard can only read it if that file is on the same machine, or if you copy it (or point `DUCKDB_PATH` at a snapshot). While a scrape is writing, a dashboard connection can fail because DuckDB takes an exclusive write lock.

## Files

| File | Role |
| --- | --- |
| `modal_app.py` | Modal image, volume, cron, and entrypoints |
| `listings.py` | Playwright search scrape |
| `warehouse.py` | Append / query DuckDB |
| `config.py` | `DUCKDB_PATH` and optional proxy |
| `query_listings.py` | Quick local counts |

## Setup (do not run a scrape unless you intend to)

```powershell
cd c:\Users\jeeva\Documents\scrapper\modal
pip install -r requirements.txt
modal setup
```

Optional proxy: copy `.env.example` to `.env` and fill `PROXY_SERVER` / `PROXY_USERNAME` / `PROXY_PASSWORD`. On Modal, put those in a **Secret** instead of a local `.env`.

## Commands

```powershell
# Deploy the scheduled job
modal deploy modal_app.py

# One-off scrape (writes to the Volume)
modal run modal_app.py

# Peek counts in the Volume DuckDB
modal run modal_app.py::peek_duckdb
```

Local test (uses `booking.duckdb` in this folder unless `DUCKDB_PATH` is set):

```powershell
python listings.py
python query_listings.py
```

## Reading the data from the dashboard

The Streamlit app in `../dashboard` looks for DuckDB in this order:

1. `DUCKDB_PATH`
2. `../booking.duckdb` (project root)
3. `../modal/booking.duckdb`

To host the dashboard against the Modal Volume, run Streamlit on Modal with the same volume mounted, or download `/data/booking.duckdb` after each scrape and set `DUCKDB_PATH`.
