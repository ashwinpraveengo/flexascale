"""Warm start: the HPA teacher reads the version-2 observation the model sees live."""

import numpy as np

from flexascale.rl.imitation import HPA_DOWN, HPA_UP, hpa_teacher


def test_teacher_matches_hpa_rule_per_slot():
    obs = np.zeros(20, dtype=np.float32)
    obs[[0, 5, 10, 15]] = [0.90, 0.70, 0.40, HPA_UP]
    assert hpa_teacher(obs).tolist() == [2, 1, 0, 1]
    obs[15] = HPA_DOWN - 1e-3
    assert hpa_teacher(obs)[3] == 0


def test_teacher_ignores_non_cpu_features():
    obs = np.tile(np.array([0.70, 1.0, 1.0, 3.0, 5.0], dtype=np.float32), 4)
    assert hpa_teacher(obs).tolist() == [1, 1, 1, 1]
