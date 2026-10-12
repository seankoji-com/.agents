#!/usr/bin/env python3
"""Compatibility adapter for the installed shared worker registry API."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.worker_registry import *  # noqa: F401,F403
