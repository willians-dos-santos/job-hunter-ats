import inspect
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Union

from supabase import AsyncClient, create_async_client

from src.models import JobOpening

logger = logging.getLogger("job_hunter_ats.storage")


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


class SupabaseStorage:
    """Supabase REST-based PostgreSQL storage adapter for ephemeral cloud execution."""

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        table_name: str = "jobs",
    ) -> None:
        self.url = (url or os.getenv("SUPABASE_URL") or "").strip()
        self.key = (key or os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        self.table_name = table_name
        self._client: Optional[AsyncClient] = None

        if not self.url or not self.key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY must be provided or configured in the environment."
            )

    async def get_client(self) -> AsyncClient:
        """Lazily initializes and returns the Supabase AsyncClient."""
        if self._client is None:
            self._client = await create_async_client(self.url, self.key)
        return self._client

    async def is_seen(self, job_id: str) -> bool:
        """Checks if a job_id already exists in the Supabase jobs table."""
        try:
            client = await self.get_client()
            table = client.table(self.table_name)
            if inspect.isawaitable(table):
                table = await table
            res = await table.select("id").eq("id", job_id).execute()
            return bool(res.data)
        except Exception as exc:
            logger.error(
                f"Error checking existence for job '{job_id}' in Supabase: {exc}",
                exc_info=True,
            )
            return False

    def _build_job_payload(self, job: JobOpening) -> Dict[str, Any]:
        """Normalizes and serializes a JobOpening into a database payload dictionary."""
        ats = getattr(job, "ats", None) or getattr(job, "source", None)
        if not ats and hasattr(job, "job_id") and ":" in job.job_id:
            ats = job.job_id.split(":")[0]
        ats_str = str(ats).lower() if ats else ""

        external_id = (
            getattr(job, "external_id", None)
            or getattr(job, "source_job_id", None)
        )
        if not external_id and hasattr(job, "job_id"):
            parts = job.job_id.split(":")
            external_id = parts[-1]
        external_id_str = str(external_id) if external_id is not None else ""

        if ats_str and external_id_str:
            normalized_id = f"{ats_str}:{external_id_str}"
        else:
            normalized_id = str(getattr(job, "id", None) or getattr(job, "job_id", ""))

        published_at_str = None
        if getattr(job, "published_at", None):
            dt = job.published_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            published_at_str = dt.isoformat()

        location_val = getattr(job, "location", None)
        if location_val in (None, "N/A", ""):
            location_val = None

        return {
            "id": normalized_id,
            "ats": ats_str,
            "external_id": external_id_str,
            "title": job.title,
            "company": job.company,
            "location": location_val,
            "url": str(job.url),
            "published_at": published_at_str,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def save_job(self, job: JobOpening) -> bool:
        """Upserts a job into the Supabase jobs table with conflict handling on 'id'."""
        try:
            payload = self._build_job_payload(job)
            client = await self.get_client()
            table = client.table(self.table_name)
            if inspect.isawaitable(table):
                table = await table
            await table.upsert(payload, on_conflict="id").execute()
            return True
        except Exception as exc:
            logger.error(
                f"Error saving job '{getattr(job, 'id', None) or getattr(job, 'job_id', '')}' to Supabase: {exc}",
                exc_info=True,
            )
            return False

    async def is_new(self, job_id: str) -> bool:
        """Returns True if the job_id has NOT been recorded yet."""
        return not await self.is_seen(job_id)

    async def filter_new_jobs(self, jobs: Iterable[JobOpening]) -> list[JobOpening]:
        """Filters a collection of jobs, returning only those not yet seen."""
        new_jobs = []
        for job in jobs:
            job_id = getattr(job, "id", None) or getattr(job, "job_id", "")
            if not await self.is_seen(job_id):
                new_jobs.append(job)
        return new_jobs

    async def mark_as_seen(self, job: Union[JobOpening, str]) -> bool:
        """Marks a job (or job_id) as seen by saving it or creating a placeholder."""
        if isinstance(job, JobOpening):
            return await self.save_job(job)

        job_id_str = str(job)
        parts = job_id_str.split(":", 1)
        ats = parts[0] if len(parts) > 1 else ""
        ext_id = parts[1] if len(parts) > 1 else job_id_str
        payload = {
            "id": job_id_str,
            "ats": ats,
            "external_id": ext_id,
            "title": "",
            "company": "",
            "location": None,
            "url": "",
            "published_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            client = await self.get_client()
            table = client.table(self.table_name)
            if inspect.isawaitable(table):
                table = await table
            await table.upsert(payload, on_conflict="id").execute()
            return True
        except Exception as exc:
            logger.error(f"Error marking job_id '{job_id_str}' as seen in Supabase: {exc}", exc_info=True)
            return False

