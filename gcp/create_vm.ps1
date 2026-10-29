# Large Compute Engine VM for parallel Booking listing scrapes.
# Default: n2-standard-16 (16 vCPU). Need more? use -MachineType n2-standard-32
#
#   .\gcp\create_vm.ps1
#   .\gcp\create_vm.ps1 -MachineType n2-standard-32

param(
    [string]$Name = "booking-scrape-1",
    [string]$Zone = "europe-west1-b",
    [string]$MachineType = "n2-standard-16",
    [string]$DiskSize = "100GB"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$startup = Join-Path $here "startup.sh"

if (-not (Test-Path $startup)) {
    throw "Missing $startup"
}

gcloud services enable compute.googleapis.com

gcloud compute instances create $Name `
    --zone=$Zone `
    --machine-type=$MachineType `
    --boot-disk-size=$DiskSize `
    --boot-disk-type=pd-ssd `
    --image-family=debian-12 `
    --image-project=debian-cloud `
    --maintenance-policy=MIGRATE `
    --metadata-from-file=startup-script=$startup `
    --tags=ssh `
    --scopes=cloud-platform

Write-Host "Created $Name ($MachineType, $DiskSize SSD) in $Zone"
Write-Host "Wait ~1 min, then from the repo:"
Write-Host "  .\vm\copy_to_vm.ps1 -Name $Name -Zone $Zone"
