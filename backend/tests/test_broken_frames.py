# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from types import SimpleNamespace

from app.media.rtsp_source import broken_packet


class Packet(bytes):
    is_corrupt = False


def test_whole_jpeg_frames_pass_and_broken_ones_are_refused():
    whole = Packet(b"\xff\xd8" + b"\x12\xff\x00\x34" * 50 + b"\xff\xd9")
    assert not broken_packet(whole, True)
    assert not broken_packet(Packet(bytes(whole) + b"\x00\x00"), True)  # padding after the end
    assert broken_packet(Packet(bytes(whole)[:-40]), True)  # cut off: no end-of-image
    assert broken_packet(Packet(bytes(whole)[10:]), True)  # no start-of-image
    two = Packet(bytes(whole)[:-2] + bytes(whole))  # two pictures run together
    assert broken_packet(two, True)
    flagged = Packet(bytes(whole))
    flagged.is_corrupt = True
    assert broken_packet(flagged, True)
    # Other codecs are only checked for the demuxer's corrupt flag.
    assert not broken_packet(Packet(b"\x00\x00\x01\x65"), False)
    assert broken_packet(SimpleNamespace(is_corrupt=True), False)
