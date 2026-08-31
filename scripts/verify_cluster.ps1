# FlexaScale - Cluster Verification Script
# Checks health of the cluster, nodes, pods, namespaces, addons, and Helm

param (
    [string]$Profile = "flexascale"
)

# Refresh PATH for current session
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " FlexaScale - Cluster & Tooling Health Verification" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

Write-Host "`n1. Minikube Status ($Profile):" -ForegroundColor Yellow
minikube status -p $Profile

Write-Host "`n2. Cluster Nodes:" -ForegroundColor Yellow
kubectl get nodes -o wide

Write-Host "`n3. Namespaces:" -ForegroundColor Yellow
kubectl get namespaces

Write-Host "`n4. Core & Addon Pods (kube-system):" -ForegroundColor Yellow
kubectl get pods -n kube-system

Write-Host "`n5. Addons Status:" -ForegroundColor Yellow
minikube addons list -p $Profile | Select-String "enabled"

Write-Host "`n6. Helm Version & Repositories:" -ForegroundColor Yellow
helm version --short
helm repo list

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " Verification completed!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
