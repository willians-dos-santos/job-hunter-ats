import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from src.collectors.base import BaseCollector
from src.models import JobOpening, TargetCompany

logger = logging.getLogger(__name__)


class SolidesCollector(BaseCollector):
    """Collector adapter for Solides official public vacancies API (vagas.solides.com.br)."""

    BASE_URL = "https://vagas.solides.com.br/api/vacancies"

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        max_pages: Optional[int] = None,
        take: int = 20,
    ) -> None:
        super().__init__(max_retries=max_retries, backoff_factor=backoff_factor)
        self.max_pages = max_pages
        self.take = take

    def build_url(self, target: TargetCompany) -> str:
        return self.BASE_URL

    def build_params(self, target: TargetCompany, page: int = 1) -> Dict[str, Any]:
        """Builds query parameters with dynamic title and empty locations."""
        params: Dict[str, Any] = {
            "page": page,
            "take": self.take,
            "locations": "",
        }

        # Dynamic title resolution: target.query or target.name (if not platform name)
        title = target.query
        if not title and target.name:
            norm_name = target.name.strip().lower()
            if norm_name not in ("solides", "solides vagas", "solides_global", "solides tech"):
                title = target.name.strip()

        if title:
            params["title"] = title

        return params

    def get_headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

    def map_modality(self, job_type: Optional[str], home_office: Optional[bool]) -> str:
        """Maps Solides workplace settings to canonical modality: remote, hybrid, or on_site."""
        jt = str(job_type or "").strip().lower()
        if jt == "remoto" or home_office is True:
            return "remote"
        if "hibrid" in jt or "híbrid" in jt:
            return "hybrid"
        return "on_site"

    def parse_jobs(self, target: TargetCompany, raw_data: Any) -> List[JobOpening]:
        """Parses the raw vacancies API response into a list of JobOpening models."""
        if not isinstance(raw_data, dict):
            return []

        jobs_list = raw_data.get("data")
        if not isinstance(jobs_list, list):
            return []

        parsed_jobs: List[JobOpening] = []
        for item in jobs_list:
            if not isinstance(item, dict):
                continue

            raw_id = item.get("id")
            if raw_id is None:
                continue
            raw_id_str = str(raw_id).strip()
            if not raw_id_str:
                continue

            # Identifiers & canonical public URL
            job_id = f"solides_{raw_id_str}"
            source_job_id = raw_id_str
            url = f"https://vagas.solides.com.br/vaga/{raw_id_str}"

            # Title & Company
            title = str(item.get("title") or "").strip()
            raw_company = item.get("companyName")
            company = str(raw_company).strip() if raw_company else "Solides"

            # Modality mapping
            modality = self.map_modality(item.get("jobType"), item.get("homeOffice"))

            # Defensive location formatting with fallback to "Remoto"
            city_obj = item.get("city") if isinstance(item.get("city"), dict) else {}
            state_obj = item.get("state") if isinstance(item.get("state"), dict) else {}

            city_name = str(city_obj.get("name") or "").strip() if isinstance(city_obj, dict) else ""
            state_code = (
                str(state_obj.get("code") or state_obj.get("name") or "").strip() if isinstance(state_obj, dict) else ""
            )

            if modality == "remote":
                location = "Remoto"
            elif city_name and state_code:
                location = f"{city_name} - {state_code}"
            elif city_name:
                location = city_name
            elif state_code:
                location = state_code
            else:
                location = "Remoto"

            # Published at timestamp parsing from createdAt (YYYY-MM-DD or ISO)
            created_at_raw = item.get("createdAt")
            published_at: Optional[datetime] = None
            if isinstance(created_at_raw, datetime):
                published_at = (
                    created_at_raw.replace(tzinfo=timezone.utc)
                    if created_at_raw.tzinfo is None
                    else created_at_raw.astimezone(timezone.utc)
                )
            elif isinstance(created_at_raw, str) and created_at_raw.strip():
                clean_date = created_at_raw.strip().replace("Z", "+00:00")
                try:
                    dt = datetime.fromisoformat(clean_date)
                    published_at = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
                except (ValueError, TypeError):
                    try:
                        dt = datetime.strptime(clean_date[:10], "%Y-%m-%d")
                        published_at = dt.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        published_at = None

            # Safe fallback date if createdAt is missing, null, or failed parsing
            if published_at is None:
                published_at = datetime.now(timezone.utc)

            try:
                job_opening = JobOpening(
                    job_id=job_id,
                    source="solides",
                    company=company,
                    title=title,
                    location=location,
                    url=url,
                    published_at=published_at,
                    source_job_id=source_job_id,
                    modality=modality,
                )
                parsed_jobs.append(job_opening)
            except Exception as exc:
                logger.warning(f"Error normalizing Solides vacancy {raw_id_str}: {exc}")
                continue

        return parsed_jobs

    async def _fetch_page(
        self,
        url: str,
        params: Dict[str, Any],
        client: httpx.AsyncClient,
    ) -> Optional[Dict[str, Any]]:
        """Fetches a single page with defensive retries and rate limiting."""
        headers = self.get_headers()
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(url, headers=headers, params=params)
                if response.status_code == 200:
                    try:
                        data = response.json()
                        return data if isinstance(data, dict) else None
                    except Exception:
                        return None
                elif response.status_code == 429:
                    if attempt < self.max_retries:
                        retry_after = response.headers.get("Retry-After")
                        delay = float(retry_after) if retry_after else self.backoff_factor * (2**attempt)
                        logger.warning(f"Rate limited (429) on Solides vacancies. Backing off {delay:.2f}s...")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(f"Rate limit exceeded (429) on Solides after {self.max_retries} retries.")
                        return None
                elif response.status_code == 404:
                    logger.warning(f"Solides vacancies endpoint returned 404 ({url})")
                    return None
                else:
                    logger.warning(f"Received HTTP {response.status_code} from Solides API ({url})")
                    return None
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt < self.max_retries:
                    delay = self.backoff_factor * (2**attempt)
                    logger.warning(f"Network error on Solides ({url}): {exc}. Retrying in {delay:.2f}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Failed to fetch Solides vacancies after {self.max_retries} attempts: {exc}")
                    return None
        return None

    async def fetch_jobs(self, target: TargetCompany, client: Optional[httpx.AsyncClient] = None) -> List[JobOpening]:
        """Fetches and parses job openings from Solides with automatic multi-page pagination."""
        url = self.build_url(target)
        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=15.0)
            should_close = True

        all_jobs: List[JobOpening] = []
        current_page = 1
        total_pages = 1

        try:
            while current_page <= total_pages:
                if self.max_pages is not None and current_page > self.max_pages:
                    break

                params = self.build_params(target, page=current_page)
                page_data = await self._fetch_page(url, params, client)

                if not page_data:
                    break

                # Extract totalPages on first page
                if current_page == 1:
                    raw_total = page_data.get("totalPages")
                    try:
                        total_pages = int(raw_total) if raw_total is not None else 1
                    except (ValueError, TypeError):
                        total_pages = 1

                    if total_pages < 1:
                        break

                page_jobs = self.parse_jobs(target, page_data)
                if not page_jobs and current_page > 1:
                    # No more jobs found on subsequent page
                    break

                all_jobs.extend(page_jobs)
                current_page += 1

            return all_jobs
        finally:
            if should_close:
                await client.aclose()
