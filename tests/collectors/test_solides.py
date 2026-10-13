from datetime import datetime, timezone

import httpx
import pytest

from src.collectors.solides import SolidesCollector
from src.models import JobOpening, TargetCompany


@pytest.mark.asyncio
async def test_solides_parse_jobs_data_envelope(solides_jobs_raw):
    """Tests parsing jobs envelope from realistic Solides response payload."""
    target = TargetCompany(name="Vagas Python", source="solides", query="Python")
    collector = SolidesCollector()

    jobs = collector.parse_jobs(target, solides_jobs_raw)

    assert len(jobs) == 4
    assert all(isinstance(j, JobOpening) for j in jobs)

    # Job 1: id=936455 (int), presencial, São Paulo - SP
    j1 = jobs[0]
    assert j1.job_id == "solides_936455"
    assert j1.source == "solides"
    assert j1.source_job_id == "936455"
    assert j1.company == "Tech Corp"
    assert j1.title == "Desenvolvedor Backend Python"
    assert j1.location == "São Paulo - SP"
    assert j1.url == "https://vagas.solides.com.br/vaga/936455"
    assert j1.published_at == datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert j1.dedup_key is not None

    # Job 2: id="936108" (str), remoto, city/state=None -> location="Remoto"
    j2 = jobs[1]
    assert j2.job_id == "solides_936108"
    assert j2.source == "solides"
    assert j2.source_job_id == "936108"
    assert j2.company == "Inova Brasil"
    assert j2.title == "Engenheiro de Software Python Sênior"
    assert j2.location == "Remoto"
    assert j2.url == "https://vagas.solides.com.br/vaga/936108"
    assert j2.published_at == datetime(2026, 10, 11, 14, 30, tzinfo=timezone.utc)

    # Job 3: id=935687 (int), hibrido, Natal - RN
    j3 = jobs[2]
    assert j3.job_id == "solides_935687"
    assert j3.source_job_id == "935687"
    assert j3.company == "Mendes Advogados"
    assert j3.title == "Desenvolvedor Fullstack Python/React"
    assert j3.location == "Natal - RN"
    assert j3.url == "https://vagas.solides.com.br/vaga/935687"

    # Job 4: id="sol-abc-42" (alphanumeric str), company=None -> "Solides", homeOffice=true, city/state=None -> "Remoto"
    j4 = jobs[3]
    assert j4.job_id == "solides_sol-abc-42"
    assert j4.source_job_id == "sol-abc-42"
    assert j4.company == "Solides"
    assert j4.title == "Arquiteto de Soluções Cloud"
    assert j4.location == "Remoto"
    assert isinstance(j4.published_at, datetime)
    assert j4.published_at.tzinfo == timezone.utc


def test_solides_mixed_ids_and_missing_optional_data():
    """Validates normalization with int, numeric str, alphanumeric str and missing/null fields."""
    collector = SolidesCollector()
    target = TargetCompany(name="Solides Tech", source="solides")

    payload = {
        "data": [
            {
                "id": 123456,
                "title": "Analista Python",
                "companyName": "Empresa 1",
            },
            {
                "id": "789101",
                "title": "Backend Go",
                "companyName": "",
            },
            {
                "id": "sol-uuid-999",
                "title": "Tech Lead",
                "companyName": None,
            },
            {
                "id": None,  # Should be skipped
                "title": "Invalid Job",
            },
            {
                "id": "   ",  # Blank id should be skipped
                "title": "Blank Job",
            },
            "invalid_non_dict_item",  # Should be skipped
        ]
    }

    jobs = collector.parse_jobs(target, payload)
    assert len(jobs) == 3

    assert jobs[0].job_id == "solides_123456"
    assert jobs[0].source_job_id == "123456"
    assert jobs[0].company == "Empresa 1"
    assert jobs[0].url == "https://vagas.solides.com.br/vaga/123456"

    assert jobs[1].job_id == "solides_789101"
    assert jobs[1].source_job_id == "789101"
    assert jobs[1].company == "Solides"
    assert jobs[1].url == "https://vagas.solides.com.br/vaga/789101"

    assert jobs[2].job_id == "solides_sol-uuid-999"
    assert jobs[2].source_job_id == "sol-uuid-999"
    assert jobs[2].company == "Solides"
    assert jobs[2].url == "https://vagas.solides.com.br/vaga/sol-uuid-999"


