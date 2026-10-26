"""Benchmark statistics: t critical values and the Welch difference used for Auto vs tuned HPA."""

import math

from flexascale.lab.benchmark import mean_ci, t95, welch_diff


def test_t95_is_exact_in_the_table_and_conservative_between_entries():
    assert t95(17) == 2.110
    assert t95(17.9) == t95(17)
    # 21..24 are not tabulated: use df 20 (larger critical value, wider interval), not df 25.
    assert t95(21) == t95(24) == t95(20) == 2.086
    assert t95(500) == 1.980
    assert math.isnan(t95(0.5))


def test_welch_diff_matches_a_hand_computation():
    # a: mean 2.5, var/n = 1.6667/4; b: mean 4, var/n = 4/3; se = sqrt(1.75); Welch df = 3.23 -> t(3) = 3.182
    d = welch_diff([1, 2, 3, 4], [2, 4, 6])
    assert d["n_a"] == 4 and d["n_b"] == 3
    assert math.isclose(d["mean"], -1.5)
    assert math.isclose(d["df"], 3.0625 / (0.41666667 ** 2 / 3 + 1.33333333 ** 2 / 2), rel_tol=1e-6)
    half = 3.182 * math.sqrt(1.75)
    assert math.isclose(d["ci95"][0], -1.5 - half, rel_tol=1e-9)
    assert math.isclose(d["ci95"][1], -1.5 + half, rel_tol=1e-9)


def test_welch_diff_needs_two_values_per_group_and_ignores_missing():
    assert welch_diff([1.0], [1.0, 2.0]) is None
    assert welch_diff([1.0, None, float("nan")], [1.0, 2.0]) is None
    assert welch_diff([1.0, 3.0, None], [0.0, 2.0])["mean"] == 1.0


def test_mean_ci_unchanged_for_tabulated_df():
    x = mean_ci([-1.0, -3.0, -2.0])
    assert math.isclose(x["mean"], -2.0)
    assert math.isclose(x["ci95"][1] - x["mean"], 4.303 * 1.0 / math.sqrt(3))
