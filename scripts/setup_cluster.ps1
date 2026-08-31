# FlexaScale - Cluster Setup Script
# Configures Minikube cluster, essential addons, namespaces, and Helm repositories

param (
    [int]$Memory = 6144,
    [int]$Cpus = 4,
    [string]$Profile = "flexascale",
    [string]$Driver = "docker",
    [string]$KubernetesVersion = "v1.31.0"
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " FlexaScale - Local Kubernetes Cluster & Helm Setup" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check prerequisites
Write-Host "`n[1/6] Checking prerequisites..." -ForegroundColor Yellow

$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker is not found in PATH. Please ensure Docker Desktop is installed."
}

if (-not (Get-Command minikube -ErrorAction SilentlyContinue)) {
    Write-Error "Minikube is not found in PATH. Please install Minikube."
}

if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    Write-Error "kubectl is not found in PATH. Please install kubectl."
}

if (-not (Get-Command helm -ErrorAction SilentlyContinue)) {
    Write-Error "Helm is not found in PATH. Please install Helm."
}

docker info > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker engine is not running. Please start Docker Desktop and wait for it to be ready."
}
Write-Host "  OK: Docker, Minikube, kubectl, and Helm are present and active." -ForegroundColor Green

# 2. Start Minikube Cluster
Write-Host "`n[2/6] Starting Minikube cluster (profile: $Profile, driver: $Driver, CPUs: $Cpus, Memory: ${Memory}MB)..." -ForegroundColor Yellow
& minikube start -p $Profile --driver=$Driver --cpus=$Cpus --memory=$Memory --kubernetes-version=$KubernetesVersion

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to start Minikube cluster."
}
Write-Host "  OK: Minikube cluster '$Profile' is running." -ForegroundColor Green

# 3. Enable essential addons
Write-Host "`n[3/6] Enabling essential addons (metrics-server, ingress, dashboard)..." -ForegroundColor Yellow
& minikube addons enable metrics-server -p $Profile
& minikube addons enable ingress -p $Profile
& minikube addons enable dashboard -p $Profile
Write-Host "  OK: Addons enabled." -ForegroundColor Green

# 4. Create Namespaces
Write-Host "`n[4/6] Creating project namespaces..." -ForegroundColor Yellow
$nsApps = kubectl get namespace flexascale-apps --ignore-not-found --no-headers
if (-not $nsApps) {
    kubectl create namespace flexascale-apps
    Write-Host "  OK: Created namespace 'flexascale-apps'" -ForegroundColor Green
} else {
    Write-Host "  INFO: Namespace 'flexascale-apps' already exists" -ForegroundColor Gray
}

$nsMon = kubectl get namespace flexascale-monitoring --ignore-not-found --no-headers
if (-not $nsMon) {
    kubectl create namespace flexascale-monitoring
    Write-Host "  OK: Created namespace 'flexascale-monitoring'" -ForegroundColor Green
} else {
    Write-Host "  INFO: Namespace 'flexascale-monitoring' already exists" -ForegroundColor Gray
}

# 5. Add and update Helm repositories
Write-Host "`n[5/6] Configuring Helm repositories..." -ForegroundColor Yellow
& helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
& helm repo add grafana https://grafana.github.io/helm-charts --force-update
& helm repo add bitnami https://charts.bitnami.com/bitnami --force-update
& helm repo update
Write-Host "  OK: Helm repositories configured and updated." -ForegroundColor Green

# 6. Cluster Summary
Write-Host "`n[6/6] Cluster Status Summary:" -ForegroundColor Yellow
& minikube status -p $Profile

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " FlexaScale Cluster & Helm setup completed successfully!" -ForegroundColor Green
Write-Host " Profile: $Profile" -ForegroundColor Green
Write-Host " App Namespace: flexascale-apps (Ready for Ghanshyam's microservices)" -ForegroundColor Green
Write-Host " Monitoring Namespace: flexascale-monitoring (Ready for Atmakrishna's Prometheus/Grafana)" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
