from app.services.clock_check import ClockRate


def test_matching_clocks_show_no_drift():
    rate = ClockRate()
    for second in range(0, 601, 5):
        rate.observe(1000.0 + second, local=50.0 + second)
    assert rate.drift_percent == 0.0
    assert rate.report()["warning"] is False


def test_fast_local_clock_is_reported_as_drift():
    """This morning's case: WSL counted 61.3 s for 55.7 s of real time."""
    rate = ClockRate()
    for second in range(0, 601, 5):
        rate.observe(1000.0 + second, local=50.0 + second * 1.099)
    assert rate.drift_percent == 9.9
    assert rate.report()["warning"] is True


def test_short_spans_and_node_reboots_do_not_report():
    rate = ClockRate()
    rate.observe(1000.0, local=0.0)
    assert rate.observe(1100.0, local=110.0) is None  # under five minutes
    rate.observe(5.0, local=200.0)  # node rebooted: start again
    assert rate.observe(200.0, local=395.0) is None
