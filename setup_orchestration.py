import os

base_dir = "/home/ghanasyam/Desktop/S7/flexascale/app"

# 1. docker-compose.yml
docker_compose = """version: '3.8'
services:
  frontend:
    build: ./frontend
    ports:
      - "8000:8000"
    environment:
      - ORDERS_URL=http://orders:8000
    depends_on:
      - orders

  orders:
    build: ./orders
    ports:
      - "8001:8000"
    environment:
      - INVENTORY_URL=http://inventory:8000
    depends_on:
      - inventory

  inventory:
    build: ./inventory
    ports:
      - "8002:8000"
    environment:
      - PAYMENTS_URL=http://payments:8000
    depends_on:
      - payments

  payments:
    build: ./payments
    ports:
      - "8003:8000"
"""

with open(os.path.join(base_dir, "docker-compose.yml"), "w") as f:
    f.write(docker_compose)

# 2. k8s manifests
k8s_dir = os.path.join(base_dir, "k8s")
os.makedirs(k8s_dir, exist_ok=True)

def create_k8s_manifest(service, port=8000):
    manifest = f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {service}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {service}
  template:
    metadata:
      labels:
        app: {service}
    spec:
      containers:
      - name: {service}
        image: {service}:latest
        imagePullPolicy: Never
        ports:
        - containerPort: {port}
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "500m"
            memory: "256Mi"
"""
    if service == "frontend":
        manifest += f"""        env:
        - name: ORDERS_URL
          value: "http://orders:8000"
"""
    elif service == "orders":
        manifest += f"""        env:
        - name: INVENTORY_URL
          value: "http://inventory:8000"
"""
    elif service == "inventory":
        manifest += f"""        env:
        - name: PAYMENTS_URL
          value: "http://payments:8000"
"""

    manifest += f"""---
apiVersion: v1
kind: Service
metadata:
  name: {service}
  labels:
    app: {service}
spec:
  ports:
  - port: 8000
    targetPort: {port}
  selector:
    app: {service}
"""
    
    with open(os.path.join(k8s_dir, f"{service}.yaml"), "w") as f:
        f.write(manifest)

for srv in ["frontend", "orders", "inventory", "payments"]:
    create_k8s_manifest(srv)

# 3. Locust file
locust_dir = os.path.join(base_dir, "locust")
os.makedirs(locust_dir, exist_ok=True)

locustfile = """from locust import HttpUser, task, between

class FlexaScaleUser(HttpUser):
    wait_time = between(1, 2)

    @task
    def checkout_flow(self):
        self.client.post("/api/checkout")
        
    @task(3)
    def index_page(self):
        self.client.get("/")
"""

with open(os.path.join(locust_dir, "locustfile.py"), "w") as f:
    f.write(locustfile)

print("Successfully created orchestration and load testing files.")
