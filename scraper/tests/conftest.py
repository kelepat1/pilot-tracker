"""Shared pytest configuration: make the scraper modules importable from the tests."""

import sys
from pathlib import Path

SCRAPER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRAPER_DIR.parent
FIXTURES_DIR = SCRAPER_DIR / "fixtures"

if str(SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(SCRAPER_DIR))
