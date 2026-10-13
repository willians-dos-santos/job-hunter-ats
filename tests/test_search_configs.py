import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.filters import JobFilter
from src.models import TargetCompany
from src.notifiers import NotificationDispatcher
from src.orchestrator import CrawlerOrchestrator
from src.storage import (
    SearchConfigData,
    SupabaseStorage,
    load_search_configs,
)


def build_mock_supabase_client(data=None, exception=None):
    """Helper to construct a mock Supabase AsyncClient supporting chained queries."""
    mock_client = AsyncMock()
    mock_table = MagicMock()
    mock_query = MagicMock()

    # Chained .eq() calls return mock_query itself
    mock_query.eq.return_value = mock_query

    if exception:
        mock_query.execute = AsyncMock(side_effect=exception)
    else:
        mock_res = MagicMock()
        mock_res.data = data if data is not None else []
        mock_query.execute = AsyncMock(return_value=mock_res)

    mock_table.select.return_value = mock_query
    mock_client.table.return_value = mock_table
    return mock_client, mock_table, mock_query


# ---------------------------------------------------------------------------
# 1. Mapeamento de Categorias e Extração de Metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_search_configs_mapping_all_categories():
    sample_records = [
        {"category": "keyword", "value": "Python", "metadata": {}},
        {"category": "keyword", "value": "FastAPI", "metadata": None},
        {"category": "excluded_keyword", "value": "Junior", "metadata": {}},
        {"category": "excluded_keyword", "value": "Estagio", "metadata": {}},
        {"category": "location", "value": "Remote", "metadata": {}},
        {"category": "location", "value": "Brasil", "metadata": {}},
        {
            "category": "company",
            "value": "gitlab",
            "metadata": {"source": "greenhouse"},
        },
        {
            "category": "company",
            "value": "spotify",
            "metadata": {"source": "lever"},
        },
        {
            "category": "company",
            "value": "Stefanini",
            "metadata": {"source": "Gupy", "slug": "stefanini"},
        },
        {
            "category": "company",
            "value": "Vagas Python",
            "metadata": {"source": "gupy_global", "query": "Python"},
        },
        {
            "category": "ats_filter",
            "value": "global_options",
            "metadata": {
                "max_days_old": 14,
                "exclude_inactive": False,
                "location_exclude": ["US Only"],
            },
        },
    ]

    client, mock_table, mock_query = build_mock_supabase_client(data=sample_records)

    config_data = await load_search_configs(client, user_id="test-user-uuid")

    assert config_data is not None
    assert isinstance(config_data, SearchConfigData)
    assert not config_data.is_empty

    # Keywords mapping
    assert config_data.keywords == ["Python", "FastAPI"]

    # Excluded keywords mapping
    assert config_data.excluded_keywords == ["Junior", "Estagio"]

    # Locations mapping
    assert config_data.locations == ["Remote", "Brasil"]

    # Companies mapping
    assert config_data.companies == ["gitlab", "spotify", "Stefanini", "Vagas Python"]

    # Target company models mapping
    assert len(config_data.target_companies) == 4
    tc_names = [tc.name for tc in config_data.target_companies]
    assert tc_names == ["gitlab", "spotify", "Stefanini", "Vagas Python"]
    assert config_data.target_companies[0].source == "greenhouse"
    assert config_data.target_companies[1].source == "lever"
    assert config_data.target_companies[2].source == "Gupy"
    assert config_data.target_companies[2].slug == "stefanini"
    assert config_data.target_companies[3].source == "gupy_global"
    assert config_data.target_companies[3].query == "Python"

    # ats_filter metadata extraction
    assert config_data.ats_filter["max_days_old"] == 14
    assert config_data.ats_filter["exclude_inactive"] is False
    assert config_data.ats_filter["location_exclude"] == ["US Only"]


