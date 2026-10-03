from pathlib import Path
import sys
import pytest

# Resolve app imports from either repository root or backend/.
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from .fixture_helpers import load_all_fixtures


@pytest.fixture
def all_investigation_fixtures():
    return load_all_fixtures()
