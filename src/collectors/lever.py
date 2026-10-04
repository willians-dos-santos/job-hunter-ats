from datetime import datetime, timezone
from typing import Any, List, Optional
from src.collectors.base import BaseCollector
from src.models import JobOpening, TargetCompany


class LeverCollector(BaseCollector):
    """Collector adapter for Lever ATS public API."""

    def build_url(self, target: TargetCompany) -> str:
        return f"https://api.lever.co/v0/postings/{target.name}?mode=json"

    def parse_jobs(self, target: TargetCompany, raw_data: Any) -> List[JobOpening]:
        if not isinstance(raw_data, list):
            return []

        parsed_jobs: List[JobOpening] = []
        for item in raw_data:
            if not isinstance(item, dict):
                continue

            raw_id = str(item.get("id", "")).strip()
            if not raw_id:
                continue

            # Extract location from categories safely
            categories = item.get("categories")
            location_str = "N/A"
            if isinstance(categories, dict):
                loc = categories.get("location")
                if loc and str(loc).strip():
                    location_str = str(loc).strip()

            # Parse createdAt timestamp (Lever uses epoch milliseconds)
            created_at = item.get("createdAt")
            published_at: Optional[datetime] = None
            if isinstance(created_at, (int, float)):
                try:
                    published_at = datetime.fromtimestamp(created_at / 1000.0, tz=timezone.utc)
                except (ValueError, OSError, OverflowError):
                    published_at = None
            elif isinstance(created_at, str):
                try:
                    published_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    published_at = None

            url = item.get("hostedUrl") or item.get("applyUrl") or ""
            title = item.get("text") or ""

            parsed_jobs.append(
                JobOpening(
                    job_id=f"lever:{target.name}:{raw_id}",
                    source="lever",
                    company=target.name,
                    title=title,
                    location=location_str,
                    url=url,
                    published_at=published_at,
                    source_job_id=raw_id,
                )
            )

        return parsed_jobs
