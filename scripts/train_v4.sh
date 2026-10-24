#!/usr/bin/env bash
# Train the v4 FlexaScale policy: PPO + GNN on the dependency-aware, unit-free
# simulator (FlexaScaleEnvV2) in 'focal' control: the policy decides for slot 0
# and is rewarded for slot 0, exactly how live neighbourhood inference uses it.
#
# A small grid (learning rate x entropy bonus x seed) runs in parallel; the
# deployed model is chosen afterwards by scripts/evaluate_v4.py using the
# validation services only. Reward weights and simulator settings are fixed.
#
#   ./scripts/train_v4.sh [timesteps]        (default 1000000; ~9 h on 16 cores, 4 runs in parallel)
set -euo pipefail
cd "$(dirname "$0")/.."
STEPS="${1:-1000000}"
mkdir -p models/flexascale_v4 logs
# name           lr     ent    seed
GRID="lr3e-4_ent0.01_s1 3e-4 0.01 1
lr3e-4_ent0.01_s2 3e-4 0.01 2
lr3e-4_ent0.003_s1 3e-4 0.003 1
lr1e-4_ent0.01_s3 1e-4 0.01 3"
while read -r NAME LR ENT SEED; do
  OMP_NUM_THREADS=3 .venv/bin/python -m flexascale.rl.train \
    --env-version 2 --control focal --demand-model normalized --service-sampling random --split-method service \
    --max-replicas 10 --randomize-initial-replicas --peak-replicas-low 1 --peak-replicas-high 4 \
    --cost-weight 1.0 --ent-coef "$ENT" --gamma 0.95 --learning-rate "$LR" --target-kl 0.03 \
    --n-envs 8 --n-steps 256 --batch-size 256 \
    --timesteps "$STEPS" --eval-every 50000 --eval-episodes 30 --seed "$SEED" \
    --save-dir "models/flexascale_v4/$NAME" > "logs/train_v4_$NAME.log" 2>&1 &
done <<< "$GRID"
wait
echo "done: models/flexascale_v4/*"
