#!/usr/bin/env python3
"""Shortcut so you can run `python bots.py ...` from the repository root."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent / "plugin/skills/mobile-bots/scripts/bots.py"), run_name="__main__")