@pytest.mark.asyncio
async def test_load_search_configs_handles_json_string_metadata():
    records = [
        {"category": "keyword", "value": "Go", "metadata": "{}"},
        {
            "category": "ats_filter",
            "value": "config",
            "metadata": '{"max_days_old": 7, "exclude_inactive": true}',
        },
    ]
    client, _, _ = build_mock_supabase_client(data=records)

    config_data = await load_search_configs(client, user_id="user-json")
    assert config_data is not None
    assert config_data.keywords == ["Go"]
    assert config_data.ats_filter["max_days_old"] == 7
    assert config_data.ats_filter["exclude_inactive"] is True


# ---------------------------------------------------------------------------
# 2. Critérios da Consulta Supabase (is_active, user_id, colunas)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_search_configs_query_criteria_with_user_id():
    client, mock_table, mock_query = build_mock_supabase_client(
        data=[{"category": "keyword", "value": "Rust", "metadata": {}}]
    )

    await load_search_configs(client, user_id="uuid-456")

    mock_client_table = client.table
    mock_client_table.assert_called_with("search_configs")
    mock_table.select.assert_called_with("category, value, metadata")

    # Verify filtering criteria
    mock_query.eq.assert_any_call("is_active", True)
    mock_query.eq.assert_any_call("user_id", "uuid-456")


@pytest.mark.asyncio
async def test_load_search_configs_query_criteria_without_user_id():
    client, mock_table, mock_query = build_mock_supabase_client(
        data=[{"category": "keyword", "value": "Rust", "metadata": {}}]
    )

    await load_search_configs(client, user_id=None)

    mock_query.eq.assert_called_once_with("is_active", True)


# ---------------------------------------------------------------------------
# 3. Fallback por Lista Vazia
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_search_configs_empty_returns_none():
    client, _, _ = build_mock_supabase_client(data=[])
    result = await load_search_configs(client, user_id="user-empty")
    assert result is None


@pytest.mark.asyncio
async def test_orchestrator_fallback_on_empty_list(caplog):
    caplog.set_level(logging.WARNING)

    client, _, _ = build_mock_supabase_client(data=[])

    initial_target = TargetCompany(name="fallback-co", source="greenhouse")
    initial_filter = JobFilter(
        title_keywords=["LocalPython"],
        title_exclude=["LocalJunior"],
        location_keywords=["LocalRemote"],
        max_days_old=30,
        exclude_inactive=True,
    )

    dispatcher = NotificationDispatcher()
    storage = MagicMock()
    storage.filter_new_jobs = AsyncMock(return_value=[])

    orchestrator = CrawlerOrchestrator(
        targets=[initial_target],
        job_filter=initial_filter,
        storage=storage,
        dispatcher=dispatcher,
        user_id="user-empty",
        supabase_client=client,
    )

    with patch.object(orchestrator, "_crawl_target", AsyncMock(return_value=[])):
        await orchestrator.run()

    # Verify WARNING log emitted
    assert "WARNING: Using local config.yaml fallback for search configurations" in [
        f"WARNING: {r.message}" for r in caplog.records if r.levelno == logging.WARNING
    ]

    # Verify that initial configuration remained intact
    assert orchestrator.job_filter.title_keywords == ["LocalPython"]
    assert orchestrator.job_filter.title_exclude == ["LocalJunior"]
    assert orchestrator.job_filter.location_keywords == ["LocalRemote"]
    assert len(orchestrator.targets) == 1
    assert orchestrator.targets[0].name == "fallback-co"


# ---------------------------------------------------------------------------
# 4. Fallback por Falha/Exceção de Rede
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_search_configs_network_exception_returns_none():
    client, _, _ = build_mock_supabase_client(exception=httpx.ConnectError("Connection refused by host"))
    result = await load_search_configs(client, user_id="user-net-err")
    assert result is None


