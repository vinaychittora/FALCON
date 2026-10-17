from app.media.audio_clock import AudioReceiveClock


def observe(clock: AudioReceiveClock, received: float, pts: float = 0.0) -> str | None:
    return clock.observe(
        samples=1024,
        sample_rate=8000,
        received=received,
        pts=pts,
        format_key="s16/mono",
    )


def test_continuous_samples_survive_derived_pts_jumps_and_tcp_bursts() -> None:
    # Relative arrivals from 92 consecutive PCMA RTP headers. No packet payload,
    # addresses, credentials, SSRC or original RTP timestamps are retained.
    # Every header advanced one sequence and 1024 samples at 8 kHz.
    arrivals = [
        0.0,
        0.090808,
        0.258785,
        0.335848,
        0.502065,
        0.668617,
        0.748956,
        0.908108,
        0.989899,
        1.158661,
        1.318168,
        1.399829,
        1.56517,
        1.643359,
        1.83136,
        1.981763,
        2.056886,
        2.218467,
        2.309621,
        2.465316,
        2.631477,
        2.710808,
        2.875778,
        2.9815,
        3.134389,
        3.284968,
        3.374622,
        3.531726,
        3.618493,
        3.885787,
        3.952362,
        4.03044,
        4.198089,
        4.280424,
        4.455792,
        4.607354,
        4.686485,
        4.851353,
        4.929266,
        5.093551,
        5.263724,
        5.33994,
        5.50379,
        5.597144,
        5.75099,
        5.93489,
        6.011626,
        6.161505,
        6.249386,
        6.423558,
        6.569382,
        6.660715,
        6.830685,
        6.907566,
        7.068828,
        7.239904,
        7.31568,
        7.483792,
        7.557187,
        7.724112,
        8.011093,
        8.011133,
        8.137653,
        8.215775,
        8.379401,
        8.54861,
        8.628513,
        8.81494,
        8.887227,
        9.039007,
        9.20361,
        9.29694,
        9.450255,
        9.542117,
        9.709052,
        9.864605,
        10.062698,
        10.124449,
        10.196765,
        10.364346,
        10.520581,
        10.609079,
        10.778304,
        10.856533,
        11.021626,
        11.189507,
        11.263834,
        11.440401,
        11.512117,
        11.675559,
        11.844527,
        11.925115,
    ]
    clock = AudioReceiveClock()
    for index, received in enumerate(arrivals):
        # Synthetic derived-PTS jumps exercise the old false-reset trigger.
        pts = index * 0.128 + (1.0 if (index // 5) % 2 else 0.0)
        assert observe(clock, received, pts) is None
        if index == 71:  # A nine-second PCM window has been emitted.
            clock.checkpoint()
    assert clock.resets == 0
    assert clock.pts_jumps == 18
    assert clock.decoded_samples == 92 * 1024
    assert clock.metrics()["audio_sample_rate"] == 8000


def test_real_receive_and_sample_coverage_gaps_reset_partial_window() -> None:
    clock = AudioReceiveClock()
    assert observe(clock, 0) is None
    assert observe(clock, 0.128, 0.128) is None
    assert observe(clock, 2.5, 0.256) == "receive gap"
    assert clock.metrics()["audio_last_gap_receive_ms"] == 2372.0
    assert observe(clock, 2.628, 0.384) is None
    # Neither individual pause reaches the hard two-second timeout, but decoded
    # sample duration no longer covers elapsed receiving time within tolerance.
    assert observe(clock, 3.156, 0.512) is None
    assert observe(clock, 3.684, 0.640) == "received audio sample coverage gap"
    assert clock.resets == 2
    assert clock.last_gap_coverage_ms == 800.0


def test_format_change_resets_window_and_new_connection_discards_old_clock() -> None:
    clock = AudioReceiveClock()
    assert observe(clock, 0) is None
    assert (
        clock.observe(
            samples=2048, sample_rate=16000, received=0.128, pts=0.128, format_key="s16/mono"
        )
        == "decoded audio format changed"
    )
    clock.begin_connection()
    assert observe(clock, 20, 300) is None
    assert clock.resets == 1
    assert clock.sample_rate == 8000
