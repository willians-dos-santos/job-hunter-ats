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
    assert j4.url == "https://portal.gupy.io/job-search/jobs/8123459"
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
async def test_gupy_collector_headers_and_params(respx_mock, gupy_jobs_raw):
    target = TargetCompany(name="Stefanini Group", source="Gupy")
    collector = GupyCollector()

    expected_url = "https://portal.gupy.io/api/job-search/jobs?limit=100&offset=0&careerPageName=Stefanini+Group"
    route = respx_mock.get("https://portal.gupy.io/api/job-search/jobs").respond(
        status_code=200, json=gupy_jobs_raw
    )

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert route.called
    sent_request = route.calls.last.request
    # Headers required: Chrome user-agent and Accept: application/json
    user_agent = sent_request.headers.get("user-agent", "")
    assert "Mozilla/5.0" in user_agent
    assert "Chrome/120.0.0.0" in user_agent
    assert sent_request.headers.get("accept") == "application/json"

    # Query params check: careerPageName with spaces, limit=100, offset=0
    assert sent_request.url.params.get("careerPageName") == "Stefanini Group"
    assert sent_request.url.params.get("limit") == "100"
    assert sent_request.url.params.get("offset") == "0"
    assert len(jobs) == 4


@pytest.mark.asyncio
async def test_gupy_collector_fetch_success(respx_mock, gupy_jobs_raw):
    target = TargetCompany(name="ambev", source="Gupy")
    collector = GupyCollector()

    route = respx_mock.get("https://portal.gupy.io/api/job-search/jobs").respond(
        status_code=200, json=gupy_jobs_raw
    )

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert route.called
    assert len(jobs) == 4
    assert jobs[0].title == "Desenvolvedor(a) Backend Python Sênior"


@pytest.mark.asyncio
async def test_gupy_collector_handles_404_gracefully(respx_mock):
    target = TargetCompany(name="nonexistent", source="Gupy")
    collector = GupyCollector()

    respx_mock.get("https://portal.gupy.io/api/job-search/jobs").respond(status_code=404)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert jobs == []


@pytest.mark.asyncio
async def test_gupy_collector_handles_500_gracefully(respx_mock):
    target = TargetCompany(name="ambev", source="Gupy")
    collector = GupyCollector()

    respx_mock.get("https://portal.gupy.io/api/job-search/jobs").respond(status_code=500)

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert jobs == []
