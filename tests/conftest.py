import json
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def synthetic_scenarios():
    path = Path(__file__).parent / "fixtures" / "scenarios.json"
    return json.loads(path.read_text(encoding="utf-8"))
