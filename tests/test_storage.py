from datetime import datetime, timezone
import pytest
from src.models import JobOpening
from src.storage import SQLiteStorage


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_jobs.db"
    return db_path


def make_sample_job(job_id: str, title: str = "Backend Engineer") -> JobOpening:
    return JobOpening(
        job_id=job_id,
        source="greenhouse",
        company="acme",
        title=title,
        location="Remote",
        url=f"https://example.com/jobs/{job_id}",
        published_at=datetime.now(timezone.utc),
    )


def test_storage_auto_creates_schema(temp_db):
    storage = SQLiteStorage(db_path=str(temp_db))
    # Schema should be initialized and queryable
    assert storage.is_new("nonexistent_id") is True


def test_storage_mark_as_seen_and_is_new(temp_db):
    storage = SQLiteStorage(db_path=str(temp_db))
    job = make_sample_job("gh:acme:1001")

    assert storage.is_new(job.job_id) is True
    storage.mark_as_seen(job)
    assert storage.is_new(job.job_id) is False


def test_storage_idempotency_duplicate_inserts(temp_db):
    storage = SQLiteStorage(db_path=str(temp_db))
    job = make_sample_job("gh:acme:1002")

    # Marking multiple times shouldn't raise exception
    storage.mark_as_seen(job)
    storage.mark_as_seen(job)
    assert storage.is_new(job.job_id) is False


def test_storage_filter_new_jobs(temp_db):
    storage = SQLiteStorage(db_path=str(temp_db))
    job1 = make_sample_job("gh:acme:1")
    job2 = make_sample_job("gh:acme:2")
    job3 = make_sample_job("gh:acme:3")

    storage.mark_as_seen(job1)

    new_jobs = storage.filter_new_jobs([job1, job2, job3])
    assert len(new_jobs) == 2
    assert [j.job_id for j in new_jobs] == ["gh:acme:2", "gh:acme:3"]


def test_storage_recreates_schema_if_db_reopened(temp_db):
    storage1 = SQLiteStorage(db_path=str(temp_db))
    job = make_sample_job("gh:acme:4")
    storage1.mark_as_seen(job)

    # Reopen same db
    storage2 = SQLiteStorage(db_path=str(temp_db))
    assert storage2.is_new("gh:acme:4") is False
    assert storage2.is_new("gh:acme:5") is True


def test_storage_persists_dedup_key(temp_db):
    storage = SQLiteStorage(db_path=str(temp_db))
    job = make_sample_job("gh:acme:10")
    assert storage.mark_as_seen(job) is True
    # Inserting same job again returns False (idempotent / duplicate)
    assert storage.mark_as_seen(job) is False

    with storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT dedup_key FROM seen_jobs WHERE job_id = ?;", (job.job_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == job.dedup_key

