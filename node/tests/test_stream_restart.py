# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import sys

from falcon_node.agent import retry_delay
from falcon_node.media import Pipeline


def test_a_blinking_camera_is_back_within_two_seconds_then_backs_off():
    assert [retry_delay(n) for n in (1, 2, 3)] == [2.0, 2.0, 2.0]
    assert retry_delay(4) == 4.0 and retry_delay(5) == 8.0
    assert retry_delay(20) == 60.0


def test_a_stopped_process_reports_its_exit_code_and_last_messages():
    script = "import sys; sys.stderr.write('Device or resource busy\\n'); sys.exit(1)"
    pipeline = Pipeline([[sys.executable, "-c", script]])
    pipeline.processes[0].wait(5)
    import time

    time.sleep(0.2)  # let the stderr reader catch the line
    report = pipeline.exit_report()
    assert len(report) == 1
    assert "exited with code 1" in report[0] and "Device or resource busy" in report[0]
    pipeline.stop()
