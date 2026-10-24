.PHONY: help build up down restart logs ps seed test test-all helm-lint helm-template k8s-apply k8s-delete clean \
	review-check review-start demo-start review-stop review-status test-framework dashboard-build evaluate

PYTHON ?= ./.venv/bin/python3
PYTEST ?= ./.venv/bin/pytest

help:
	@echo "Review / presentation (scripts/*.sh are the source of truth):"
	@echo "  make review-check   - Preflight only (starts nothing, changes nothing)"
	@echo "  make review-start   - Start port-forwards + Live Lab dashboard (http://127.0.0.1:8090)"
	@echo "  make demo-start     - Same as review-start plus demo checklist"
	@echo "  make review-status  - Cluster, pods, ownership, model, dashboard and URLs"
	@echo "  make review-stop    - Stop managed processes and restore native HPA ownership"
	@echo "  make test-framework - FlexaScale framework tests (no cluster needed)"
	@echo "  make dashboard-build- Rebuild the Live Lab UI into src/flexascale/lab/static"
	@echo "  make evaluate       - Held-out simulation evaluation of the trained policies"
	@echo ""
	@echo "FlexaScale E-Commerce Microservices Management Commands:"
	@echo "  make build          - Build all microservice and frontend Docker images"
	@echo "  make up             - Start local development stack with Docker Compose"
	@echo "  make down           - Stop local development stack and remove volumes"
	@echo "  make restart        - Restart all Docker Compose services"
	@echo "  make logs           - Tail all service logs"
	@echo "  make ps             - View running container status"
	@echo "  make seed           - Seed database with users, catalog products, and inventory"
	@echo "  make test           - Run shopping app automated test suite"
	@echo "  make test-all       - Run shopping app tests + FlexaScale framework tests"
	@echo "  make helm-lint      - Lint the Helm chart"
	@echo "  make helm-template  - Render Helm chart templates"
	@echo "  make k8s-apply      - Deploy to Kubernetes namespace flexascale-apps"
	@echo "  make k8s-delete     - Remove application from Kubernetes namespace"

build:
	docker compose build

up:
	docker compose up -d
	@echo "Services started! Frontend: http://localhost:3000 | Gateway: http://localhost:8000"

down:
	docker compose down -v

restart: down up

logs:
	docker compose logs -f

ps:
	docker compose ps

seed:
	DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/ecommerce" $(PYTHON) apps/database/seed.py

test:
	$(PYTEST) tests/shopping-app/ -v

test-all:
	$(PYTEST) tests/ -v

test-framework:
	$(PYTEST) tests/ --ignore=tests/shopping-app -q

review-check:
	./scripts/start_review.sh --check

review-start:
	./scripts/start_review.sh

demo-start:
	./scripts/start_demo.sh

review-status:
	./scripts/review_status.sh

review-stop:
	./scripts/stop_review.sh

dashboard-build:
	cd dashboard && npm ci && npm run build

evaluate:
	$(PYTHON) scripts/evaluate_policies.py --episodes 200

helm-lint:
	helm lint charts/shopping-app

helm-template:
	helm template shopping-app charts/shopping-app

k8s-apply:
	kubectl apply -f deploy/kubernetes/

k8s-delete:
	kubectl delete -f deploy/kubernetes/ --ignore-not-found

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	rm -rf apps/shopping-frontend/dist apps/shopping-frontend/node_modules
