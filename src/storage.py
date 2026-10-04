import sqlite3
from pathlib import Path
from typing import Union, Iterable
from src.models import JobOpening


class SQLiteStorage:
    """SQLite repository for job deduplication and idempotency."""

    def __init__(self, db_path: str = "jobs.db") -> None:
        self.db_path = Path(db_path)
        self._ensure_db_dir()
        self._init_db()

    def _ensure_db_dir(self) -> None:
        if self.db_path.parent and not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_jobs (
                    job_id TEXT PRIMARY KEY,
                    source TEXT,
                    company TEXT,
                    title TEXT,
                    url TEXT,
                    location TEXT,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.commit()

    def is_new(self, job_id: str) -> bool:
        """Returns True if the job_id has not been recorded yet."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM seen_jobs WHERE job_id = ? LIMIT 1;", (job_id,))
            return cursor.fetchone() is None

    def mark_as_seen(self, job: Union[JobOpening, str]) -> None:
        """Marks a job (or job_id) as seen idempotently."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if isinstance(job, JobOpening):
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO seen_jobs (job_id, source, company, title, url, location)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (job.job_id, job.source, job.company, job.title, job.url, job.location),
                )
            else:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO seen_jobs (job_id, source, company, title, url, location)
                    VALUES (?, '', '', '', '', '');
                    """,
                    (str(job),),
                )
            conn.commit()

    def filter_new_jobs(self, jobs: Iterable[JobOpening]) -> list[JobOpening]:
        """Filters a collection of jobs, returning only those not yet seen."""
        new_jobs = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for job in jobs:
                cursor.execute("SELECT 1 FROM seen_jobs WHERE job_id = ? LIMIT 1;", (job.job_id,))
                if cursor.fetchone() is None:
                    new_jobs.append(job)
        return new_jobs
