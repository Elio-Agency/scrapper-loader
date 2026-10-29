# VM scrape pack — 24–30 Sep 2026

Python scrapers live in `../scrape/`. `copy_to_vm.ps1` flattens them into `~/scrapper/` on the VM with the scripts in this folder.

Search scrape captures prices **and tax**. Then one hotel-page pass fills address + amenities (`enrich_week.py`). Both run together in `run_week.sh`.

Default stay: **24 Sep → 30 Sep 2026**, 1 night, 1 adult, GBP.

VM name: `booking-scrape-1`  
Zone: `europe-west1-b`

## 1. Create the VM

**Windows (from the repo root):**

```powershell
.\gcp\create_vm.ps1 -Zone europe-west1-b -MachineType n2-standard-16
```

Quota fail? Use `-MachineType n2-standard-8`.

**Or Cloud Shell / bash:**

```bash
gcloud services enable compute.googleapis.com

gcloud compute instances create booking-scrape-1 \
  --zone=europe-west1-b \
  --machine-type=n2-standard-16 \
  --boot-disk-size=100GB \
  --boot-disk-type=pd-ssd \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --maintenance-policy=MIGRATE \
  --tags=ssh \
  --scopes=cloud-platform
```

Wait ~1 minute (startup script installs python3-venv + tmux).

## 2. Copy this folder to the VM

**Windows:**

```powershell
.\vm\copy_to_vm.ps1
```

**Or from the repo** (scripts are in `scrape/` + `vm/`):

```bash
gcloud compute ssh booking-scrape-1 --zone=europe-west1-b --command="mkdir -p ~/scrapper"

gcloud compute scp scrape/scrape_range.py scrape/scrape_one_property.py scrape/milan_listings.py \
  scrape/listing_columns.py scrape/config.py scrape/warehouse.py scrape/enrich_week.py \
  requirements.txt .env.example \
  vm/run_week.sh vm/verify_one.sh \
  booking-scrape-1:~/scrapper/ --zone=europe-west1-b
```

Then SSH:

```bash
gcloud compute ssh booking-scrape-1 --zone=europe-west1-b
cd ~/scrapper
cp .env.example .env
sed -i 's/\r$//' run_week.sh verify_one.sh
```

Leave `PROXY_SERVER` empty (direct). Do not upload a laptop `.env` that uses `127.0.0.1:8888`.

## 3. Install on the VM

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv tmux
cd ~/scrapper
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
python -m playwright install --with-deps chromium
chmod +x run_week.sh verify_one.sh
```

## 4. Verify one property first (DoubleTree, 24 Sep)

```bash
cd ~/scrapper
source .venv/bin/activate
bash verify_one.sh
```

You should see name, address, postal code, **tax**, and files:

- `outputs/property_doubletree.csv`
- `outputs/property_doubletree.xlsx`

If you see `captcha / bot check`, stop and retry later. Do not start the week yet.

## 5. Full week (24–30 Sep) after the one-property check looks good

```bash
cd ~/scrapper
source .venv/bin/activate
tmux new -s scrape
bash run_week.sh
```

Detach: `Ctrl+B` then `D`. Reattach: `tmux attach -t scrape`.

This runs **full search slices** for 24–30 Sep (tax on the card), then **hotel-page enrich** (address + amenities) into `outputs/enriched/`.

One date only (no enrich):

```bash
python scrape_range.py --full --from-date 2026-09-24 --to-date 2026-09-24
```

If captcha:

```bash
pkill -f scrape_range.py
pkill -f enrich_week.py
```

Then rerun. `enrich_week.py` is safe to re-run; cached hotels are skipped.

## 6. Download results

```bash
gcloud compute scp --recurse booking-scrape-1:~/scrapper/outputs ./outputs-24-30 --zone=europe-west1-b
```
