import pytest
import httpx
from src.collectors.gupy import GupyCollector
from src.models import TargetCompany, JobOpening


@pytest.mark.asyncio
async def test_gupy_collector_parse_jobs_data_envelope(gupy_jobs_raw):
    target = TargetCompany(name="ambev", source="Gupy")
    collector = GupyCollector()

    jobs = collector.parse_jobs(target, gupy_jobs_raw)

    assert len(jobs) == 4
    assert all(isinstance(j, JobOpening) for j in jobs)

    # Job 1: Remote work -> location "Remoto"
    j1 = jobs[0]
    assert j1.job_id == "gupy_8123456"
    assert j1.source == "Gupy"
    assert j1.company == "ambev"
    assert j1.title == "Desenvolvedor(a) Backend Python Sênior"
    assert j1.location == "Remoto"
    assert j1.url == "https://ambev.gupy.io/job/eyJqb2JJZCI6ODEyMzQ1Nn0="
    assert j1.source_job_id == "8123456"

    # Job 2: Onsite work -> location "Campinas - SP"
    j2 = jobs[1]
    assert j2.job_id == "gupy_8123457"
    assert j2.location == "Campinas - SP"
    assert j2.url == "https://ambev.gupy.io/job/eyJqb2JJZCI6ODEyMzQ1N30="

    # Job 3: Fallback to jobUrl when careerPageUrl is missing
    j3 = jobs[2]
    assert j3.location == "Rio de Janeiro - RJ"
    assert j3.url == "https://ambev.gupy.io/jobs/8123458"

    # Job 4: Fallback to canonical URL pattern and N/A location when city/state missing
    j4 = jobs[3]
    assert j4.url == "https://ambev.gupy.io/jobs/8123459"
    assert j4.location == "N/A"


@pytest.mark.asyncio
async def test_gupy_collector_edge_cases_empty_or_malformed():
    target = TargetCompany(name="ambev", source="Gupy")
    collector = GupyCollector()

    # Empty payload or missing 'data'
    assert collector.parse_jobs(target, {}) == []
    assert collector.parse_jobs(target, {"data": []}) == []
    assert collector.parse_jobs(target, {"data": None}) == []
    assert collector.parse_jobs(target, "malformed string") == []


@pytest.mark.asyncio
async def test_gupy_collector_headers(respx_mock, gupy_jobs_raw):
    target = TargetCompany(name="ambev", source="Gupy")
    collector = GupyCollector()

    primary_url = "https://portal.api.gupy.io/api/v1/jobs?careerPageName=ambev&limit=100"
    route = respx_mock.get(primary_url).respond(
        status_code=200, json=gupy_jobs_raw
    )

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert route.called
    sent_request = route.calls.last.request
    # Headers required: User-Agent and Accept: application/json
    assert sent_request.headers.get("user-agent") == "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    assert sent_request.headers.get("accept") == "application/json"
    assert len(jobs) == 4


@pytest.mark.asyncio
async def test_gupy_collector_primary_success(respx_mock, gupy_jobs_raw):
    target = TargetCompany(name="ambev", source="Gupy")
    collector = GupyCollector()

    primary_url = "https://portal.api.gupy.io/api/v1/jobs?careerPageName=ambev&limit=100"
    route = respx_mock.get(primary_url).respond(
        status_code=200, json=gupy_jobs_raw
    )

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert route.called
    assert len(jobs) == 4


@pytest.mark.asyncio
async def test_gupy_collector_fallback_to_subdomain_on_404(respx_mock, gupy_jobs_raw):
    target = TargetCompany(name="ambev", source="Gupy")
    collector = GupyCollector()

    primary_url = "https://portal.api.gupy.io/api/v1/jobs?careerPageName=ambev&limit=100"
    fallback_url = "https://ambev.gupy.io/api/v1/jobs?limit=100"

    primary_route = respx_mock.get(primary_url).respond(status_code=404)
    fallback_route = respx_mock.get(fallback_url).respond(status_code=200, json=gupy_jobs_raw)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert primary_route.called
    assert fallback_route.called
    assert len(jobs) == 4
    assert jobs[0].title == "Desenvolvedor(a) Backend Python Sênior"


