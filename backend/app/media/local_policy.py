# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Uploaded originals are media files, never playlists or network manifests."""

# Restrict both probing and decoding. A misleading .mp4 extension must not make
# FFmpeg follow an HLS/concat playlist's local paths or network URLs.
LOCAL_DEMUXERS = "mov,matroska,avi,mpegts,m4v,wav,mp3,flac,ogg,aac"


def local_media_options() -> dict[str, str]:
    return {"protocol_whitelist": "file", "format_whitelist": LOCAL_DEMUXERS}


def local_media_arguments() -> list[str]:
    return [
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        LOCAL_DEMUXERS,
    ]
