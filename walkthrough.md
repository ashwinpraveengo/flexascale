# FlexaScale Demo Microservices Setup

The demo microservices application has been successfully created. This application will act as the target environment for the FlexaScale RL auto-scaling agent.

## Architecture & Components

The application follows a chain architecture to simulate inter-service dependencies, which is critical for demonstrating your agent's ability to model upstream and downstream dependencies.

```mermaid
graph LR
    User[User/Locust] -->|POST /api/checkout| Frontend
    Frontend -->|POST /api/orders| Orders
    Orders -->|POST /api/inventory/reserve| Inventory
    Inventory -->|POST /api/payments/charge| Payments
```

> [!NOTE]
> Each service has been built with Python 3.11 and **FastAPI**, and is instrumented using `prometheus-fastapi-instrumentator`. This exposes a `/metrics` endpoint on each service by default, allowing Prometheus to easily scrape RPS and latency data.

We created 4 separate directories (`frontend`, `orders`, `inventory`, `payments`), each containing:
- `main.py`: The FastAPI application code.
- `requirements.txt`: Python dependencies (`fastapi`, `uvicorn`, `requests`, `prometheus-fastapi-instrumentator`).
- `Dockerfile`: Instructions for containerizing the service.

## Orchestration

> [!TIP]
> You can run the entire environment locally without Kubernetes using Docker Compose.

- **[docker-compose.yml](file:///home/ghanasyam/Desktop/S7/flexascale/app/docker-compose.yml)**: Created at the root to facilitate local testing and building of all images.
- **[k8s/](file:///home/ghanasyam/Desktop/S7/flexascale/app/k8s/)**: Contains Kubernetes Deployments and Services for each of the microservices. They are pre-configured with standard resource requests and limits (`100m`/`500m` CPU, `128Mi`/`256Mi` RAM).

## Load Simulation

- **[locustfile.py](file:///home/ghanasyam/Desktop/S7/flexascale/app/locust/locustfile.py)**: Contains a Locust load testing script that simulates user checkout flows. This will be used to simulate traffic spikes and test the agent's response time and scaling actions.

## Next Steps

1. To test everything locally:
```bash
cd /home/ghanasyam/Desktop/S7/flexascale/app
docker-compose up --build
```
2. In a separate terminal, to test the load generator:
```bash
cd /home/ghanasyam/Desktop/S7/flexascale/app/locust
locust -f locustfile.py --host=http://localhost:8000
```
3. To deploy to your local Minikube cluster (make sure you push your images to a registry or build them inside minikube):
```bash
kubectl apply -f k8s/
```
