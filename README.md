# Booking.com Milan scraper

Playwright scrapers for Milan hotel search on Booking.com, plus a Streamlit dashboard. Default stay is **24–30 Sep 2026**, 1 night, 1 adult, GBP.

Do not scrape unless you intend to. Booking may show a captcha.

## Layout

```text
scrape/          Search + hotel-page scrapers, enrich, merge
dashboard/       Streamlit app (deploy this folder)
vm/              GCP VM run scripts (copies scrape/ onto the VM)
gcp/             Create the Compute Engine VM
outputs/         Local scrape files (gitignored)
archive/         Older Modal / probe / Geneva experiments
```

Secrets stay in `.env` (gitignored). Copy `.env.example`.

## Scrape (local)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium

python scrape/scrape_one_property.py --from-date 2026-09-24
python scrape/scrape_range.py --from-date 2026-09-24 --to-date 2026-09-24 --max-offset 0
python scrape/enrich_week.py --dir outputs --from-date 2026-09-24 --limit 5
python scrape/load_enriched_week.py
```

Search writes price, tax, distance, and beds to `outputs/`. Address and amenities are filled by `enrich_week.py` into `outputs/enriched/`.

## Dashboard

```powershell
cd dashboard
pip install -r requirements.txt
streamlit run app.py
```

The app reads `dashboard/listings_week_merged.csv`. After a new enrich, run `python scrape/load_enriched_week.py` from the repo root.

## GCP VM

```powershell
.\gcp\create_vm.ps1 -Zone europe-west1-b -MachineType n2-standard-16
.\vm\copy_to_vm.ps1
```

On the VM the pack is flattened into `~/scrapper/` (same as before). See `vm/README.md`.

```bash
gcloud compute instances stop booking-scrape-1 --zone=europe-west1-b
```

## GitHub

Do not commit `.env`, DuckDB files, or `outputs/`. The merged dashboard CSV is allowed so Streamlit Cloud can load data.
