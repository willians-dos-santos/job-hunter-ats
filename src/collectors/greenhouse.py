from datetime import datetime
from typing import Any, List, Optional
from src.collectors.base import BaseCollector
from src.models import JobOpening, TargetCompany


class GreenhouseCollector(BaseCollector):
    """Collector adapter for Greenhouse ATS public API."""

    def build_url(self, target: TargetCompany) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{target.name}/jobs"

    def parse_jobs(self, target: TargetCompany, raw_data: Any) -> List[JobOpening]:
        if not isinstance(raw_data, dict):
            return []

        jobs_list = raw_data.get("jobs", [])
        if not isinstance(jobs_list, list):
            return []

        parsed_jobs: List[JobOpening] = []
        for item in jobs_list:
            if not isinstance(item, dict):
                continue

            raw_id = str(item.get("id", "")).strip()
            if not raw_id:
                continue

            # Extract location safely with edge-case handling
            location_val = item.get("location")
            location_str = "N/A"
            if isinstance(location_val, dict):
                name = location_val.get("name")
                if name and str(name).strip():
                    location_str = str(name).strip()
            elif isinstance(location_val, str) and location_val.strip():
                location_str = location_val.strip()

            # Extract published / updated datetime
            updated_at_str = item.get("updated_at")
            published_at: Optional[datetime] = None
            if updated_at_str and isinstance(updated_at_str, str):
                try:
                    published_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    published_at = None

            url = item.get("absolute_url") or ""
            title = item.get("title") or ""

            parsed_jobs.append(
                JobOpening(
                    job_id=f"greenhouse:{target.name}:{raw_id}",
                    source="greenhouse",
                    company=target.name,
                    title=title,
                    location=location_str,
                    url=url,
                    published_at=published_at,
                    source_job_id=raw_id,
                )
            )

        return parsed_jobs
