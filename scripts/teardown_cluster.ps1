# FlexaScale - Cluster Teardown Script
# Safely stops or deletes the local Minikube cluster profile

param (
    [string]$Profile = "flexascale",
    [switch]$Delete = $false
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " FlexaScale - Local Kubernetes Cluster Teardown" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

if ($Delete) {
    Write-Host "Deleting Minikube profile '$Profile'..." -ForegroundColor Yellow
    minikube delete -p $Profile
    Write-Host "✔ Minikube profile '$Profile' deleted." -ForegroundColor Green
} else {
    Write-Host "Stopping Minikube profile '$Profile'..." -ForegroundColor Yellow
    minikube stop -p $Profile
    Write-Host "✔ Minikube profile '$Profile' stopped. (Use -Delete to remove completely)" -ForegroundColor Green
}
