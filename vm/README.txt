VM pack 24-30 Sep 2026. Python files live in ../scrape/.

Windows:
  .\gcp\create_vm.ps1 -Zone europe-west1-b -MachineType n2-standard-16
  .\vm\copy_to_vm.ps1

On VM:
  cp .env.example .env
  sed -i 's/\r$//' run_week.sh verify_one.sh
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  python -m playwright install --with-deps chromium

Verify one hotel:
  bash verify_one.sh

Then full week:
  tmux new -s scrape
  bash run_week.sh
