from datetime import datetime
import logging
from typing import Any, List, Optional
import httpx
from src.collectors.base import BaseCollector
from src.models import JobOpening, TargetCompany

logger = logging.getLogger(__name__)


class GupyCollector(BaseCollector):
    """Collector adapter for Gupy public careers portal API with subdomain fallback."""

    def build_url(self, target: TargetCompany) -> str:
        # Portal endpoint querying by careerPageName
        return f"https://portal.api.gupy.io/api/v1/jobs?careerPageName={target.name}&limit=100"

    def build_fallback_url(self, target: TargetCompany) -> str:
        # Fallback to direct company subdomain endpoint
        return f"https://{target.name}.gupy.io/api/v1/jobs?limit=100"

    def get_headers(self) -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
        }

    async def fetch_jobs(
        self, target: TargetCompany, client: Optional[httpx.AsyncClient] = None
    ) -> List[JobOpening]:
        """Fetches jobs via careerPageName, falling back to direct company subdomain if empty or 404."""
        primary_url = self.build_url(target)
        jobs = await self.fetch_jobs_from_url(primary_url, target, client=client)
        if jobs:
            return jobs

        fallback_url = self.build_fallback_url(target)
        logger.info(
            f"Gupy primary endpoint returned no jobs for {target.name}. Trying fallback: {fallback_url}"
        )
        return await self.fetch_jobs_from_url(fallback_url, target, client=client)

    def parse_jobs(self, target: TargetCompany, raw_data: Any) -> List[JobOpening]:
        if not isinstance(raw_data, dict):
            return []

        # FR-003: Root 'data' envelope
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

            # Title
            title = str(item.get("name") or "").strip()

            # Canonical URL resolution
            url = (
                item.get("careerPageUrl")
                or item.get("jobUrl")
                or f"https://{target.name}.gupy.io/jobs/{raw_id_str}"
            )

            # Location formatting
            if item.get("isRemoteWork") is True:
                location = "Remoto"
            else:
                city = str(item.get("city") or "").strip()
                state = str(item.get("state") or "").strip()
                if city and state:
                    location = f"{city} - {state}"
                elif city:
                    location = city
                elif state:
                    location = state
                else:
                    location = "N/A"

            # Parse optional publishedDate
            published_date_raw = item.get("publishedDate") or item.get("createdAt")
            published_at: Optional[datetime] = None
            if isinstance(published_date_raw, str):
                try:
                    published_at = datetime.fromisoformat(published_date_raw.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    published_at = None

            parsed_jobs.append(
                JobOpening(
                    job_id=f"gupy_{raw_id_str}",
                    source="Gupy",
                    company=target.name,
                    title=title,
                    location=location,
                    url=url,
                    published_at=published_at,
                    source_job_id=raw_id_str,
                )
            )

        return parsed_jobs
