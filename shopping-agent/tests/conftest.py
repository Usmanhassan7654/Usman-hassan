import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shopping_agent.catalog import load_file  # noqa: E402


@pytest.fixture
def catalog():
    return load_file(ROOT / "data" / "sample_grocery.csv")
