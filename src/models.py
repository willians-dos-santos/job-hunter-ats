from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class JobOpening(BaseModel):
    """Normalized canonical model for a job opening."""
    job_id: str = Field(..., description="Canonical globally unique ID, e.g. 'greenhouse:acme:12345'")
    source: Literal["greenhouse", "lever", "Gupy", "gupy"] = Field(..., description="Source ATS platform")
    company: str = Field(..., description="Company name or slug")
    title: str = Field(..., description="Job opening title")
    location: str = Field(default="N/A", description="Job location or 'N/A' if unspecified")
    url: str = Field(..., description="Canonical URL to view/apply for the job")
    published_at: Optional[datetime] = Field(default=None, description="Publication timestamp")
    source_job_id: str = Field(default="", description="Platform raw identifier")

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
    source: Literal["greenhouse", "lever", "Gupy", "gupy"] = Field(..., description="Target ATS platform")

    @model_validator(mode="before")
    @classmethod
    def support_slug_alias(cls, values: dict) -> dict:
        if isinstance(values, dict):
            if "name" not in values and "slug" in values:
                values["name"] = values["slug"]
        return values
