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

