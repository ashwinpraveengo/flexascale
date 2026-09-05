#!/usr/bin/env bash
# FlexaScale - Local Cluster Setup Script (Linux / macOS)
# Configures Minikube cluster, essential addons, namespaces, and Helm repositories

set -euo pipefail

MEMORY=${1:-6144}
CPUS=${2:-4}
PROFILE=${3:-"flexascale"}
DRIVER=${4:-"docker"}
K8S_VERSION=${5:-"v1.31.0"}

echo "=========================================================="
echo " FlexaScale - Local Kubernetes Cluster & Helm Setup"
echo "=========================================================="

echo -e "\n[1/6] Checking prerequisites..."
for cmd in docker minikube kubectl helm; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: $cmd is not found in PATH." >&2
        exit 1
    fi
done
echo "  OK: Docker, Minikube, kubectl, and Helm are present and active."

echo -e "\n[2/6] Starting Minikube cluster (profile: $PROFILE, driver: $DRIVER, CPUs: $CPUS, Memory: ${MEMORY}MB)..."
minikube start -p "$PROFILE" --driver="$DRIVER" --cpus="$CPUS" --memory="$MEMORY" --kubernetes-version="$K8S_VERSION"
echo "  OK: Minikube cluster '$PROFILE' is running."

echo -e "\n[3/6] Enabling essential addons (metrics-server, ingress, dashboard)..."
minikube addons enable metrics-server -p "$PROFILE"
minikube addons enable ingress -p "$PROFILE"
minikube addons enable dashboard -p "$PROFILE"
echo "  OK: Addons enabled."

echo -e "\n[4/6] Creating project namespaces..."
kubectl get namespace flexascale-apps &>/dev/null || kubectl create namespace flexascale-apps
kubectl get namespace flexascale-monitoring &>/dev/null || kubectl create namespace flexascale-monitoring
echo "  OK: Namespaces 'flexascale-apps' and 'flexascale-monitoring' ready."

echo -e "\n[5/6] Configuring Helm repositories..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
helm repo add grafana https://grafana.github.io/helm-charts --force-update
helm repo add bitnami https://charts.bitnami.com/bitnami --force-update
helm repo update
echo "  OK: Helm repositories configured and updated."

echo -e "\n[6/6] Cluster Status Summary:"
minikube status -p "$PROFILE"

echo -e "\n=========================================================="
echo " FlexaScale Cluster & Helm setup completed successfully!"
echo " Profile: $PROFILE"
echo " App Namespace: flexascale-apps"
echo " Monitoring Namespace: flexascale-monitoring"
echo "=========================================================="
