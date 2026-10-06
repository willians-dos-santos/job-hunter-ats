from datetime import datetime, timedelta, timezone
from typing import Optional
import pytest
from src.filters import JobFilter
from src.models import JobOpening


def make_job(
    title: str = "Backend Engineer",
    location: str = "Remote",
    url: str = "https://example.com/job/1",
    published_at: Optional[datetime] = None,
) -> JobOpening:
    return JobOpening(
        job_id="test:1",
        source="greenhouse",
        company="acme",
        title=title,
        location=location,
        url=url,
        published_at=published_at,
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


def test_filter_published_today_accepted():
    now_utc = datetime.now(timezone.utc)
    job = make_job("Backend Engineer", "Remote", published_at=now_utc)
    criteria = JobFilter(max_days_old=30)
    assert criteria.matches(job) is True


def test_filter_published_within_days_limit_accepted():
    twenty_days_ago = datetime.now(timezone.utc) - timedelta(days=20)
    job = make_job("Backend Engineer", "Remote", published_at=twenty_days_ago)
    criteria = JobFilter(max_days_old=30)
    assert criteria.matches(job) is True


def test_filter_published_past_days_limit_rejected():
    sixty_days_ago = datetime.now(timezone.utc) - timedelta(days=60)
    job = make_job("Backend Engineer", "Remote", published_at=sixty_days_ago)
    criteria = JobFilter(max_days_old=30)
    assert criteria.matches(job) is False


def test_filter_published_at_none_accepted():
    job = make_job("Backend Engineer", "Remote", published_at=None)
    criteria = JobFilter(max_days_old=30)
    assert criteria.matches(job) is True


def test_filter_inactive_url_rejected_when_enabled():
    job_inactive_subdomain = make_job(
        "Backend Engineer",
        "Remote",
        url="https://inactive.gupy.io/job/123",
    )
    job_inactive_param = make_job(
        "Backend Engineer",
        "Remote",
        url="https://empresa.gupy.io/job/123&inactive.gupy.io",
    )
    criteria = JobFilter(exclude_inactive=True)
    assert criteria.matches(job_inactive_subdomain) is False
    assert criteria.matches(job_inactive_param) is False


def test_filter_inactive_url_accepted_when_disabled():
    job_inactive = make_job(
        "Backend Engineer",
        "Remote",
        url="https://empresa.gupy.io/job/123&inactive.gupy.io",
    )
    criteria = JobFilter(exclude_inactive=False)
    assert criteria.matches(job_inactive) is True


def test_filter_temporal_disabled_with_zero_or_none():
    old_date = datetime.now(timezone.utc) - timedelta(days=120)
    old_job = make_job("Backend Engineer", "Remote", published_at=old_date)

    criteria_zero = JobFilter(max_days_old=0)
    assert criteria_zero.matches(old_job) is True

    criteria_negative = JobFilter(max_days_old=-5)
    assert criteria_negative.matches(old_job) is True

    criteria_none = JobFilter(max_days_old=None)
    assert criteria_none.matches(old_job) is True
