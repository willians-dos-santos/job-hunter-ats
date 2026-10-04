import pytest
import httpx
from src.collectors.gupy import GupyCollector
from src.models import TargetCompany, JobOpening


@pytest.mark.asyncio
async def test_gupy_collector_parse_jobs_data_envelope(gupy_jobs_raw):
    target = TargetCompany(name="Stefanini Group", source="Gupy")
    collector = GupyCollector()

    jobs = collector.parse_jobs(target, gupy_jobs_raw)

    assert len(jobs) == 10
    assert all(isinstance(j, JobOpening) for j in jobs)

    # Job 1 (id 12518303): On-site -> location "São Paulo - São Paulo"
    j1 = jobs[0]
    assert j1.job_id == "gupy_12518303"
    assert j1.source == "Gupy"
    assert j1.company == "Stefanini Group"
    assert j1.title == "ANALISTA ADMINISTRATIVO PL"
    assert j1.location == "São Paulo - São Paulo"
    assert "https://stefanini.gupy.io/job/" in j1.url
    assert j1.source_job_id == "12518303"

    # Job 4 (id 12669218): workplaceType == "remote" -> location "Remoto"
    j4 = jobs[3]
    assert j4.job_id == "gupy_12669218"
    assert j4.location == "Remoto"

    # Job 7 (id 12668014): workplaceType == "remote" -> location "Remoto"
    j7 = jobs[6]
    assert j7.job_id == "gupy_12668014"
    assert j7.title == "Analista Desenvolvedor Backend Sr"
    assert j7.location == "Remoto"

    # Job 9 (id 12630267): workplaceType == "remote" -> location "Remoto"
    j9 = jobs[8]
    assert j9.job_id == "gupy_12630267"
    assert j9.location == "Remoto"


def test_gupy_collector_workplace_type_mapping():
    collector = GupyCollector()
    target = TargetCompany(name="Stefanini Group", source="Gupy")

    # 1. workplaceType == "remote" -> "Remoto"
    remote_payload = {
        "data": [
            {
                "id": 99901,
                "name": "Backend Python",
                "workplaceType": "remote",
                "city": "São Paulo",
                "state": "SP",
                "jobUrl": "https://company.gupy.io/jobs/99901",
            }
        ]
    }
    jobs = collector.parse_jobs(target, remote_payload)
    assert len(jobs) == 1
    assert jobs[0].location == "Remoto"
    assert jobs[0].job_id == "gupy_99901"
    assert jobs[0].company == "Stefanini Group"

    # 2. workplaceType == "on-site" with city & state -> "City - State"
    onsite_payload = {
        "data": [
            {
                "id": 99902,
                "name": "Frontend React",
                "workplaceType": "on-site",
                "city": "Campinas",
                "state": "SP",
            }
        ]
    }
    jobs = collector.parse_jobs(target, onsite_payload)
    assert len(jobs) == 1
    assert jobs[0].location == "Campinas - SP"

    # 3. workplaceType == "on-site" without city & state -> "Presencial"
    onsite_no_loc_payload = {
        "data": [
            {
                "id": 99903,
                "name": "Support Analyst",
                "workplaceType": "on-site",
                "city": None,
                "state": "",
            }
        ]
    }
    jobs = collector.parse_jobs(target, onsite_no_loc_payload)
    assert len(jobs) == 1
    assert jobs[0].location == "Presencial"

    # 4. company fallback to careerPageName or Stefanini Group
    fallback_company_payload = {
        "data": [
            {
                "id": 99904,
                "name": "Engineer",
                "workplaceType": "remote",
                "careerPageName": "Acme Brasil",
            }
        ]
    }
    jobs = collector.parse_jobs(TargetCompany(name="", source="Gupy"), fallback_company_payload)
    assert jobs[0].company == "Acme Brasil"

    jobs_default = collector.parse_jobs(TargetCompany(name="", source="Gupy"), {"data": [{"id": 99905, "name": "Dev"}]})
    assert jobs_default[0].company == "Stefanini Group"


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
    assert len(jobs) == 10


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
    assert len(jobs) == 10
    assert jobs[0].title == "ANALISTA ADMINISTRATIVO PL"


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


