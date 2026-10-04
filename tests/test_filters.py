import pytest
from src.filters import JobFilter
from src.models import JobOpening


def make_job(title: str, location: str) -> JobOpening:
    return JobOpening(
        job_id="test:1",
        source="greenhouse",
        company="acme",
        title=title,
        location=location,
        url="https://example.com/job/1",
    )


def test_filter_matches_title_and_location():
    # Acceptance Scenario 1 from spec
    criteria = JobFilter(
        title_keywords=["Backend"],
        location_keywords=["Remote"],
    )

    job_matching = make_job("Senior Backend Engineer", "Remote, Brazil")
    assert criteria.matches(job_matching) is True


def test_filter_rejects_non_matching_title():
    criteria = JobFilter(
        title_keywords=["Backend"],
        location_keywords=["Remote"],
    )

    job = make_job("Frontend Architect", "Remote")
    assert criteria.matches(job) is False


def test_filter_rejects_non_matching_location():
    criteria = JobFilter(
        title_keywords=["Backend"],
        location_keywords=["Remote"],
    )

    job = make_job("Senior Backend Developer", "Onsite - New York")
    assert criteria.matches(job) is False


def test_filter_case_insensitivity():
    criteria = JobFilter(
        title_keywords=["python", "backend"],
        location_keywords=["remote"],
    )

    job = make_job("STAFF BACKEND DEVELOPER", "REMOTE - LATAM")
    assert criteria.matches(job) is True


def test_filter_exclusion_keywords():
    criteria = JobFilter(
        title_keywords=["Backend"],
        title_exclude=["Junior", "Intern"],
        location_keywords=["Remote"],
        location_exclude=["US Only"],
    )

    job_valid = make_job("Senior Backend Engineer", "Remote - Worldwide")
    assert criteria.matches(job_valid) is True

    job_excluded_title = make_job("Junior Backend Engineer", "Remote - Worldwide")
    assert criteria.matches(job_excluded_title) is False

    job_excluded_loc = make_job("Senior Backend Engineer", "Remote - US Only")
    assert criteria.matches(job_excluded_loc) is False


def test_filter_empty_criteria_matches_all():
    criteria = JobFilter()
    job = make_job("Any Title", "Anywhere")
    assert criteria.matches(job) is True


def test_filter_jobs_batch_processing():
    criteria = JobFilter(
        title_keywords=["Backend"],
        location_keywords=["Remote"],
    )

    jobs = [
        make_job("Backend Engineer", "Remote"),
        make_job("Frontend Engineer", "Remote"),
        make_job("Backend Engineer", "Onsite"),
    ]

    filtered = criteria.filter_jobs(jobs)
    assert len(filtered) == 1
    assert filtered[0].title == "Backend Engineer"
    assert filtered[0].location == "Remote"