@pytest.mark.asyncio
async def test_orchestrator_fallback_on_network_exception(caplog):
    caplog.set_level(logging.WARNING)

    client, _, _ = build_mock_supabase_client(exception=httpx.ConnectTimeout("Request timed out"))

    initial_target = TargetCompany(name="net-fallback", source="lever")
    initial_filter = JobFilter(title_keywords=["DefaultKeyword"])

    dispatcher = NotificationDispatcher()
    storage = MagicMock()
    storage.filter_new_jobs = AsyncMock(return_value=[])

    orchestrator = CrawlerOrchestrator(
        targets=[initial_target],
        job_filter=initial_filter,
        storage=storage,
        dispatcher=dispatcher,
        user_id="user-timeout",
        supabase_client=client,
    )

    with patch.object(orchestrator, "_crawl_target", AsyncMock(return_value=[])):
        # Run must complete without raising exception
        await orchestrator.run()

    # Verify WARNING log
    warning_logs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Using local config.yaml fallback for search configurations" in msg for msg in warning_logs)

    # Initial configs retained
    assert orchestrator.job_filter.title_keywords == ["DefaultKeyword"]
    assert orchestrator.targets[0].name == "net-fallback"


# ---------------------------------------------------------------------------
# 5. Fallback quando SEARCH_CONFIG_USER_ID não configurado
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_fallback_when_user_id_not_configured(caplog, monkeypatch):
    caplog.set_level(logging.WARNING)
    monkeypatch.delenv("SEARCH_CONFIG_USER_ID", raising=False)

    initial_target = TargetCompany(name="no-user-co", source="greenhouse")
    initial_filter = JobFilter(title_keywords=["Standard"])

    dispatcher = NotificationDispatcher()
    storage = MagicMock()
    storage.filter_new_jobs = AsyncMock(return_value=[])

    orchestrator = CrawlerOrchestrator(
        targets=[initial_target],
        job_filter=initial_filter,
        storage=storage,
        dispatcher=dispatcher,
        user_id=None,
    )

    with patch.object(orchestrator, "_crawl_target", AsyncMock(return_value=[])):
        await orchestrator.run()

    warning_logs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Using local config.yaml fallback for search configurations" in msg for msg in warning_logs)
    assert orchestrator.job_filter.title_keywords == ["Standard"]


# ---------------------------------------------------------------------------
# 6. Sucesso no Supabase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_dynamic_config_success(caplog):
    caplog.set_level(logging.INFO)

    user_uuid = "00000000-0000-0000-0000-000000000001"
    remote_records = [
        {"category": "keyword", "value": "DynamicDev", "metadata": {}},
        {"category": "excluded_keyword", "value": "Trainee", "metadata": {}},
        {"category": "location", "value": "DynamicLocation", "metadata": {}},
        {
            "category": "company",
            "value": "DynamicCompany",
            "metadata": {"source": "greenhouse"},
        },
        {
            "category": "ats_filter",
            "value": "filters",
            "metadata": {"max_days_old": 10, "exclude_inactive": False},
        },
    ]

    client, _, _ = build_mock_supabase_client(data=remote_records)

    local_target = TargetCompany(name="local-co", source="greenhouse")
    local_filter = JobFilter(
        title_keywords=["LocalDev"],
        title_exclude=["LocalJunior"],
        location_keywords=["LocalLoc"],
        max_days_old=30,
        exclude_inactive=True,
    )

    dispatcher = NotificationDispatcher()
    storage = MagicMock()
    storage.filter_new_jobs = AsyncMock(return_value=[])

    orchestrator = CrawlerOrchestrator(
        targets=[local_target],
        job_filter=local_filter,
        storage=storage,
        dispatcher=dispatcher,
        user_id=user_uuid,
        supabase_client=client,
    )

    with patch.object(orchestrator, "_crawl_target", AsyncMock(return_value=[])):
        await orchestrator.run()

    # Validate INFO log emitted
    info_logs = [r.message for r in caplog.records if r.levelno == logging.INFO]
    expected_log = f"Loaded dynamic search configurations from Supabase for user {user_uuid}"
    assert any(expected_log in msg for msg in info_logs)

    # Validate overlay in memory
    assert orchestrator.job_filter.title_keywords == ["DynamicDev"]
    assert orchestrator.job_filter.title_exclude == ["Trainee"]
    assert orchestrator.job_filter.location_keywords == ["DynamicLocation"]
    assert orchestrator.job_filter.max_days_old == 10
    assert orchestrator.job_filter.exclude_inactive is False

    # Validate collector/target overlay in memory
    assert len(orchestrator.targets) == 1
    assert orchestrator.targets[0].name == "DynamicCompany"
    assert orchestrator.targets[0].source == "greenhouse"


