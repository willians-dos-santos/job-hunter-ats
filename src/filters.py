from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from pydantic import BaseModel, Field

from src.models import JobOpening


class JobFilter(BaseModel):
    """Deterministic filter criteria for job openings."""

    title_keywords: List[str] = Field(default_factory=list, description="Keywords required in title (any match)")
    title_exclude: List[str] = Field(default_factory=list, description="Keywords forbidden in title")
    location_keywords: List[str] = Field(default_factory=list, description="Keywords required in location (any match)")
    location_exclude: List[str] = Field(default_factory=list, description="Keywords forbidden in location")
    max_days_old: Optional[int] = Field(
        default=30, description="Max job age in days. If None or <= 0, no temporal cutoff."
    )
    exclude_inactive: bool = Field(default=True, description="Exclude jobs with inactive URLs or status")

    def get_rejection_reason(self, job: JobOpening) -> Optional[str]:
        """Returns the specific reason why a job was rejected, or None if it matches all criteria."""
        # 1. Reject inactive URLs or status
        if self.exclude_inactive and job.url and "inactive" in str(job.url).lower():
            return f"inactive URL or status: '{job.url}'"

        # 2. Temporal validation
        if self.max_days_old is not None and self.max_days_old > 0 and job.published_at is not None:
            pub_dt = job.published_at
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            else:
                pub_dt = pub_dt.astimezone(timezone.utc)
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=self.max_days_old)
            if pub_dt < cutoff_dt:
                return f"cutoff date '{pub_dt.strftime('%Y-%m-%d')}' < '{cutoff_dt.strftime('%Y-%m-%d')}'"

        # 3. Deterministic title & location keyword matching
        title_lower = job.title.lower()
        location_lower = job.location.lower()

        # Check excluded title keywords
        if self.title_exclude:
            for kw in self.title_exclude:
                if kw.lower() in title_lower:
                    return f"rejected by excluded_keyword: '{kw}' found in title '{job.title}'"

        # Check required title keywords (OR logic among keywords)
        if self.title_keywords:
            if not any(k.lower() in title_lower for k in self.title_keywords):
                return f"rejected by title: '{job.title}' does not match required title_keywords {self.title_keywords}"

        # Check excluded location keywords
        if self.location_exclude:
            for kw in self.location_exclude:
                if kw.lower() in location_lower:
                    return f"rejected by excluded_location: '{kw}' found in location '{job.location}'"

        # Check required location keywords (OR logic among keywords)
        if self.location_keywords:
            loc_matched = any(k.lower() in location_lower for k in self.location_keywords)
            if (
                not loc_matched
                and getattr(job, "modality", None) == "remote"
                and any(rem in k.lower() for k in self.location_keywords for rem in ("remoto", "remote"))
            ):
                loc_matched = True
            if not loc_matched:
                return (
                    f"rejected by location: '{job.location}' does not match location_keywords {self.location_keywords}"
                )

        return None

    def matches(self, job: JobOpening) -> bool:
        """Determines if a job satisfies the filter criteria."""
        return self.get_rejection_reason(job) is None

    def filter_jobs(self, jobs: Iterable[JobOpening]) -> List[JobOpening]:
        """Filters an iterable of jobs, returning those matching criteria."""
        return [job for job in jobs if self.matches(job)]
