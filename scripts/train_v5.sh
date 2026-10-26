#!/usr/bin/env bash
# Train the v5 FlexaScale policy: imitate the HPA-like rule (actor + critic),
# then fine-tune with PPO on the unchanged v4 simulator and reward. See
# docs/POLICY_V5.md for the fixed protocol; selection: scripts/evaluate_v5.py.
#
#   ./scripts/train_v5.sh [timesteps]        (default 500000; ~20 min on 16 cores; use systemd-inhibit on a laptop)
set -euo pipefail
cd "$(dirname "$0")/.."
STEPS="${1:-500000}"
mkdir -p models/flexascale_v5 logs
# name        lr     seed
GRID="lr1e-4_s1 1e-4 1
lr1e-4_s2 1e-4 2
lr3e-5_s1 3e-5 1
lr3e-5_s2 3e-5 2"
while read -r NAME LR SEED; do
  OMP_NUM_THREADS=3 .venv/bin/python -m flexascale.rl.train \
    --env-version 2 --control focal --demand-model normalized --service-sampling random --split-method service \
    --max-replicas 10 --randomize-initial-replicas --peak-replicas-low 1 --peak-replicas-high 4 \
    --cost-weight 1.0 --ent-coef 0.001 --gamma 0.95 --learning-rate "$LR" --target-kl 0.02 --clip-range 0.1 \
    --warm-start hpa --warm-start-episodes 3000 \
    --n-envs 8 --n-steps 256 --batch-size 256 \
    --timesteps "$STEPS" --eval-every 50000 --eval-episodes 30 --seed "$SEED" \
    --save-dir "models/flexascale_v5/$NAME" > "logs/train_v5_$NAME.log" 2>&1 &
done <<< "$GRID"
wait
echo "done: models/flexascale_v5/*"