def test_gupy_collector_build_params_global_discovery():
    collector = GupyCollector()

    # 1. gupy_global with explicit query
    target_query = TargetCompany(name="Ignored", source="gupy_global", query="Backend Python")
    params_query = collector.build_params(target_query)
    assert params_query["jobName"] == "Backend Python"
    assert params_query["limit"] == 100
    assert params_query["offset"] == 0
    assert "careerPageName" not in params_query

    # 2. gupy_global without query (fallback to name)
    target_name = TargetCompany(name="Python", source="gupy_global")
    params_name = collector.build_params(target_name)
    assert params_name["jobName"] == "Python"
    assert params_name["limit"] == 100
    assert params_name["offset"] == 0
    assert "careerPageName" not in params_name

    # 3. Standard company search keeps careerPageName and has no jobName
    target_company = TargetCompany(name="Stefanini Group", source="Gupy")
    params_company = collector.build_params(target_company)
    assert params_company["careerPageName"] == "Stefanini Group"
    assert "jobName" not in params_company


def test_gupy_collector_parse_jobs_global_discovery_multiple_companies():
    collector = GupyCollector()
    target = TargetCompany(name="Python", source="gupy_global")

    payload = {
        "data": [
            {
                "id": 1001,
                "name": "Backend Python Sênior",
                "careerPageName": "PicPay",
                "workplaceType": "remote",
                "jobUrl": "https://picpay.gupy.io/jobs/1001",
            },
            {
                "id": 1002,
                "name": "Engenheiro de Dados Pleno",
                "careerPageName": "Ambev Tech",
                "workplaceType": "on-site",
                "city": "Campinas",
                "state": "SP",
                "jobUrl": "https://ambevtech.gupy.io/jobs/1002",
            },
            {
                "id": 1003,
                "name": "Python Specialist",
                "careerPageName": None,  # Test fallback to "Gupy"
                "workplaceType": "remote",
                "jobUrl": "https://portal.gupy.io/jobs/1003",
            },
        ]
    }

    jobs = collector.parse_jobs(target, payload)
    assert len(jobs) == 3

    # Job 1: PicPay - Remoto
    assert jobs[0].company == "PicPay"
    assert jobs[0].title == "Backend Python Sênior"
    assert jobs[0].location == "Remoto"
    assert jobs[0].url == "https://picpay.gupy.io/jobs/1001"

    # Job 2: Ambev Tech - Campinas - SP
    assert jobs[1].company == "Ambev Tech"
    assert jobs[1].title == "Engenheiro de Dados Pleno"
    assert jobs[1].location == "Campinas - SP"
    assert jobs[1].url == "https://ambevtech.gupy.io/jobs/1002"

    # Job 3: Fallback to "Gupy" when careerPageName is None
    assert jobs[2].company == "Gupy"
    assert jobs[2].title == "Python Specialist"
    assert jobs[2].location == "Remoto"


@pytest.mark.asyncio
async def test_gupy_collector_fetch_global_discovery(respx_mock):
    collector = GupyCollector()
    target = TargetCompany(name="Python Global", source="gupy_global", query="Python")

    mock_payload = {
        "data": [
            {
                "id": 2001,
                "name": "Desenvolvedor Python",
                "careerPageName": "Tech Hub",
                "workplaceType": "remote",
                "jobUrl": "https://techhub.gupy.io/jobs/2001",
            }
        ]
    }

    route = respx_mock.get("https://portal.gupy.io/api/job-search/jobs").respond(
        status_code=200, json=mock_payload
    )

    async with httpx.AsyncClient() as client:
        jobs = await collector.fetch_jobs(target, client=client)

    assert route.called
    sent_request = route.calls.last.request

    # Check query params: jobName should be "Python", limit="100", offset="0"
    assert sent_request.url.params.get("jobName") == "Python"
    assert sent_request.url.params.get("limit") == "100"
    assert sent_request.url.params.get("offset") == "0"
    assert "careerPageName" not in sent_request.url.params

    # Check headers
    user_agent = sent_request.headers.get("user-agent", "")
    assert "Mozilla/5.0" in user_agent
    assert sent_request.headers.get("accept") == "application/json"

    # Check parsed jobs
    assert len(jobs) == 1
    assert jobs[0].company == "Tech Hub"
    assert jobs[0].title == "Desenvolvedor Python"
    assert jobs[0].location == "Remoto"

