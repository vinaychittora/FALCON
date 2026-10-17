import argparse
from pathlib import Path

from app.media.probe import probe

parser = argparse.ArgumentParser(
    description="Inspect original video metadata without transcoding"
)
parser.add_argument("video", type=Path)
args = parser.parse_args()
print(probe(args.video.resolve()).model_dump_json(indent=2))
