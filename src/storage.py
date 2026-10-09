import inspect
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from pydantic import BaseModel, Field
from supabase import AsyncClient, create_async_client

from src.models import JobOpening, TargetCompany, generate_dedup_key

logger = logging.getLogger("job_hunter_ats.storage")


class SearchConfigData(BaseModel):
    """Dynamic search configuration loaded from Supabase `public.search_configs`."""
    keywords: List[str] = Field(default_factory=list, description="Target job title keywords")
    excluded_keywords: List[str] = Field(default_factory=list, description="Excluded job title keywords")
    locations: List[str] = Field(default_factory=list, description="Target location keywords")
    companies: List[str] = Field(default_factory=list, description="Target company names")
    ats_filter: Dict[str, Any] = Field(default_factory=dict, description="Global ATS filter options")
    target_companies: List[TargetCompany] = Field(default_factory=list, description="Target company models")

    @property
    def is_empty(self) -> bool:
        return not (
            self.keywords
            or self.excluded_keywords
            or self.locations
            or self.companies
            or self.ats_filter
            or self.target_companies
        )

    def __bool__(self) -> bool:
        return not self.is_empty


def _parse_metadata(raw_metadata: Any) -> Dict[str, Any]:
    if isinstance(raw_metadata, dict):
        return raw_metadata
    if isinstance(raw_metadata, str):
        try:
            parsed = json.loads(raw_metadata)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


