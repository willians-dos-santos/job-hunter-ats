import pytest
import respx
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, ANY

from src.main import CrawlerOrchestrator, load_config
from src.models import TargetCompany, JobOpening
from src.filters import JobFilter
from src.notifiers import NotificationDispatcher, TelegramNotifier
from src.storage import SQLiteStorage, SupabaseStorage


@pytest.fixture
def sample_config_file(tmp_path):
    config = {
        "concurrency_limit": 2,
        "storage_type": "sqlite",
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
    respx_mock.get("https://portal.gupy.io/api/job-search/jobs").respond(
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
    # From gupy_jobs: "Analista Desenvolvedor Backend Sr", "Remoto"
    # Total new matching jobs: 3
    assert len(notified_jobs) == 3
    job_ids = [j.job_id for j in notified_jobs]
    assert "greenhouse:acme:4123456" in job_ids
    assert "lever:techcorp:a1b2c3d4-e5f6-7890-abcd-ef1234567890" in job_ids
    assert "gupy_12668014" in job_ids

    # Second crawl run: all jobs are marked as seen, notified_jobs is 0
    second_run_notified = await orchestrator.run()
    assert len(second_run_notified) == 0


def test_orchestrator_initializes_supabase_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://mock.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "mock-key")
    config = {
        "concurrency_limit": 1,
        "storage_type": "supabase",
        "targets": [],
    }
    file_path = tmp_path / "supabase_config.yaml"
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    orchestrator = CrawlerOrchestrator.from_config_file(str(file_path))
    assert isinstance(orchestrator.storage, SupabaseStorage)


def test_orchestrator_falls_back_to_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    config = {
        "concurrency_limit": 1,
        "database_path": str(tmp_path / "fallback.db"),
        "targets": [],
    }
    file_path = tmp_path / "fallback_config.yaml"
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    orchestrator = CrawlerOrchestrator.from_config_file(str(file_path))
    assert isinstance(orchestrator.storage, SQLiteStorage)


@pytest.mark.asyncio
async def test_orchestrator_skips_telegram_notification_for_dedup_key_duplicate():
    mock_telegram = AsyncMock(spec=TelegramNotifier)
    mock_telegram.is_configured = True
    mock_telegram.notify = AsyncMock(return_value=True)

    dispatcher = NotificationDispatcher(telegram_notifier=mock_telegram)

    mock_storage = AsyncMock()
    mock_storage.filter_new_jobs = AsyncMock(side_effect=lambda jobs: list(jobs))
    # First job persists successfully; second job is rejected as semantic duplicate
    mock_storage.save_job = AsyncMock(side_effect=[True, False])

    job1 = JobOpening(
        job_id="gupy:1001",
        source="gupy",
        company="Acme Corp",
        title="Software Engineer",
        location="Remote",
        url="https://example.com/1",
    )
    job2 = JobOpening(
        job_id="gupy:1002",
        source="gupy",
        company="Acme Corp",
        title="Software Engineer",
        location="Remote",
        url="https://example.com/2",
    )
    assert job1.dedup_key == job2.dedup_key

    mock_collector = AsyncMock()
    mock_collector.fetch_jobs.return_value = [job1, job2]

    target = TargetCompany(name="acme", source="gupy")
    orchestrator = CrawlerOrchestrator(
        targets=[target],
        job_filter=JobFilter(),
        storage=mock_storage,
        dispatcher=dispatcher,
    )
    orchestrator.collectors["gupy"] = mock_collector

    notified = await orchestrator.run()

    # Only job1 is notified; job2 was skipped due to dedup_key collision
    assert len(notified) == 1
    assert notified[0].job_id == "gupy:1001"
    mock_telegram.notify.assert_called_once_with(job1, client=ANY)


@pytest.mark.asyncio
async def test_orchestrator_with_supabase_storage_dedup_skips_telegram():
    mock_telegram = AsyncMock(spec=TelegramNotifier)
    mock_telegram.is_configured = True
    mock_telegram.notify = AsyncMock(return_value=True)

    dispatcher = NotificationDispatcher(telegram_notifier=mock_telegram)

    # SupabaseStorage with mocked Supabase client
    storage = SupabaseStorage(url="https://fake.supabase.co", key="fake-key")

    mock_client = AsyncMock()
    mock_execute_first = AsyncMock()
    mock_execute_first.data = [{"id": "gupy:1001"}]
    mock_execute_second = AsyncMock()
    mock_execute_second.data = []  # Conflict on dedup_key ignored

    mock_table = MagicMock()
    mock_table.upsert.return_value.execute = AsyncMock(
        side_effect=[mock_execute_first, mock_execute_second]
    )
    mock_client.table.return_value = mock_table

    with patch.object(storage, "get_client", AsyncMock(return_value=mock_client)), \
         patch.object(storage, "is_seen", AsyncMock(return_value=False)):

        job1 = JobOpening(
            job_id="gupy:1001",
            source="gupy",
            company="Acme Corp",
            title="Software Engineer",
            location="Remote",
            url="https://example.com/1",
        )
        job2 = JobOpening(
            job_id="gupy:1002",
            source="gupy",
            company="Acme Corp",
            title="Software Engineer",
            location="Remote",
            url="https://example.com/2",
        )
        assert job1.dedup_key == job2.dedup_key

        mock_collector = AsyncMock()
        mock_collector.fetch_jobs.return_value = [job1, job2]

        target = TargetCompany(name="acme", source="gupy")
        orchestrator = CrawlerOrchestrator(
            targets=[target],
            job_filter=JobFilter(),
            storage=storage,
            dispatcher=dispatcher,
        )
        orchestrator.collectors["gupy"] = mock_collector

        notified = await orchestrator.run()

        assert len(notified) == 1
        assert notified[0].job_id == "gupy:1001"
        mock_telegram.notify.assert_called_once_with(job1, client=ANY)


