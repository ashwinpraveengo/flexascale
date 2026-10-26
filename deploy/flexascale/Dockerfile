# FlexaScale operator image (CPU-only PyTorch). Build from the repository root:
#   docker build -f deploy/flexascale/Dockerfile -t flexascale:0.5.0 .   (after scripts/promote_v7.py)
FROM python:3.11-slim

ARG KUBECTL_VERSION=v1.31.0
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
 && chmod +x /usr/local/bin/kubectl \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY deploy/flexascale/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r /tmp/requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
COPY scripts/run_operator.py scripts/run_api.py ./scripts/
COPY models/flexascale_v5/best_model ./models/flexascale_v5/best_model
COPY models/flexascale_v5/model_card.json ./models/flexascale_v5/model_card.json
# v7 graph policy (docs/POLICY_V7.md), written by scripts/promote_v7.py; select it with policy.model_path
COPY models/flexascale_v7/best_model ./models/flexascale_v7/best_model
COPY models/flexascale_v7/model_card.json ./models/flexascale_v7/model_card.json

USER 65534
ENTRYPOINT ["python", "/app/scripts/run_operator.py"]
CMD ["--help"]
