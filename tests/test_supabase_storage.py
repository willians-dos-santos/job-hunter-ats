import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from src.models import JobOpening
from src.storage import SupabaseStorage  # ou de onde for exportado

@pytest.fixture
def mock_job():
    return JobOpening(
        id="gupy:998877",
        external_id="998877",
        title="Desenvolvedor Python Pleno",
        company="Tech Corp",
        location="Remoto",
        url="https://tech.gupy.io/job/998877",
        ats="gupy",
        published_at=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
    )

@pytest.mark.asyncio
async def test_supabase_is_seen_true():
    storage = SupabaseStorage(url="https://fake.supabase.co", key="fake-key")
    
    # Mock da cadeia: client.table("jobs").select("id").eq("id", job_id).execute()
    mock_client = AsyncMock()
    mock_execute = AsyncMock()
    mock_execute.data = [{"id": "gupy:998877"}]
    
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.execute = AsyncMock(return_value=mock_execute)
    mock_client.table.return_value = mock_table

    with patch.object(storage, "get_client", AsyncMock(return_value=mock_client)):
        seen = await storage.is_seen("gupy:998877")
        assert seen is True
        mock_client.table.assert_called_with("jobs")

@pytest.mark.asyncio
async def test_supabase_is_seen_false():
    storage = SupabaseStorage(url="https://fake.supabase.co", key="fake-key")
    
    mock_client = AsyncMock()
    mock_execute = AsyncMock()
    mock_execute.data = []
    
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.execute = AsyncMock(return_value=mock_execute)
    mock_client.table.return_value = mock_table

    with patch.object(storage, "get_client", AsyncMock(return_value=mock_client)):
        seen = await storage.is_seen("gupy:111111")
        assert seen is False

@pytest.mark.asyncio
async def test_supabase_save_job_success(mock_job):
    storage = SupabaseStorage(url="https://fake.supabase.co", key="fake-key")
    
    mock_client = AsyncMock()
    mock_execute = AsyncMock()
    mock_execute.data = [{"id": "gupy:998877"}]
    
    mock_table = MagicMock()
    mock_table.upsert.return_value.execute = AsyncMock(return_value=mock_execute)
    mock_client.table.return_value = mock_table

    with patch.object(storage, "get_client", AsyncMock(return_value=mock_client)):
        success = await storage.save_job(mock_job)
        assert success is True
        mock_table.upsert.assert_called_once()
        args, kwargs = mock_table.upsert.call_args
        assert args[0]["id"] == "gupy:998877"
        assert args[0]["ats"] == "gupy"
        assert args[0]["external_id"] == "998877"
        assert kwargs.get("on_conflict") == "id"


def test_supabase_storage_missing_credentials_raises_value_error(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    with pytest.raises(ValueError, match="SUPABASE_URL and SUPABASE_KEY"):
        SupabaseStorage()

    with pytest.raises(ValueError):
        SupabaseStorage(url="", key="valid_key")

    with pytest.raises(ValueError):
        SupabaseStorage(url="https://valid.url", key="")


def test_supabase_storage_loads_from_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://env.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "env-secret-key")

    storage = SupabaseStorage()
    assert storage.url == "https://env.supabase.co"
    assert storage.key == "env-secret-key"


@pytest.mark.asyncio
async def test_supabase_save_job_transient_error_returns_false(mock_job):
    storage = SupabaseStorage(url="https://fake.supabase.co", key="fake-key")

    mock_client = AsyncMock()
    mock_table = MagicMock()
    mock_table.upsert.return_value.execute = AsyncMock(side_effect=Exception("503 Service Unavailable"))
    mock_client.table.return_value = mock_table

    with patch.object(storage, "get_client", AsyncMock(return_value=mock_client)):
        success = await storage.save_job(mock_job)
        assert success is False


@pytest.mark.asyncio
async def test_supabase_is_seen_error_returns_false():
    storage = SupabaseStorage(url="https://fake.supabase.co", key="fake-key")

    mock_client = AsyncMock()
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.execute = AsyncMock(
        side_effect=Exception("Connection timed out")
    )
    mock_client.table.return_value = mock_table

    with patch.object(storage, "get_client", AsyncMock(return_value=mock_client)):
        seen = await storage.is_seen("gupy:998877")
        assert seen is False


@pytest.mark.asyncio
async def test_supabase_save_job_date_serialization_and_null_location():
    storage = SupabaseStorage(url="https://fake.supabase.co", key="fake-key")
    job = JobOpening(
        job_id="greenhouse:acme:123",
        source="greenhouse",
        company="acme",
        title="Backend Dev",
        location=None,
        url="https://example.com/jobs/123",
        published_at=datetime(2026, 10, 5, 12, 0),  # Naive datetime
    )

    mock_client = AsyncMock()
    mock_execute = AsyncMock()
    mock_table = MagicMock()
    mock_table.upsert.return_value.execute = AsyncMock(return_value=mock_execute)
    mock_client.table.return_value = mock_table

    with patch.object(storage, "get_client", AsyncMock(return_value=mock_client)):
        success = await storage.save_job(job)
        assert success is True
        args, kwargs = mock_table.upsert.call_args
        payload = args[0]
        assert payload["id"] == "greenhouse:123"
        assert payload["ats"] == "greenhouse"
        assert payload["external_id"] == "123"
        assert payload["location"] is None
        assert payload["published_at"] == "2026-10-05T12:00:00+00:00"
        assert "created_at" in payload


@pytest.mark.asyncio
async def test_supabase_filter_new_jobs_and_mark_as_seen(mock_job):
    storage = SupabaseStorage(url="https://fake.supabase.co", key="fake-key")
    job2 = JobOpening(
        job_id="gupy:111",
        source="gupy",
        company="Other",
        title="Frontend",
        url="https://example.com",
    )

    with patch.object(storage, "is_seen", AsyncMock(side_effect=[True, False])):
        new_jobs = await storage.filter_new_jobs([mock_job, job2])
        assert len(new_jobs) == 1
        assert new_jobs[0].job_id == "gupy:111"

    with patch.object(storage, "save_job", AsyncMock(return_value=True)) as mock_save:
        assert await storage.mark_as_seen(mock_job) is True
        mock_save.assert_called_once_with(mock_job)


@pytest.mark.asyncio
async def test_supabase_get_client_initializes_once():
    storage = SupabaseStorage(url="https://fake.supabase.co", key="fake-key")
    mock_client_instance = AsyncMock()

    with patch("src.storage.create_async_client", AsyncMock(return_value=mock_client_instance)) as mock_create:
        c1 = await storage.get_client()
        c2 = await storage.get_client()
        assert c1 is mock_client_instance
        assert c2 is mock_client_instance
        mock_create.assert_called_once_with("https://fake.supabase.co", "fake-key")