async def load_search_configs(
    client: Any,
    user_id: Optional[str] = None,
) -> Optional[SearchConfigData]:
    """Queries dynamic search configurations from Supabase `public.search_configs`.

    Criteria:
    - Strictly filter by `is_active = True`.
    - If `user_id` is provided, filter by `user_id = user_id`.
    - Fields: `category`, `value`, `metadata`.

    Category mapping:
    - `keyword` -> keywords
    - `excluded_keyword` -> excluded_keywords
    - `location` -> locations
    - `company` -> companies (and target_companies)
    - `ats_filter` -> global options extracted from metadata (e.g. max_days_old, exclude_inactive)

    Returns:
    - SearchConfigData if query succeeds and has at least one active rule.
    - None if empty, error, or no active rules found.
    """
    if client is None:
        return None

    try:
        table_fn = getattr(client, "table", None) or getattr(client, "from_", None)
        if not table_fn:
            return None

        table = table_fn("search_configs")
        if inspect.isawaitable(table):
            table = await table

        query = table.select("category, value, metadata").eq("is_active", True)
        if user_id:
            query = query.eq("user_id", user_id)

        res = query.execute()
        if inspect.isawaitable(res):
            res = await res

        data = getattr(res, "data", None)
        if data is None and isinstance(res, (list, tuple)):
            data = res
        elif data is None and isinstance(res, dict) and "data" in res:
            data = res["data"]

        if not data or not isinstance(data, list):
            return None

        keywords: List[str] = []
        excluded_keywords: List[str] = []
        locations: List[str] = []
        companies: List[str] = []
        ats_filter: Dict[str, Any] = {}
        target_companies: List[TargetCompany] = []

        for row in data:
            if not isinstance(row, dict):
                continue
            cat = str(row.get("category") or "").strip().lower()
            val = row.get("value")
            meta = _parse_metadata(row.get("metadata"))
            val_str = str(val).strip() if val is not None else ""

            if cat in ("keyword", "keywords"):
                if val_str:
                    keywords.append(val_str)
            elif cat in ("excluded_keyword", "excluded_keywords"):
                if val_str:
                    excluded_keywords.append(val_str)
            elif cat in ("location", "locations"):
                if val_str:
                    locations.append(val_str)
            elif cat in ("company", "companies"):
                if val_str:
                    companies.append(val_str)
                    src = meta.get("source", "greenhouse")
                    if src not in {"greenhouse", "lever", "Gupy", "gupy", "gupy_global"}:
                        src = "greenhouse"
                    target_companies.append(
                        TargetCompany(
                            name=val_str,
                            source=src,
                            slug=meta.get("slug"),
                            query=meta.get("query"),
                        )
                    )
            elif cat in ("ats_filter", "ats_filters", "filter", "filters"):
                if meta:
                    ats_filter.update(meta)
                    if val_str and "value" in meta and val_str not in meta:
                        ats_filter[val_str] = meta["value"]
                elif val_str:
                    ats_filter[val_str] = True

        config_data = SearchConfigData(
            keywords=keywords,
            excluded_keywords=excluded_keywords,
            locations=locations,
            companies=companies,
            ats_filter=ats_filter,
            target_companies=target_companies,
        )

        if config_data.is_empty:
            return None

        return config_data

    except Exception as exc:
        logger.warning(f"Error querying search configs from Supabase: {exc}", exc_info=True)
        return None



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
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    dedup_key TEXT
                );
                """
            )
            # Ensure dedup_key column exists if table was previously created without it
            cursor.execute("PRAGMA table_info(seen_jobs);")
            columns = [col[1] for col in cursor.fetchall()]
            if "dedup_key" not in columns:
                cursor.execute("ALTER TABLE seen_jobs ADD COLUMN dedup_key TEXT;")
            conn.commit()

    def is_new(self, job_id: str) -> bool:
        """Returns True if the job_id has not been recorded yet."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM seen_jobs WHERE job_id = ? LIMIT 1;", (job_id,))
            return cursor.fetchone() is None

    def mark_as_seen(self, job: Union[JobOpening, str]) -> bool:
        """Marks a job (or job_id) as seen idempotently. Returns True if newly inserted, False if duplicate."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if isinstance(job, JobOpening):
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO seen_jobs (job_id, source, company, title, url, location, dedup_key)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (job.job_id, job.source, job.company, job.title, job.url, job.location, job.dedup_key),
                )
            else:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO seen_jobs (job_id, source, company, title, url, location, dedup_key)
                    VALUES (?, '', '', '', '', '', ?);
                    """,
                    (str(job), str(job)),
                )
            conn.commit()
            return cursor.rowcount > 0

    def save_job(self, job: JobOpening) -> bool:
        """Saves a job idempotently. Returns True if inserted, False if duplicate."""
        return self.mark_as_seen(job)

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

    async def is_seen(self, job_id: str, dedup_key: Optional[str] = None) -> bool:
        """Checks if a job_id or dedup_key already exists in the Supabase jobs table."""
        try:
            client = await self.get_client()
            table = client.table(self.table_name)
            if inspect.isawaitable(table):
                table = await table
            if dedup_key:
                res = await table.select("id").eq("dedup_key", dedup_key).execute()
            else:
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

        dedup_key = getattr(job, "dedup_key", None)
        if not dedup_key:
            dedup_key = generate_dedup_key(job)

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
            "dedup_key": dedup_key,
        }

    async def save_job(self, job: JobOpening) -> bool:
        """Upserts a job into the Supabase jobs table with conflict handling on 'dedup_key'."""
        try:
            payload = self._build_job_payload(job)
            client = await self.get_client()
            table = client.table(self.table_name)
            if inspect.isawaitable(table):
                table = await table
            res = await table.upsert(
                payload,
                on_conflict="dedup_key",
                ignore_duplicates=True,
            ).execute()
            # If the job was newly inserted, res.data contains the record.
            # If it was ignored due to conflict on dedup_key, res.data is empty.
            if res and hasattr(res, "data") and res.data:
                return True
            return False
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
        seen_dedup_keys = set()
        for job in jobs:
            dedup_key = getattr(job, "dedup_key", None)
            if dedup_key and dedup_key in seen_dedup_keys:
                continue
            job_id = getattr(job, "id", None) or getattr(job, "job_id", "")
            if not await self.is_seen(job_id):
                new_jobs.append(job)
                if dedup_key:
                    seen_dedup_keys.add(dedup_key)
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
            "dedup_key": generate_dedup_key(ats=ats, company=job_id_str, title=job_id_str, location=""),
        }
        try:
            client = await self.get_client()
            table = client.table(self.table_name)
            if inspect.isawaitable(table):
                table = await table
            res = await table.upsert(
                payload,
                on_conflict="dedup_key",
                ignore_duplicates=True,
            ).execute()
            if res and hasattr(res, "data") and res.data:
                return True
            return False
        except Exception as exc:
            logger.error(f"Error marking job_id '{job_id_str}' as seen in Supabase: {exc}", exc_info=True)
            return False

    async def load_search_configs(
        self, user_id: Optional[str] = None
    ) -> Optional[SearchConfigData]:
        """Loads search configurations for a specific user_id."""
        client = await self.get_client()
        return await load_search_configs(client, user_id=user_id)