# ---------------------------------------------------------------------------
# 7. SupabaseStorage helper method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supabase_storage_load_search_configs_delegates():
    storage = SupabaseStorage(url="https://mock.supabase.co", key="mock-key")
    client, _, _ = build_mock_supabase_client(data=[{"category": "keyword", "value": "Python", "metadata": {}}])

    with patch.object(storage, "get_client", AsyncMock(return_value=client)):
        res = await storage.load_search_configs(user_id="user-sub")
        assert res is not None
        assert res.keywords == ["Python"]


@pytest.mark.asyncio
async def test_orchestrator_dynamic_config_generates_targets_for_solides_and_gupy(caplog):
    """Validates that active ats_filter records for solides and gupy generate keyword discovery targets."""
    caplog.set_level(logging.INFO)
    user_uuid = "solides-gupy-user"

    remote_records = [
        {"category": "keyword", "value": "Python", "metadata": {}},
        {"category": "keyword", "value": "Backend", "metadata": {}},
        {"category": "ats_filter", "value": "solides", "metadata": {}},
        {"category": "ats_filter", "value": "gupy", "metadata": {}},
    ]

    client, _, _ = build_mock_supabase_client(data=remote_records)

    orchestrator = CrawlerOrchestrator(
        targets=[],
        job_filter=JobFilter(),
        storage=MagicMock(),
        dispatcher=NotificationDispatcher(),
        user_id=user_uuid,
        supabase_client=client,
    )

    with patch.object(orchestrator, "_crawl_target", AsyncMock(return_value=[])):
        await orchestrator.run()

    # Verify generated targets for each keyword across both platforms
    assert len(orchestrator.targets) == 4
    target_pairs = [(t.query, t.source) for t in orchestrator.targets]
    assert ("Python", "gupy_global") in target_pairs
    assert ("Python", "solides") in target_pairs
    assert ("Backend", "gupy_global") in target_pairs
    assert ("Backend", "solides") in target_pairs

    # Verify active ATS platforms log
    info_logs = [r.message for r in caplog.records if r.levelno == logging.INFO]
    expected_log = "Active ATS platforms for this run: ['gupy', 'solides']"
    assert any(expected_log in msg for msg in info_logs)


@pytest.mark.asyncio
async def test_orchestrator_dynamic_config_generates_targets_for_solides_only(caplog):
    """Validates that having only solides in ats_filter generates targets exclusively for Solides."""
    caplog.set_level(logging.INFO)
    user_uuid = "solides-only-user"

    remote_records = [
        {"category": "keyword", "value": "Rust", "metadata": {}},
        {"category": "ats_filter", "value": "solides", "metadata": {}},
    ]

    client, _, _ = build_mock_supabase_client(data=remote_records)

    orchestrator = CrawlerOrchestrator(
        targets=[],
        job_filter=JobFilter(),
        storage=MagicMock(),
        dispatcher=NotificationDispatcher(),
        user_id=user_uuid,
        supabase_client=client,
    )

    with patch.object(orchestrator, "_crawl_target", AsyncMock(return_value=[])):
        await orchestrator.run()

    assert len(orchestrator.targets) == 1
    assert orchestrator.targets[0].query == "Rust"
    assert orchestrator.targets[0].source == "solides"

    info_logs = [r.message for r in caplog.records if r.levelno == logging.INFO]
    expected_log = "Active ATS platforms for this run: ['solides']"
    assert any(expected_log in msg for msg in info_logs)