def test_solides_modality_mapping():
    """Validates modality mapping: remote, hybrid, on_site."""
    collector = SolidesCollector()

    # jobType == "remoto" -> "remote"
    assert collector.map_modality("remoto", False) == "remote"
    assert collector.map_modality("Remoto", False) == "remote"

    # homeOffice is True -> "remote"
    assert collector.map_modality("presencial", True) == "remote"
    assert collector.map_modality("", True) == "remote"

    # hybrid detection -> "hybrid"
    assert collector.map_modality("hibrido", False) == "hybrid"
    assert collector.map_modality("Híbrido", False) == "hybrid"
    assert collector.map_modality("modelo hibrido", False) == "hybrid"

    # otherwise -> "on_site"
    assert collector.map_modality("presencial", False) == "on_site"
    assert collector.map_modality("integral", False) == "on_site"
    assert collector.map_modality(None, False) == "on_site"


def test_solides_location_fallback():
    """Validates location formatting f'{city.name} - {state.code}' and fallback to 'Remoto'."""
    collector = SolidesCollector()
    target = TargetCompany(name="Solides", source="solides")

    payload = {
        "data": [
            # 1. Full city and state code
            {
                "id": 1,
                "title": "Vaga 1",
                "city": {"name": "Campinas"},
                "state": {"code": "SP"},
                "jobType": "presencial",
            },
            # 2. Null city and state with jobType 'remoto'
            {
                "id": 2,
                "title": "Vaga 2",
                "city": None,
                "state": None,
                "jobType": "remoto",
            },
            # 3. Null city and state with on-site -> fallback to 'Remoto'
            {
                "id": 3,
                "title": "Vaga 3",
                "city": None,
                "state": None,
                "jobType": "presencial",
            },
            # 4. City only, state is None -> handles defensively
            {
                "id": 4,
                "title": "Vaga 4",
                "city": {"name": "Fortaleza"},
                "state": None,
                "jobType": "presencial",
            },
            # 5. State with name instead of code
            {
                "id": 5,
                "title": "Vaga 5",
                "city": {"name": "Salvador"},
                "state": {"name": "Bahia", "code": None},
                "jobType": "presencial",
            },
        ]
    }

    jobs = collector.parse_jobs(target, payload)
    assert len(jobs) == 5

    assert jobs[0].location == "Campinas - SP"
    assert jobs[1].location == "Remoto"
    assert jobs[2].location == "Remoto"
    assert jobs[3].location == "Fortaleza"
    assert jobs[4].location == "Salvador - Bahia"


def test_solides_build_params_dynamic_title_and_locations():
    """Validates building query parameters with dynamic title and empty locations."""
    collector = SolidesCollector()

    # 1. Target with explicit query
    t1 = TargetCompany(name="Solides Vagas", source="solides", query="Python Developer")
    p1 = collector.build_params(t1)
    assert p1["page"] == 1
    assert p1["take"] == 20
    assert p1["title"] == "Python Developer"
    assert p1["locations"] == ""

    # 2. Target with name (not Solides) without query
    t2 = TargetCompany(name="Backend", source="solides")
    p2 = collector.build_params(t2)
    assert p2["title"] == "Backend"
    assert p2["take"] == 20
    assert p2["locations"] == ""

    # 3. Target named "solides" without query -> title is not set or empty
    t3 = TargetCompany(name="Solides", source="solides")
    p3 = collector.build_params(t3)
    assert "title" not in p3 or p3["title"] == ""
    assert p3["locations"] == ""


@pytest.mark.asyncio
async def test_solides_pagination_complete_loop(respx_mock):
    """Validates automatic pagination iterating through all pages up to totalPages."""
    collector = SolidesCollector()
    target = TargetCompany(name="Vagas Python", source="solides", query="Python")

    page1_response = {
        "totalPages": 3,
        "currentPage": 1,
        "count": 6,
        "data": [
            {"id": 101, "title": "Job 1", "companyName": "Alpha"},
            {"id": 102, "title": "Job 2", "companyName": "Alpha"},
        ],
    }
    page2_response = {
        "totalPages": 3,
        "currentPage": 2,
        "count": 6,
        "data": [
            {"id": 103, "title": "Job 3", "companyName": "Beta"},
            {"id": 104, "title": "Job 4", "companyName": "Beta"},
        ],
    }
    page3_response = {
        "totalPages": 3,
        "currentPage": 3,
        "count": 6,
        "data": [
            {"id": 105, "title": "Job 5", "companyName": "Gamma"},
            {"id": 106, "title": "Job 6", "companyName": "Gamma"},
        ],
    }

    r1 = respx_mock.get(
        "https://vagas.solides.com.br/api/vacancies",
        params={"page": "1", "take": "20", "title": "Python", "locations": ""},
    ).respond(status_code=200, json=page1_response)

    r2 = respx_mock.get(
        "https://vagas.solides.com.br/api/vacancies",
        params={"page": "2", "take": "20", "title": "Python", "locations": ""},
    ).respond(status_code=200, json=page2_response)

    r3 = respx_mock.get(
        "https://vagas.solides.com.br/api/vacancies",
        params={"page": "3", "take": "20", "title": "Python", "locations": ""},
    ).respond(status_code=200, json=page3_response)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert r1.called
    assert r2.called
    assert r3.called
    assert len(jobs) == 6
    assert [j.job_id for j in jobs] == [
        "solides_101",
        "solides_102",
        "solides_103",
        "solides_104",
        "solides_105",
        "solides_106",
    ]


