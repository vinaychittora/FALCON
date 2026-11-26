# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import argparse
from pathlib import Path

from app.media.probe import probe

parser = argparse.ArgumentParser(
    description="Inspect original video metadata without transcoding"
)
parser.add_argument("video", type=Path)
args = parser.parse_args()
print(probe(args.video.resolve()).model_dump_json(indent=2))
