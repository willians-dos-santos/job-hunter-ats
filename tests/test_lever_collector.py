import pytest
import respx
import httpx
from src.collectors.lever import LeverCollector
from src.models import TargetCompany, JobOpening


@pytest.mark.asyncio
async def test_lever_collector_parse_jobs(lever_jobs_raw):
    target = TargetCompany(name="techcorp", source="lever")
    collector = LeverCollector()

    jobs = collector.parse_jobs(target, lever_jobs_raw)

    assert len(jobs) == 2
    assert all(isinstance(j, JobOpening) for j in jobs)

    first_job = jobs[0]
    assert first_job.company == "techcorp"
    assert first_job.source == "lever"
    assert first_job.job_id == "lever:techcorp:a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    assert first_job.source_job_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    assert first_job.title == "Staff Backend Engineer - Python"
    assert first_job.location == "Remote, Global"
    assert first_job.url == "https://jobs.lever.co/techcorp/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    assert first_job.published_at is not None

    second_job = jobs[1]
    assert second_job.title == "Data Analyst"
    assert second_job.location == "London, UK"


@pytest.mark.asyncio
async def test_lever_collector_edge_cases(lever_edge_cases_raw):
    target = TargetCompany(name="techcorp", source="lever")
    collector = LeverCollector()

    jobs = collector.parse_jobs(target, lever_edge_cases_raw)

    assert len(jobs) == 3
    # Job 1: null categories -> 'N/A'
    assert jobs[0].location == "N/A"
    # Job 2: empty categories -> 'N/A'
    assert jobs[1].location == "N/A"
    # Job 3: categories with null location -> 'N/A'
    assert jobs[2].location == "N/A"


@pytest.mark.asyncio
async def test_lever_collector_fetch_success(respx_mock, lever_jobs_raw):
    target = TargetCompany(name="techcorp", source="lever")
    collector = LeverCollector()

    route = respx_mock.get("https://api.lever.co/v0/postings/techcorp?mode=json").respond(
        status_code=200, json=lever_jobs_raw
    )

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert route.called
    assert len(jobs) == 2
    assert jobs[0].title == "Staff Backend Engineer - Python"


@pytest.mark.asyncio
async def test_lever_collector_handles_404_gracefully(respx_mock):
    target = TargetCompany(name="nonexistent", source="lever")
    collector = LeverCollector()

    respx_mock.get("https://api.lever.co/v0/postings/nonexistent?mode=json").respond(
        status_code=404
    )

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert jobs == []


@pytest.mark.asyncio
async def test_lever_collector_retries_on_429(respx_mock, lever_jobs_raw):
    target = TargetCompany(name="techcorp", source="lever")
    collector = LeverCollector(max_retries=2, backoff_factor=0.01)

    route = respx_mock.get("https://api.lever.co/v0/postings/techcorp?mode=json")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json=lever_jobs_raw),
    ]

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert len(jobs) == 2
    assert route.call_count == 2
