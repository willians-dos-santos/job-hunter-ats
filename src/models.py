from datetime import datetime
import hashlib
import re
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


def normalize_dedup_text(text: Optional[str]) -> str:
    """Normalizes text by lowercasing, stripping excessive punctuation, and condensing whitespaces."""
    if not text:
        return ""
    lowered = text.lower()
    # Replace non-alphanumeric punctuation and underscores with space
    stripped_punct = re.sub(r"[^\w\s]|_", " ", lowered)
    # Condense multiple whitespaces and strip ends
    return re.sub(r"\s+", " ", stripped_punct).strip()


def generate_dedup_key(
    ats: Union[str, "JobOpening"] = "",
    company: Optional[str] = None,
    title: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """Generates a deterministic 32-char hexadecimal SHA-256 hash for semantic job deduplication."""
    if isinstance(ats, JobOpening):
        raw_ats = ats.ats
        raw_company = ats.company
        raw_title = ats.title
        raw_location = ats.location
    else:
        raw_ats = str(ats or "")
        raw_company = str(company or "")
        raw_title = str(title or "")
        raw_location = location

    # Treat None, whitespace-only, or "N/A" as empty location
    if raw_location is None or str(raw_location).strip().upper() == "N/A":
        norm_location = ""
    else:
        norm_location = normalize_dedup_text(str(raw_location))

    norm_ats = normalize_dedup_text(raw_ats)
    norm_company = normalize_dedup_text(raw_company)
    norm_title = normalize_dedup_text(raw_title)

    composed = f"{norm_ats}|{norm_company}|{norm_title}|{norm_location or ''}"
    return hashlib.sha256(composed.encode("utf-8")).hexdigest()[:32]


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
    dedup_key: Optional[str] = Field(default=None, description="Deterministic 32-char hex hash for semantic deduplication")

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

    @model_validator(mode="after")
    def populate_dedup_key(self) -> "JobOpening":
        if not self.dedup_key:
            self.dedup_key = generate_dedup_key(self)
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

