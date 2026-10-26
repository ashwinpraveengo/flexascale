#!/usr/bin/env bash
# Train the v6 FlexaScale policy on the control-loop simulator (FlexaScaleEnvV3:
# 15 s decisions, pod start-up delay, 1-minute CPU lag, the operator's guards,
# native-HPA neighbours) with replica-delta actions -2..+3. Warm start: imitate
# native HPA's ratio rule (actor + critic), then PPO fine-tuning. Protocol:
# docs/POLICY_V6.md; selection and test: scripts/evaluate_v6.py.
#
#   ./scripts/train_v6.sh [timesteps]        (default 1500000; ~40 min on 16 cores; use systemd-inhibit on a laptop)
set -euo pipefail
cd "$(dirname "$0")/.."
STEPS="${1:-1500000}"
mkdir -p models/flexascale_v6 logs
# name        lr     seed
GRID="lr1e-4_s1 1e-4 1
lr1e-4_s2 1e-4 2
lr3e-5_s1 3e-5 1
lr3e-5_s2 3e-5 2"
while read -r NAME LR SEED; do
  OMP_NUM_THREADS=3 .venv/bin/python -m flexascale.rl.train \
    --env-version 3 --control focal --demand-model normalized --service-sampling random --split-method service \
    --max-replicas 10 --randomize-initial-replicas --peak-replicas-low 1 --peak-replicas-high 4 \
    --cost-weight 1.0 --ent-coef 0.001 --gamma 0.97 --learning-rate "$LR" --target-kl 0.02 --clip-range 0.1 \
    --warm-start hpa --warm-start-episodes 3000 \
    --n-envs 8 --n-steps 256 --batch-size 256 \
    --timesteps "$STEPS" --eval-every 150000 --eval-episodes 30 --seed "$SEED" \
    --save-dir "models/flexascale_v6/$NAME" > "logs/train_v6_$NAME.log" 2>&1 &
done <<< "$GRID"
wait
echo "done: models/flexascale_v6/*"
