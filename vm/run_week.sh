#!/bin/bash
# Full Milan week in one go: search scrape (prices + tax) then hotel pages
# (address + amenities). Sequential — fewer captchas than 7 browsers at once.
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
mkdir -p outputs logs

echo "=== search scrape 24-30 Sep 2026 (full slices, tax on cards) ==="
python scrape_range.py --full --from-date 2026-09-24 --to-date 2026-09-30 \
  2>&1 | tee logs/week_search.log

echo "=== property details (address, amenities) ==="
python enrich_week.py --dir outputs --from-date 2026-09-24 \
  2>&1 | tee logs/week_enrich.log

echo "Done."
echo "Search:   outputs/listings_2026-09-24_to_2026-09-30.csv"
echo "Full:     outputs/enriched/"
echo "Logs:     logs/"
