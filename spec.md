# Job Hunter ATS - Main Specification

## Overview

The Job Hunter ATS is an asynchronous crawler engineered to monitor Applicant Tracking Systems (ATS) and public job portals (Greenhouse, Lever, Gupy, and Solides), normalize raw postings into validated Pydantic models, apply deterministic eligibility filters, persist findings to Supabase (or SQLite fallback) with semantic deduplication, and dispatch instant notifications (e.g., via Telegram).

---

## Active Specifications Registry

1. **[001 - ATS Crawler Core](specs/001-ats-crawler-core.md)**: Core async engine for Greenhouse and Lever, SQLite storage, filtering, and notifications.
2. **[002 - Gupy Collector Adapter](specs/002-gupy-collector.md)**: Public portal API integration for Gupy company portals.
3. **[003 - Gupy Global Discovery](specs/003-gupy-global-discovery.md)**: Global keyword search on Gupy portal without fixed company boards.
4. **[004 - Supabase Storage Adapter](specs/004-supabase-storage-adapter.md)**: Ephemeral cloud PostgreSQL persistence with semantic deduplication (`dedup_key`) and dynamic `search_configs`.
5. **[005 - Solides Collector Adapter](specs/005-solides-collector.md)**: Native public portal integration for Solides vacancies API (`https://vagas.solides.com.br/api/vacancies`) with automated pagination, defensive normalization, and rate limiting.

---

## Feature 005: Solides Collector Adapter Summary

### Endpoint & Query
- **URL**: `GET https://vagas.solides.com.br/api/vacancies`
- **Pagination**: Iterates `page` from `1` up to `totalPages`, `take=20`.
- **Search Parameters**: `title` extracted dynamically from search configurations or target query; `locations` defaults to empty (`""`).
- **Headers**: Emulates standard browser with `User-Agent: Mozilla/5.0...` and `Accept: application/json`.

### Normalization Rules to `JobOpening`
- **ID Resolution**: Raw numeric or string ID converted strictly to `str`. Formatted as `job_id="solides_{id}"` and `source_job_id="{id}"`.
- **Source**: Registered as literal `'solides'`.
- **Canonical URL**: Always `https://vagas.solides.com.br/vaga/{id}`.
- **Company**: Extracted from `companyName` with fallback to `"Solides"`.
- **Modality**:
  - `"remote"`: When `jobType == "remoto"` or `homeOffice is True`.
  - `"hybrid"`: When "hibrid" or "híbrid" is in `jobType`.
  - `"on_site"`: All other values.
- **Location**:
  - `f"{city.name} - {state.code}"` when city and state are present.
  - Fallback to `"Remoto"` when fields are null or empty.
- **Publication Date**: Parsed from `createdAt` into timezone-aware UTC `datetime`.

### Database & Deduplication
- Integrates with `public.jobs` (Supabase) and `seen_jobs` (SQLite).
- Generates deterministic 32-character SHA-256 `dedup_key` to avoid duplicate alerts across runs.
