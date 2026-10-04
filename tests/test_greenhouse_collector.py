import pytest
import respx
import httpx
from src.collectors.greenhouse import GreenhouseCollector
from src.models import TargetCompany, JobOpening


@pytest.mark.asyncio
async def test_greenhouse_collector_parse_jobs(greenhouse_jobs_raw):
    target = TargetCompany(name="acme", source="greenhouse")
    collector = GreenhouseCollector()

    jobs = collector.parse_jobs(target, greenhouse_jobs_raw)

    assert len(jobs) == 2
    assert all(isinstance(j, JobOpening) for j in jobs)

    first_job = jobs[0]
    assert first_job.company == "acme"
    assert first_job.source == "greenhouse"
    assert first_job.job_id == "greenhouse:acme:4123456"
    assert first_job.source_job_id == "4123456"
    assert first_job.title == "Senior Backend Engineer"
    assert first_job.location == "Remote, Brazil"
    assert first_job.url == "https://boards.greenhouse.io/acme/jobs/4123456"
    assert first_job.published_at is not None

    second_job = jobs[1]
    assert second_job.title == "Frontend Developer"
    assert second_job.location == "New York, NY"


@pytest.mark.asyncio
async def test_greenhouse_collector_edge_cases(greenhouse_edge_cases_raw):
    target = TargetCompany(name="acme", source="greenhouse")
    collector = GreenhouseCollector()

    jobs = collector.parse_jobs(target, greenhouse_edge_cases_raw)

    assert len(jobs) == 4
    # Job 1: null location -> 'N/A'
    assert jobs[0].location == "N/A"
    # Job 2: empty location dict -> 'N/A'
    assert jobs[1].location == "N/A"
    # Job 3: missing location key -> 'N/A'
    assert jobs[2].location == "N/A"
    # Job 4: null updated_at -> published_at is None
    assert jobs[3].published_at is None


@pytest.mark.asyncio
async def test_greenhouse_collector_fetch_success(respx_mock, greenhouse_jobs_raw):
    target = TargetCompany(name="acme", source="greenhouse")
    collector = GreenhouseCollector()

    route = respx_mock.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").respond(
        status_code=200, json=greenhouse_jobs_raw
    )

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert route.called
    assert len(jobs) == 2
    assert jobs[0].title == "Senior Backend Engineer"


@pytest.mark.asyncio
async def test_greenhouse_collector_handles_404_gracefully(respx_mock):
    target = TargetCompany(name="nonexistent", source="greenhouse")
    collector = GreenhouseCollector()

    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/nonexistent/jobs").respond(
        status_code=404
    )

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    # Should not raise exception; returns empty list for isolated failure
    assert jobs == []


@pytest.mark.asyncio
async def test_greenhouse_collector_handles_500_server_error(respx_mock):
    target = TargetCompany(name="acme", source="greenhouse")
    collector = GreenhouseCollector(max_retries=1)

    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").respond(
        status_code=500
    )

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert jobs == []


@pytest.mark.asyncio
async def test_greenhouse_collector_retries_on_429(respx_mock, greenhouse_jobs_raw):
    target = TargetCompany(name="acme", source="greenhouse")
    collector = GreenhouseCollector(max_retries=2, backoff_factor=0.01)

    route = respx_mock.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json=greenhouse_jobs_raw),
    ]

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert len(jobs) == 2
    assert route.call_count == 2
