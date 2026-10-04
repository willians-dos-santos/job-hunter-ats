import pytest
import respx
import yaml
from pathlib import Path
from src.main import CrawlerOrchestrator, load_config
from src.models import TargetCompany, JobOpening
from src.filters import JobFilter
from src.storage import SQLiteStorage


@pytest.fixture
def sample_config_file(tmp_path):
    config = {
        "concurrency_limit": 2,
        "database_path": str(tmp_path / "orchestrator_test.db"),
        "targets": [
            {"name": "acme", "source": "greenhouse"},
            {"name": "techcorp", "source": "lever"},
            {"name": "badcompany", "source": "greenhouse"},
        ],
        "filters": {
            "title_keywords": ["Backend"],
            "location_keywords": ["Remote"],
        },
        "telegram": {
            "enabled": False,
            "bot_token": None,
            "chat_id": None,
        },
    }
    file_path = tmp_path / "config.yaml"
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return file_path


def test_load_config(sample_config_file):
    cfg = load_config(str(sample_config_file))
    assert cfg["concurrency_limit"] == 2
    assert len(cfg["targets"]) == 3
    assert cfg["filters"]["title_keywords"] == ["Backend"]


@pytest.mark.asyncio
async def test_orchestrator_run_end_to_end(respx_mock, sample_config_file, greenhouse_jobs_raw, lever_jobs_raw):
    # Mock Greenhouse endpoint for acme
    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").respond(
        status_code=200, json=greenhouse_jobs_raw
    )
    # Mock Lever endpoint for techcorp
    respx_mock.get("https://api.lever.co/v0/postings/techcorp?mode=json").respond(
        status_code=200, json=lever_jobs_raw
    )
    # Mock Greenhouse endpoint for badcompany (returns 404 - fault isolation test)
    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/badcompany/jobs").respond(
        status_code=404
    )

    orchestrator = CrawlerOrchestrator.from_config_file(str(sample_config_file))
    
    # First crawl run
    notified_jobs = await orchestrator.run()

    # From greenhouse_jobs:
    # 1. "Senior Backend Engineer", "Remote, Brazil" -> matches "Backend" & "Remote"
    # 2. "Frontend Developer", "New York, NY" -> does not match
    # From lever_jobs:
    # 1. "Staff Backend Engineer - Python", "Remote, Global" -> matches "Backend" & "Remote"
    # 2. "Data Analyst", "London, UK" -> does not match
    # Total new matching jobs: 2
    assert len(notified_jobs) == 2
    job_ids = [j.job_id for j in notified_jobs]
    assert "greenhouse:acme:4123456" in job_ids
    assert "lever:techcorp:a1b2c3d4-e5f6-7890-abcd-ef1234567890" in job_ids

    # Second crawl run: both jobs are now marked as seen, so notified_jobs should be 0 (SC-002: 0% false positives)
    second_run_notified = await orchestrator.run()
    assert len(second_run_notified) == 0
