$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " FlexaScale - Deploying Prometheus & Grafana Stack" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

Write-Host "`n[1/2] Updating Helm Repositories..." -ForegroundColor Yellow
helm repo update

Write-Host "`n[2/2] Installing kube-prometheus-stack in flexascale-monitoring..." -ForegroundColor Yellow
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack `
  --namespace flexascale-monitoring `
  -f k8s/prometheus-values.yaml

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " Monitoring Stack Deployment Completed Successfully!" -ForegroundColor Green
Write-Host " Run 'kubectl get pods -n flexascale-monitoring' to check status." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
