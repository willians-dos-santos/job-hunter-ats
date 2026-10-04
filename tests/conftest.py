import json
from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def greenhouse_jobs_raw() -> dict:
    with open(FIXTURES_DIR / "greenhouse_jobs.json", "r", encoding="utf-8") as f:
        return json.load(f)

@pytest.fixture
def greenhouse_edge_cases_raw() -> dict:
    with open(FIXTURES_DIR / "greenhouse_edge_cases.json", "r", encoding="utf-8") as f:
        return json.load(f)

@pytest.fixture
def lever_jobs_raw() -> list:
    with open(FIXTURES_DIR / "lever_jobs.json", "r", encoding="utf-8") as f:
        return json.load(f)

@pytest.fixture
def lever_edge_cases_raw() -> list:
    with open(FIXTURES_DIR / "lever_edge_cases.json", "r", encoding="utf-8") as f:
        return json.load(f)
