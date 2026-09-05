#!/usr/bin/env bash
# FlexaScale - Deploy Prometheus & Grafana Monitoring Stack (Linux / macOS)

set -euo pipefail

echo "=========================================================="
echo " FlexaScale - Deploying Prometheus & Grafana Stack"
echo "=========================================================="

echo -e "\n[1/3] Updating Helm Repositories..."
helm repo update

echo -e "\n[2/3] Installing kube-prometheus-stack in flexascale-monitoring..."
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace flexascale-monitoring \
  -f k8s/prometheus-values.yaml

echo -e "\n[3/3] Applying FlexaScale Grafana Dashboard ConfigMap..."
kubectl apply -f k8s/grafana-dashboard-configmap.yaml

echo -e "\n=========================================================="
echo " Monitoring Stack Deployment Completed Successfully!"
echo " Run 'kubectl get pods -n flexascale-monitoring' to check status."
echo "=========================================================="
