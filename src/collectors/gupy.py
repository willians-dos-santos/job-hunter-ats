from datetime import datetime
import logging
from typing import Any, Dict, List, Optional
import httpx
from src.collectors.base import BaseCollector
from src.models import JobOpening, TargetCompany

logger = logging.getLogger(__name__)


class GupyCollector(BaseCollector):
    """Collector adapter for Gupy official public portal job-search API."""

    BASE_URL = "https://portal.gupy.io/api/job-search/jobs"

    def build_url(self, target: TargetCompany) -> str:
        return self.BASE_URL

    def build_params(self, target: TargetCompany) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "limit": 100,
            "offset": 0,
        }
        if target.name:
            params["careerPageName"] = target.name
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

    def parse_jobs(self, target: TargetCompany, raw_data: Any) -> List[JobOpening]:
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

            # Model & Normalization
            job_id = f"gupy_{item['id']}"
            title = str(item.get("name") or "").strip()
            company = item.get("careerPageName") or (target.name if target and target.name else "Stefanini Group")
            url = (
                item.get("jobUrl")
                or item.get("careerPageUrl")
                or f"https://portal.gupy.io/job-search/jobs/{raw_id_str}"
            )

            # Location resolution based on workplaceType
            workplace_type = str(item.get("workplaceType") or "").strip().lower()
            if workplace_type == "remote" or item.get("isRemoteWork") is True:
                location = "Remoto"
            else:
                city = item.get("city", "") or ""
                state = item.get("state", "") or ""
                city_state = f"{city} - {state}".strip(" - ")
                location = city_state if city_state else "Presencial"

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
                    job_id=job_id,
                    source="Gupy",
                    company=company,
                    title=title,
                    location=location,
                    url=url,
                    published_at=published_at,
                    source_job_id=raw_id_str,
                )
            )

        return parsed_jobs
