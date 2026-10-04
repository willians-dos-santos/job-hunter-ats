from datetime import datetime
from typing import Any, List, Optional
from src.collectors.base import BaseCollector
from src.models import JobOpening, TargetCompany


class GupyCollector(BaseCollector):
    """Collector adapter for Gupy public careers portal API."""

    def build_url(self, target: TargetCompany) -> str:
        # FR-001: Public portal endpoint with subdomain and limit=100
        return f"https://portal.api.gupy.io/api/v1/jobs?subdomain={target.name}&limit=100"

    def get_headers(self) -> dict:
        # FR-002: User-Agent header to avoid CDN blocks or 403 responses
        return {"User-Agent": "Mozilla/5.0"}

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
