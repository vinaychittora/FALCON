"""Runs only in the isolated BirdNET environment; no analysis or coordinates here."""

import shutil
import sys

from birdnet_analyzer import config, utils

utils.ensure_model_exists()
shutil.copyfile(config.BIRDNET_LABELS_FILE, sys.argv[1])
