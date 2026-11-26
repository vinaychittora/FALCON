# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Runs only in the isolated BirdNET environment; no analysis or coordinates here."""

import shutil
import sys

from birdnet_analyzer import config, utils

utils.ensure_model_exists()
shutil.copyfile(config.BIRDNET_LABELS_FILE, sys.argv[1])
