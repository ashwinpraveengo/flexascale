#!/usr/bin/env bash
# FlexaScale - Cluster Verification Script (Linux / macOS)

set -euo pipefail

PROFILE=${1:-"flexascale"}

echo "=========================================================="
echo " FlexaScale - Cluster Health & Resource Verification"
echo "=========================================================="

echo -e "\n[*] Minikube Status:"
minikube status -p "$PROFILE" || true

echo -e "\n[*] Kubernetes Nodes:"
kubectl get nodes -o wide

echo -e "\n[*] Namespaces:"
kubectl get namespaces

echo -e "\n[*] Microservice Pods (flexascale-apps):"
kubectl get pods -n flexascale-apps -o wide

echo -e "\n[*] Microservice Services (flexascale-apps):"
kubectl get svc -n flexascale-apps

echo -e "\n[*] Monitoring Pods (flexascale-monitoring):"
kubectl get pods -n flexascale-monitoring

echo -e "\n[*] Monitoring Services (flexascale-monitoring):"
kubectl get svc -n flexascale-monitoring

echo -e "\n[*] Helm Deployments:"
helm list -A

echo -e "\n=========================================================="
echo " Cluster verification complete."
echo "=========================================================="
