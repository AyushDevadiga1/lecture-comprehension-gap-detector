"""Test module hook ensuring hermetic DBs from *_usage/media test suites leave
the dev lecgap.db alone (they set LECGAP_DATABASE_URL before importing main)."""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))