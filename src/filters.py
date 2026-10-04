from typing import Iterable, List
from pydantic import BaseModel, Field
from src.models import JobOpening


class JobFilter(BaseModel):
    """Deterministic filter criteria for job openings."""

    title_keywords: List[str] = Field(default_factory=list, description="Keywords required in title (any match)")
    title_exclude: List[str] = Field(default_factory=list, description="Keywords forbidden in title")
    location_keywords: List[str] = Field(default_factory=list, description="Keywords required in location (any match)")
    location_exclude: List[str] = Field(default_factory=list, description="Keywords forbidden in location")

    def matches(self, job: JobOpening) -> bool:
        """Determines if a job satisfies the filter criteria."""
        title_lower = job.title.lower()
        location_lower = job.location.lower()

        # Check required title keywords (OR logic among keywords)
        if self.title_keywords:
            if not any(k.lower() in title_lower for k in self.title_keywords):
                return False

        # Check excluded title keywords
        if self.title_exclude:
            if any(k.lower() in title_lower for k in self.title_exclude):
                return False

        # Check required location keywords (OR logic among keywords)
        if self.location_keywords:
            if not any(k.lower() in location_lower for k in self.location_keywords):
                return False

        # Check excluded location keywords
        if self.location_exclude:
            if any(k.lower() in location_lower for k in self.location_exclude):
                return False

        return True

    def filter_jobs(self, jobs: Iterable[JobOpening]) -> List[JobOpening]:
        """Filters an iterable of jobs, returning those matching criteria."""
        return [job for job in jobs if self.matches(job)]
