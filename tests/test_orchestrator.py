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
            {"name": "ambev", "source": "Gupy"},
            {"name": "badcompany", "source": "greenhouse"},
        ],
        "filters": {
            "title_keywords": ["Backend"],
            "location_keywords": ["Remote", "Remoto"],
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
    assert len(cfg["targets"]) == 4
    assert cfg["filters"]["title_keywords"] == ["Backend"]


@pytest.mark.asyncio
async def test_orchestrator_run_end_to_end(
    respx_mock, sample_config_file, greenhouse_jobs_raw, lever_jobs_raw, gupy_jobs_raw
):
    # Mock Greenhouse endpoint for acme
    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").respond(
        status_code=200, json=greenhouse_jobs_raw
    )
    # Mock Lever endpoint for techcorp
    respx_mock.get("https://api.lever.co/v0/postings/techcorp?mode=json").respond(
        status_code=200, json=lever_jobs_raw
    )
    # Mock Gupy endpoint for ambev
    respx_mock.get("https://portal.api.gupy.io/api/v1/jobs?careerPageName=ambev&limit=100").respond(
        status_code=200, json=gupy_jobs_raw
    )
    # Mock Greenhouse endpoint for badcompany (returns 404 - fault isolation test)
    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/badcompany/jobs").respond(
        status_code=404
    )

    orchestrator = CrawlerOrchestrator.from_config_file(str(sample_config_file))
    
    # First crawl run
    notified_jobs = await orchestrator.run()

    # From greenhouse_jobs: "Senior Backend Engineer", "Remote, Brazil"
    # From lever_jobs: "Staff Backend Engineer - Python", "Remote, Global"
    # From gupy_jobs: "Desenvolvedor(a) Backend Python Sênior", "Remoto"
    # Total new matching jobs: 3
    assert len(notified_jobs) == 3
    job_ids = [j.job_id for j in notified_jobs]
    assert "greenhouse:acme:4123456" in job_ids
    assert "lever:techcorp:a1b2c3d4-e5f6-7890-abcd-ef1234567890" in job_ids
    assert "gupy_8123456" in job_ids

    # Second crawl run: all jobs are marked as seen, notified_jobs is 0
    second_run_notified = await orchestrator.run()
    assert len(second_run_notified) == 0
