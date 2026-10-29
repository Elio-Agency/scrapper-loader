# Copy scrape pack (flat) onto the GCP VM.
# From the repo root:
#   .\vm\copy_to_vm.ps1
#   .\vm\copy_to_vm.ps1 -Name booking-scrape-1 -Zone europe-west1-b

param(
    [string]$Name = "booking-scrape-1",
    [string]$Zone = "europe-west1-b"
)

$ErrorActionPreference = "Stop"
$vmDir = $PSScriptRoot
$repo = Split-Path $vmDir
$scrape = Join-Path $repo "scrape"

gcloud compute ssh $Name --zone=$Zone --command="mkdir -p ~/scrapper"

Push-Location $scrape
try {
    gcloud compute scp `
        scrape_range.py scrape_one_property.py milan_listings.py listing_columns.py `
        config.py warehouse.py enrich_week.py `
        "${Name}:~/scrapper/" --zone=$Zone
}
finally {
    Pop-Location
}

Push-Location $repo
try {
    gcloud compute scp requirements.txt .env.example "${Name}:~/scrapper/" --zone=$Zone
}
finally {
    Pop-Location
}

Push-Location $vmDir
try {
    gcloud compute scp run_week.sh verify_one.sh "${Name}:~/scrapper/" --zone=$Zone
}
finally {
    Pop-Location
}

Write-Host "Copied pack to ${Name}:~/scrapper/"
Write-Host "On the VM:  cp .env.example .env   (leave PROXY empty)"
