from datetime import datetime
import re
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class JobOpening(BaseModel):
    """Normalized canonical model for a job opening."""
    job_id: str = Field(..., description="Canonical globally unique ID, e.g. 'greenhouse:acme:12345'")
    source: Literal["greenhouse", "lever", "Gupy", "gupy", "gupy_global"] = Field(..., description="Source ATS platform")
    company: str = Field(..., description="Company name or slug")
    title: str = Field(..., description="Job opening title")
    location: str = Field(default="N/A", description="Job location or 'N/A' if unspecified")
    url: str = Field(..., description="Canonical URL to view/apply for the job")
    published_at: Optional[datetime] = Field(default=None, description="Publication timestamp")
    source_job_id: str = Field(default="", description="Platform raw identifier")

    @model_validator(mode="before")
    @classmethod
    def support_aliases(cls, values: dict) -> dict:
        if isinstance(values, dict):
            if "job_id" not in values and "id" in values:
                values["job_id"] = values["id"]
            if "source" not in values and "ats" in values:
                values["source"] = values["ats"]
            if "source_job_id" not in values and "external_id" in values:
                values["source_job_id"] = values["external_id"]
        return values

    @property
    def id(self) -> str:
        return self.job_id

    @property
    def ats(self) -> str:
        return self.source

    @property
    def external_id(self) -> str:
        return self.source_job_id

    @field_validator("location", mode="before")
    @classmethod
    def normalize_location(cls, v: Optional[str]) -> str:
        if v is None:
            return "N/A"
        stripped = str(v).strip()
        return stripped if stripped else "N/A"

    @model_validator(mode="after")
    def populate_source_job_id(self) -> "JobOpening":
        if not self.source_job_id:
            # Fallback to the suffix of job_id if formatted like source:company:id
            parts = self.job_id.split(":")
            self.source_job_id = parts[-1] if len(parts) > 1 else self.job_id
        return self

class TargetCompany(BaseModel):
    """Target company ATS configuration."""
    name: str = Field(..., description="Company name or slug")
    source: Literal["greenhouse", "lever", "Gupy", "gupy", "gupy_global"] = Field(..., description="Target ATS platform")
    slug: Optional[str] = Field(default=None, description="Explicit slug identifier")
    query: Optional[str] = Field(default=None, description="Search term for global discovery")

    @property
    def search_query(self) -> str:
        """Returns query or falls back to name as search term."""
        return self.query or self.name

    @model_validator(mode="before")
    @classmethod
    def support_slug_alias(cls, values: dict) -> dict:
        if isinstance(values, dict):
            if "name" not in values and "slug" in values:
                values["name"] = values["slug"]
            if "slug" not in values and "name" in values:
                values["slug"] = values["name"]
        return values

    @property
    def clean_slug(self) -> str:
        """Returns a sanitized slug (lowercase, no spaces, alphanumeric and hyphens only)."""
        raw = (self.slug or self.name).strip().lower()
        cleaned = re.sub(r"[^a-z0-9-]", "", raw.replace(" ", "-").replace("_", "-"))
        return re.sub(r"-+", "-", cleaned).strip("-")

