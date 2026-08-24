# FlexaScale

FlexaScale is an RL-based Kubernetes autoscaling system that combines:

- Kubernetes
- Prometheus metrics
- dependency-aware state representation
- Graph Neural Networks
- PPO reinforcement learning
- safe execution with HPA fallback

## Architecture

Metrics → State Builder → GNN → PPO Policy → Safety Layer → Kubernetes

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
