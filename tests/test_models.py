from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

# We import from src.models
from src.models import JobOpening, TargetCompany


def test_job_opening_creation_valid():
    job = JobOpening(
        job_id="gh:acme:12345",
        source="greenhouse",
        company="acme",
        title="Senior Python Engineer",
        location="Remote, Brazil",
        url="https://boards.greenhouse.io/acme/jobs/12345",
        published_at=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        source_job_id="12345",
    )
    assert job.job_id == "gh:acme:12345"
    assert job.source == "greenhouse"
    assert job.company == "acme"
    assert job.title == "Senior Python Engineer"
    assert job.location == "Remote, Brazil"
    assert job.url == "https://boards.greenhouse.io/acme/jobs/12345"
    assert job.source_job_id == "12345"


def test_job_opening_default_location_and_source_id():
    job = JobOpening(
        job_id="gh:acme:12345",
        source="greenhouse",
        company="acme",
        title="Software Engineer",
        url="https://boards.greenhouse.io/acme/jobs/12345",
    )
    assert job.location == "N/A"
    assert job.source_job_id == "12345"
    assert job.published_at is None


def test_job_opening_location_none_or_blank_defaults_to_na():
    job_none = JobOpening(
        job_id="gh:acme:1",
        source="greenhouse",
        company="acme",
        title="Software Engineer",
        location=None,
        url="https://boards.greenhouse.io/acme/jobs/1",
    )
    assert job_none.location == "N/A"

    job_empty = JobOpening(
        job_id="gh:acme:2",
        source="greenhouse",
        company="acme",
        title="Software Engineer",
        location="   ",
        url="https://boards.greenhouse.io/acme/jobs/2",
    )
    assert job_empty.location == "N/A"


def test_job_opening_missing_required_fields_raises_validation_error():
    with pytest.raises(ValidationError):
        # Missing title and url
        JobOpening(
            job_id="gh:acme:123",
            source="greenhouse",
            company="acme",
        )


def test_target_company_valid():
    target = TargetCompany(name="acme", source="greenhouse")
    assert target.name == "acme"
    assert target.source == "greenhouse"


def test_target_company_supports_slug_alias():
    target = TargetCompany(slug="techcorp", source="lever")
    assert target.name == "techcorp"
    assert target.source == "lever"


def test_target_company_invalid_source():
    with pytest.raises(ValidationError):
        TargetCompany(name="test", source="invalid_ats")


def test_job_opening_and_target_company_support_gupy_source():
    job = JobOpening(
        job_id="gupy_999",
        source="Gupy",
        company="ambev",
        title="Engenheiro de Software",
        url="https://ambev.gupy.io/jobs/999",
    )
    assert job.source == "Gupy"
    assert job.job_id == "gupy_999"

    target = TargetCompany(name="ambev", source="Gupy")
    assert target.source == "Gupy"


def test_target_company_supports_gupy_global_source_and_query():
    target = TargetCompany(name="Python", source="gupy_global")
    assert target.source == "gupy_global"
    assert target.name == "Python"
    assert target.query is None
    assert target.search_query == "Python"

    target_with_query = TargetCompany(name="Global Search", source="gupy_global", query="Python Backend")
    assert target_with_query.source == "gupy_global"
    assert target_with_query.query == "Python Backend"
    assert target_with_query.search_query == "Python Backend"

    job = JobOpening(
        job_id="gupy_101",
        source="gupy_global",
        company="Diverse Corp",
        title="Python Dev",
        url="https://diverse.gupy.io/jobs/101",
    )
    assert job.source == "gupy_global"


def test_job_opening_dedup_key_auto_populated():
    job1 = JobOpening(
        job_id="gupy:1001",
        source="gupy",
        company="Acme Corp",
        title="Senior Python Engineer",
        location="Remote",
        url="https://example.com/1",
    )
    job2 = JobOpening(
        job_id="gupy:1002",
        source="gupy",
        company="Acme Corp",
        title="Senior Python Engineer",
        location="Remote",
        url="https://example.com/2",
    )
    # Different external/job IDs, but same semantic opening -> same dedup_key
    assert job1.dedup_key is not None
    assert len(job1.dedup_key) == 32
    assert job1.dedup_key == job2.dedup_key
    # Check that it's a valid hex string
    int(job1.dedup_key, 16)


def test_job_opening_dedup_key_normalizes_spaces_and_punctuation():
    job_clean = JobOpening(
        job_id="gupy:1",
        source="gupy",
        company="Acme Corp",
        title="Senior Backend Engineer Python",
        location="Remote Brazil",
        url="https://example.com/1",
    )
    job_noisy = JobOpening(
        job_id="gupy:2",
        source="Gupy",
        company="  Acme,  Corp.  ",
        title="Senior   Backend - Engineer! (Python)   ",
        location="Remote,  Brazil",
        url="https://example.com/2",
    )
    assert job_clean.dedup_key == job_noisy.dedup_key


def test_job_opening_dedup_key_location_none_handling():
    job_none = JobOpening(
        job_id="gupy:1",
        source="gupy",
        company="Acme",
        title="Dev",
        location=None,
        url="https://example.com/1",
    )
    job_na = JobOpening(
        job_id="gupy:2",
        source="gupy",
        company="Acme",
        title="Dev",
        location="N/A",
        url="https://example.com/2",
    )
    job_blank = JobOpening(
        job_id="gupy:3",
        source="gupy",
        company="Acme",
        title="Dev",
        location="   ",
        url="https://example.com/3",
    )
    assert job_none.dedup_key == job_na.dedup_key == job_blank.dedup_key


def test_generate_dedup_key_matches_model():
    from src.models import generate_dedup_key
    key = generate_dedup_key(ats="gupy", company="Acme", title="Dev", location=None)
    job = JobOpening(
        job_id="gupy:1",
        source="gupy",
        company="Acme",
        title="Dev",
        location=None,
        url="https://example.com/1",
    )
    assert key == job.dedup_key
    assert len(key) == 32


