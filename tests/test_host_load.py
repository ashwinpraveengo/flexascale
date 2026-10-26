"""Host-load criterion (docs/POLICY_V6.md §5.2): battery periods, overlap and classification."""

from scripts.check_host_load import battery_intervals, classify, overlap_s


def test_battery_intervals_from_upower_history(tmp_path):
    f = tmp_path / "history-charge-Primary.dat"
    f.write_text("100\t94.000\tcharging\n200\t94.000\tdischarging\n260\t90.000\tdischarging\n"
                 "300\t88.000\tcharging\n400\t80.000\tdischarging\n")
    assert battery_intervals(str(f)) == [(200.0, 300.0), (400.0, float("inf"))]
    assert battery_intervals(str(tmp_path / "missing.dat")) is None


def test_overlap_counts_only_the_load_window():
    periods = [(200.0, 300.0), (400.0, float("inf"))]
    assert overlap_s(250, 350, periods) == 50
    assert overlap_s(310, 390, periods) == 0
    assert overlap_s(450, 500, periods) == 50


def test_classify_flags_battery_or_outside_load_above_limit():
    assert classify(0.8, 0) == (False, "")
    assert classify(2.0, 0) == (False, "")  # the limit itself is still normal
    assert classify(5.6, 0) == (True, "5.6 cores outside Kubernetes")
    assert classify(1.0, 218)[0] is True
    assert classify(2.5, 218) == (True, "on battery 218 s; 2.5 cores outside Kubernetes")


def test_classify_reports_unknown_instead_of_guessing():
    assert classify(None, 0) == (None, "unknown (no host CPU data)")
    assert classify(0.7, None) == (None, "unknown (no battery history)")
    # a known reason still flags the run even if the other input is missing
    assert classify(None, 30)[0] is True