@pytest.mark.asyncio
async def test_solides_single_page_pagination(respx_mock):
    """Validates termination after a single page when totalPages == 1."""
    collector = SolidesCollector()
    target = TargetCompany(name="Vagas Go", source="solides", query="Go")

    page_response = {
        "totalPages": 1,
        "currentPage": 1,
        "count": 1,
        "data": [{"id": 201, "title": "Go Dev", "companyName": "Gopher Corp"}],
    }

    r = respx_mock.get("https://vagas.solides.com.br/api/vacancies").respond(status_code=200, json=page_response)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert r.call_count == 1
    assert len(jobs) == 1
    assert jobs[0].job_id == "solides_201"


@pytest.mark.asyncio
async def test_solides_empty_response_handling(respx_mock):
    """Validates graceful termination when vacancies response is empty or malformed."""
    collector = SolidesCollector()
    target = TargetCompany(name="Empty", source="solides")

    # 1. totalPages = 0 and empty data
    respx_mock.get("https://vagas.solides.com.br/api/vacancies").respond(
        status_code=200, json={"totalPages": 0, "currentPage": 1, "count": 0, "data": []}
    )

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert jobs == []

    # 2. Non-dict or malformed raw data
    assert collector.parse_jobs(target, {}) == []
    assert collector.parse_jobs(target, {"data": None}) == []
    assert collector.parse_jobs(target, "not-a-dict") == []


@pytest.mark.asyncio
async def test_solides_rate_limiting_429_retry(respx_mock):
    """Validates handling HTTP 429 rate limit with backoff and retry."""
    collector = SolidesCollector(max_retries=2, backoff_factor=0.01)
    target = TargetCompany(name="RateLimited", source="solides")

    # Fail once with 429, then succeed
    route = respx_mock.get("https://vagas.solides.com.br/api/vacancies")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0.01"}),
        httpx.Response(
            200,
            json={
                "totalPages": 1,
                "currentPage": 1,
                "count": 1,
                "data": [{"id": 301, "title": "Dev Ops"}],
            },
        ),
    ]

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert len(jobs) == 1
    assert jobs[0].job_id == "solides_301"


@pytest.mark.asyncio
async def test_solides_network_error_isolation(respx_mock):
    """Validates network errors and 500 status codes do not crash crawler and return empty list."""
    collector = SolidesCollector(max_retries=1, backoff_factor=0.01)
    target = TargetCompany(name="Broken", source="solides")

    # 1. 500 internal server error
    respx_mock.get("https://vagas.solides.com.br/api/vacancies").respond(status_code=500)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert jobs == []

    # 2. 404 not found
    respx_mock.get("https://vagas.solides.com.br/api/vacancies").respond(status_code=404)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert jobs == []


@pytest.mark.asyncio
async def test_solides_headers_simulation(respx_mock):
    """Validates browser simulation headers (User-Agent, Accept)."""
    collector = SolidesCollector()
    target = TargetCompany(name="HeadersTest", source="solides", query="Dev")

    route = respx_mock.get("https://vagas.solides.com.br/api/vacancies").respond(
        status_code=200,
        json={"totalPages": 1, "currentPage": 1, "count": 1, "data": [{"id": 401, "title": "QA"}]},
    )

    async with httpx.AsyncClient() as client:
        await collector.fetch_jobs(target, client=client)

    assert route.called
    sent_req = route.calls.last.request
    assert "Mozilla/5.0" in sent_req.headers.get("user-agent", "")
    assert sent_req.headers.get("accept") == "application/json"


