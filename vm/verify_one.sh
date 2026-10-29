#!/bin/bash
# 1) Hotel page (address, tax, amenities, beds if present)
# 2) First search page (distance, bed, reviews — same source as the full week)
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
mkdir -p outputs

python scrape_one_property.py --from-date 2026-09-24
python scrape_range.py --from-date 2026-09-24 --to-date 2026-09-24 --max-offset 0

python - <<'PY'
from pathlib import Path
import pandas as pd

def show(path, title):
    p = Path(path)
    if not p.exists():
        print(f"\n=== {title} === missing {path}")
        return
    df = pd.read_csv(p)
    print(f"\n=== {title} === {path}  rows={len(df)}")
    keys = [
        "title", "room_type", "bed_info", "distance", "neighbourhood",
        "price_current", "taxes_fees", "review_score", "review_word",
        "review_count", "stars", "address", "postal_code",
    ]
    cols = [c for c in keys if c in df.columns]
    print(df[cols].head(8).to_string(index=False))
    print("\nnon-empty %")
    for c in cols:
        n = df[c].notna() & df[c].astype(str).str.strip().ne("") & df[c].astype(str).ne("nan")
        print(f"  {c:16} {int(n.mean()*100):3d}%  ({int(n.sum())}/{len(df)})")

show("outputs/property_doubletree.csv", "hotel page (one property)")
show("outputs/listings_2026-09-24_to_2026-09-24.csv", "search first page (week sample)")
PY