@pytest.mark.asyncio
async def test_gupy_collector_fallback_to_subdomain_on_empty(respx_mock, gupy_jobs_raw):
    target = TargetCompany(name="ambev", source="Gupy")
    collector = GupyCollector()

    primary_url = "https://portal.api.gupy.io/api/v1/jobs?careerPageName=ambev&limit=100"
    fallback_url = "https://ambev.gupy.io/api/v1/jobs?limit=100"

    primary_route = respx_mock.get(primary_url).respond(status_code=200, json={"data": []})
    fallback_route = respx_mock.get(fallback_url).respond(status_code=200, json=gupy_jobs_raw)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert primary_route.called
    assert fallback_route.called
    assert len(jobs) == 4


@pytest.mark.asyncio
async def test_gupy_collector_handles_both_404_gracefully(respx_mock):
    target = TargetCompany(name="nonexistent", source="Gupy")
    collector = GupyCollector()

    primary_url = "https://portal.api.gupy.io/api/v1/jobs?careerPageName=nonexistent&limit=100"
    fallback_url = "https://nonexistent.gupy.io/api/v1/jobs?limit=100"

    respx_mock.get(primary_url).respond(status_code=404)
    respx_mock.get(fallback_url).respond(status_code=404)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert jobs == []


@pytest.mark.asyncio
async def test_gupy_collector_handles_both_500_gracefully(respx_mock):
    target = TargetCompany(name="ambev", source="Gupy")
    collector = GupyCollector()

    primary_url = "https://portal.api.gupy.io/api/v1/jobs?careerPageName=ambev&limit=100"
    fallback_url = "https://ambev.gupy.io/api/v1/jobs?limit=100"

    respx_mock.get(primary_url).respond(status_code=500)
    respx_mock.get(fallback_url).respond(status_code=500)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert jobs == []


@pytest.mark.asyncio
async def test_gupy_collector_sanitizes_names_with_spaces_and_special_chars(respx_mock, gupy_jobs_raw):
    # Case 1: Company name with spaces -> primary encoded, fallback sanitized without spaces
    target_spaces = TargetCompany(name="Stefanini Group", source="Gupy")
    collector = GupyCollector()

    assert " " not in collector.get_slug(target_spaces)
    assert collector.get_slug(target_spaces) == "stefanini-group"
    assert collector.build_url(target_spaces) == "https://portal.api.gupy.io/api/v1/jobs?careerPageName=Stefanini+Group&limit=100"
    assert collector.build_fallback_url(target_spaces) == "https://stefanini-group.gupy.io/api/v1/jobs?limit=100"

    # Mock primary 404 and fallback 200
    respx_mock.get("https://portal.api.gupy.io/api/v1/jobs?careerPageName=Stefanini+Group&limit=100").respond(status_code=404)
    respx_mock.get("https://stefanini-group.gupy.io/api/v1/jobs?limit=100").respond(status_code=200, json=gupy_jobs_raw)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target_spaces, client=client)

    assert len(jobs) == 4
    # Check that generated job URL uses sanitized slug
    assert " " not in jobs[3].url


@pytest.mark.asyncio
async def test_gupy_collector_uses_explicit_slug_prioritized(respx_mock, gupy_jobs_raw):
    # Case 2: Company has explicit slug provided
    target_explicit = TargetCompany(name="Stefanini Group", slug="stefaninigroup", source="Gupy")
    collector = GupyCollector()

    assert collector.get_slug(target_explicit) == "stefaninigroup"
    assert collector.build_fallback_url(target_explicit) == "https://stefaninigroup.gupy.io/api/v1/jobs?limit=100"

    respx_mock.get("https://portal.api.gupy.io/api/v1/jobs?careerPageName=Stefanini+Group&limit=100").respond(status_code=404)
    respx_mock.get("https://stefaninigroup.gupy.io/api/v1/jobs?limit=100").respond(status_code=200, json=gupy_jobs_raw)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target_explicit, client=client)

    assert len(jobs) == 4
    assert jobs[0].url.startswith("https://")