@pytest.mark.asyncio
async def test_solides_orchestrator_integration(respx_mock):
    """Validates full end-to-end integration of Solides collector in CrawlerOrchestrator."""
    from unittest.mock import AsyncMock, MagicMock

    from src.filters import JobFilter
    from src.notifiers import NotificationDispatcher
    from src.orchestrator import CrawlerOrchestrator

    target = TargetCompany(name="Solides Python", source="solides", query="Python")
    mock_payload = {
        "totalPages": 1,
        "currentPage": 1,
        "count": 1,
        "data": [
            {
                "id": 999888,
                "title": "Desenvolvedor Python Backend",
                "companyName": "Solides Enterprise",
                "jobType": "remoto",
                "city": None,
                "state": None,
                "createdAt": "2026-10-12T10:00:00Z",
            }
        ],
    }

    respx_mock.get("https://vagas.solides.com.br/api/vacancies").respond(status_code=200, json=mock_payload)

    job_filter = JobFilter(
        title_keywords=["Python"],
        location_keywords=["Remoto"],
    )

    storage = MagicMock()
    storage.filter_new_jobs = AsyncMock(side_effect=lambda jobs: list(jobs))
    storage.save_job = AsyncMock(return_value=True)

    notifier = MagicMock()
    notifier.notify.return_value = True
    dispatcher = NotificationDispatcher(console_notifier=notifier)

    orchestrator = CrawlerOrchestrator(
        targets=[target],
        job_filter=job_filter,
        storage=storage,
        dispatcher=dispatcher,
        concurrency_limit=2,
    )

    notified = await orchestrator.run()

    assert len(notified) == 1
    assert notified[0].job_id == "solides_999888"
    assert notified[0].source == "solides"
    assert notified[0].location == "Remoto"
    assert storage.save_job.called
    assert notifier.notify.called


def test_solides_published_at_parsing_and_safe_fallback():
    """Validates YYYY-MM-DD date parsing, ISO format parsing, and fallback to safe datetime."""
    collector = SolidesCollector()
    target = TargetCompany(name="Solides Date Test", source="solides")

    payload = {
        "data": [
            # 1. YYYY-MM-DD format
            {"id": 1, "title": "Job 1", "createdAt": "2026-10-06"},
            # 2. ISO timestamp format with Z
            {"id": 2, "title": "Job 2", "createdAt": "2026-10-06T12:30:00Z"},
            # 3. None / null createdAt
            {"id": 3, "title": "Job 3", "createdAt": None},
            # 4. Invalid date string
            {"id": 4, "title": "Job 4", "createdAt": "not-a-valid-date"},
        ]
    }

    jobs = collector.parse_jobs(target, payload)
    assert len(jobs) == 4

    # Job 1: 2026-10-06 parsed into UTC datetime
    assert jobs[0].published_at == datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)

    # Job 2: ISO parsed into UTC datetime
    assert jobs[1].published_at == datetime(2026, 10, 6, 12, 30, tzinfo=timezone.utc)

    # Job 3: Null falls back to current UTC datetime
    assert isinstance(jobs[2].published_at, datetime)
    assert jobs[2].published_at.tzinfo == timezone.utc

    # Job 4: Malformed string falls back to current UTC datetime
    assert isinstance(jobs[3].published_at, datetime)
    assert jobs[3].published_at.tzinfo == timezone.utc


def test_solides_remote_modality_normalizes_location_to_remoto():
    """Validates that vacancies with remote modality normalize location to 'Remoto' even if city/state are provided."""
    collector = SolidesCollector()
    target = TargetCompany(name="Solides Location Test", source="solides")

    payload = {
        "data": [
            # Remote via jobType with headquarters city/state
            {
                "id": 10,
                "title": "Backend Dev",
                "jobType": "remoto",
                "homeOffice": False,
                "city": {"name": "Belo Horizonte"},
                "state": {"code": "MG"},
            },
            # Remote via homeOffice flag with headquarters city/state
            {
                "id": 11,
                "title": "Python Dev",
                "jobType": "presencial",
                "homeOffice": True,
                "city": {"name": "São Paulo"},
                "state": {"code": "SP"},
            },
            # Presencial with city/state remains city/state
            {
                "id": 12,
                "title": "Onsite Dev",
                "jobType": "presencial",
                "homeOffice": False,
                "city": {"name": "Curitiba"},
                "state": {"code": "PR"},
            },
        ]
    }

    jobs = collector.parse_jobs(target, payload)
    assert len(jobs) == 3

    assert jobs[0].location == "Remoto"
    assert jobs[0].modality == "remote"

    assert jobs[1].location == "Remoto"
    assert jobs[1].modality == "remote"

    assert jobs[2].location == "Curitiba - PR"
    assert jobs[2].modality == "on_site"
