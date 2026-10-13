# Database Schema Specification

This document details the database schema and persistence contracts for the Job Hunter ATS platform, supporting SQLite (local development and fallback) and Supabase PostgreSQL (cloud ephemeral execution).

---

## 1. Supabase PostgreSQL Schema

### 1.1 Table: `public.jobs`

Stores discovered job vacancies with semantic deduplication and idempotent upserting.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `TEXT` | `PRIMARY KEY` | Canonical composite identifier (`{ats}:{external_id}` or `solides_{id}`) |
| `ats` | `TEXT` | `NOT NULL` | Source platform (`greenhouse`, `lever`, `gupy`, `solides`) |
| `external_id` | `TEXT` | `NOT NULL` | Raw platform identifier from source API |
| `title` | `TEXT` | `NOT NULL` | Job opening title |
| `company` | `TEXT` | `NOT NULL` | Company or organization name |
| `location` | `TEXT` | `NULLABLE` | Normalized location string or null |
| `url` | `TEXT` | `NOT NULL` | Public canonical application URL |
| `published_at` | `TIMESTAMPTZ` | `NULLABLE` | ISO 8601 publication timestamp |
| `created_at` | `TIMESTAMPTZ` | `DEFAULT NOW()` | Record insertion timestamp |
| `dedup_key` | `TEXT` | `UNIQUE` | 32-character SHA-256 hash for semantic deduplication |

#### Semantic Deduplication: `dedup_key`
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedup_key ON public.jobs (dedup_key);
```
Generated via `generate_dedup_key(ats, company, title, location)`:
- Normalized lowercase strings without punctuation.
- Ensures duplicate postings under different IDs across runs are detected.

---

### 1.2 Table: `public.search_configs`

Configures dynamic search keywords, excluded terms, locations, and targets.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | `PRIMARY KEY DEFAULT gen_random_uuid()` | Config entry identifier |
| `user_id` | `UUID` | `NULLABLE` | Scoped user identifier for multi-tenant configurations |
| `category` | `TEXT` | `NOT NULL` | Category: `keyword`, `excluded_keyword`, `location`, `company`, `ats_filter` |
| `value` | `TEXT` | `NOT NULL` | Search term or target value |
| `metadata` | `JSONB` | `DEFAULT '{}'::jsonb` | Additional options (e.g. `{"source": "solides"}`, `{"query": "Python"}`) |
| `is_active` | `BOOLEAN` | `DEFAULT TRUE` | Activation toggle |
| `created_at` | `TIMESTAMPTZ` | `DEFAULT NOW()` | Creation timestamp |

---

## 2. SQLite Local Fallback Schema

### 2.1 Table: `seen_jobs`

Used when running locally or when Supabase credentials are not present.

```sql
CREATE TABLE IF NOT EXISTS seen_jobs (
    job_id TEXT PRIMARY KEY,
    source TEXT,
    company TEXT,
    title TEXT,
    url TEXT,
    location TEXT,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dedup_key TEXT
);
```

---

## 3. Integration with Solides Collector

When jobs are collected from Solides:
- `job_id`: Format `solides_{id}` (e.g., `solides_936455`).
- `source`: Literal `'solides'`.
- `company`: `item.companyName` or `"Solides"`.
- `location`: Normalized `f"{city.name} - {state.code}"` or `"Remoto"`.
- `url`: Canonical URL `https://vagas.solides.com.br/vaga/{id}`.
- `published_at`: Parsed from `createdAt` in UTC.
- `dedup_key`: Deterministic hash derived from normalized attributes.
- Upsert target: `public.jobs` with `on_conflict="dedup_key"`.
