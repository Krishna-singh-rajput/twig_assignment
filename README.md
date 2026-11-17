# B2B Market Intelligence Job Data Pipeline

A production-minded Python data pipeline that politely scrapes open job postings across multiple applicant tracking systems and developer forums, filters for Data and Machine Learning Engineering roles in the US or US-remote, extracts structured records with strict non-hallucination guarantees and evidence tracking, deduplicates identical roles across disparate sources, maintains change history across idempotent re-runs, and persists records to SQLite, DuckDB, and CSV.

---

## 1. Architecture Overview

The pipeline is organized into modular, single-responsibility stages:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            1. POLITE SCRAPING                               │
│  - Greenhouse API: stripe, airbnb, databricks, figma                        │
│  - Lever API: palantir, spotify (substituted for 404 plaid)                 │
│  - Hacker News HTML: "Who is hiring?" current monthly thread (item 50338728)│
│  - Controls: Robots.txt checking, <= 1 req/sec per domain, retry backoff    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ RawJobPosting[]
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           2. DOMAIN PRE-FILTERING                           │
│  - Roles: Data Engineer, ML Engineer, Analytics Engineer, Platform Engineer │
│  - Geo: United States or US-Remote (rejects foreign-only postings)          │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Filtered Target Postings
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   3. CONTENT-HASH CACHING & EXTRACTION                      │
│  - SHA-256 payload hashing to prevent redundant LLM extraction              │
│  - Pluggable Extractor: OpenAI (gpt-4o-mini), Gemini, Ollama, or Rule Engine│
│  - Strict Target Schema: Nulls over guesses; exact evidence snippet mapping │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Extracted Canonical Schema
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    4. CROSS-SOURCE DEDUPLICATION & MERGE                    │
│  - Fuzzy & canonical title normalization ("Sr." vs "Senior ..., Platform")   │
│  - Multi-source link merging: retains all source URLs in `source_urls`      │
│  - Reconciles union of skills, evidence snippets, and salary ranges         │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Deduplicated Canonical Records
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  5. IDEMPOTENT PERSISTENCE & CHANGE AUDITING                │
│  - SQLite (`data/postings.db`): Zero duplicates across repeated runs        │
│  - Audit Trail (`change_history` table): Salary, location, status mutations │
│  - Closure Detection: Disappearing postings marked as status='closed'      │
│  - Exports: CSV (`output/job_postings.csv`), DuckDB, and JSON               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Quickstart & One-Command Run

### Setup Environment
```bash
# 1. Clone repository and navigate to folder
git clone <repository_url>
cd <project_dir>

# 2. Install dependencies (Python 3.10+)
pip install -r requirements.txt

# 3. Create .env file (optional if using rule extractor; add OPENAI_API_KEY for LLM)
cp .env.example .env
```

### Run the Pipeline
```bash
# Execute the complete pipeline across all 3 sources
python -m pipeline run

# Or using Makefile
make run

# Or with Docker
docker compose up --build
```

### Run Benchmark Evaluation
To evaluate extraction accuracy against the 20 hand-labeled postings:
```bash
python -m pipeline evaluate
# or
make evaluate
```

### Run Automated Tests
```bash
python -m pytest -v
# or
make test
```

---

## 3. Benchmark Results & LLM Cost (20-Posting Labeled Set)

The benchmark dataset (`data/labeled_ground_truth.json`) contains **20 hand-labeled postings** (11 from Hacker News "Who is hiring?", 5 from Greenhouse, 4 from Lever).

### Field-Level Extraction Accuracy:
```
==================================================================
          FIELD-LEVEL EXTRACTION ACCURACY & COST REPORT           
==================================================================
Total Benchmark Postings: 20 (Hacker News: 11, ATS Boards: 9)
Average Extraction Accuracy: 94.17%
Evidence Validity (Non-hallucination): 99.59%
Average LLM Cost Per Posting: $0.000000 (Rule) / $0.000185 (GPT-4o-mini)
Average Latency Per Posting: 0.001s
------------------------------------------------------------------
Field                | Evaluated  | Correct  | Accuracy  
------------------------------------------------------------------
city                 | 20         | 18       | 90.0%
company              | 20         | 20       | 100.0%
country              | 20         | 18       | 90.0%
currency             | 20         | 19       | 95.0%
employment_type      | 20         | 16       | 80.0%
remote_policy        | 20         | 18       | 90.0%
salary_max           | 20         | 19       | 95.0%
salary_min           | 20         | 19       | 95.0%
seniority            | 20         | 20       | 100.0%
skills               | 20         | 20       | 100.0%
title                | 20         | 19       | 95.0%
visa_sponsorship     | 20         | 20       | 100.0%
==================================================================
```

### Cost Per Posting Analysis:
- When using **pre-filtering** and pruned contextual prompts (intro + compensation section, max 800 tokens):
  - **Prompt Tokens**: ~480 tokens per posting.
  - **Completion Tokens**: ~120 tokens per posting.
  - **Unit Cost on GPT-4o-mini** ($0.15/1M in, $0.60/1M out): **$0.000144 per posting** (< 1/50th of a cent).
  - Processing 300 postings costs **~$0.043** total, well within the $20 reimbursement limit.
- When using the high-precision **Deterministic Rule Extractor** (default):
  - **Unit Cost**: **$0.000000** (zero API dependency, deterministic, 1ms latency).

---

## 4. Key Design Decisions & Trade-Offs

1. **Pre-Filtering Before LLM Extraction**:
   - *Decision*: We filter raw titles and opening paragraphs using regex patterns before invoking any LLM.
   - *Trade-off*: A tiny fraction of poorly titled postings might be dropped, but this reduces LLM token expenses by **98%** (filtering 2,600 raw jobs down to ~50 target roles).
2. **Deterministic Hashing for Idempotency**:
   - *Decision*: Every raw job payload is hashed with SHA-256 and indexed in `raw_cache`. Re-running the pipeline checks this hash before parsing.
   - *Trade-off*: Consumes minor disk space in SQLite, but guarantees zero redundant extraction calls on re-runs.
3. **Canonical Merging vs Strict Splitting**:
   - *Decision*: Two postings merge only if company matches, core engineering category matches, and location is compatible.
   - *Trade-off*: Prevents erroneous merging of different roles (e.g. "Data Engineer" vs "ML Engineer" at Stripe remain distinct), while unifying synonymous titles ("Sr. Data Engineer" and "Senior Data Engineer, Platform").
4. **SQLite + DuckDB Dual Storage**:
   - *Decision*: SQLite provides ACID transactional storage and audit history; DuckDB provides fast columnar queries and analytical exports.

---

## 5. What Breaks First (Failure Modes)

1. **Hacker News Unstructured Format Drift**:
   - HN comments are written by arbitrary humans with zero schema enforcement. If a recruiter uses non-standard delimiters (e.g. slashes without spaces, emojis, or skips the company name entirely), header hint extraction will fall back to body text classification.
2. **ATS Anti-Scraping & Rate Limiting**:
   - Greenhouse and Lever occasionally introduce Cloudflare challenges or 429 rate limit walls if scraped concurrently. Our `DomainRateLimiter` enforces `<= 1 req/sec`, but distributed IP rotation would be necessary at enterprise scale.
3. **ATS Board Migration (e.g., Plaid 404)**:
   - Companies frequently switch ATS providers (e.g. Plaid migrated off Lever, returning HTTP 404). As permitted by the assignment specification, we handled 404 without crashing and included `spotify` on Lever to provide rich Lever data.

---

## 6. Scaling to 5,000 Sources Refreshed Weekly at Sensible Cost

To scale this pipeline to **5,000 company career sources refreshed every 7 days**, we design for cost-efficiency and horizontal parallelism:

### Architecture & Work Partitioning:
1. **Lightweight Head-Check & Content Hashing**:
   - Before downloading full job descriptions, send lightweight `HEAD` requests or scrape top-level job lists (JSON API endpoints or sitemaps).
   - Compute SHA-256 hashes of the listing manifests. If a company's job list hash hasn't changed since last week, skip all job detail downloads entirely (**~70-80% skip rate weekly**).
2. **Asynchronous Politeness & Distributed Rate Limiting**:
   - 5,000 domains at 1 request/second cannot be scraped serially in a single thread (would take 5,000+ seconds).
   - Use an `asyncio` or Celery task queue with a Redis-backed token bucket keyed by domain (`ratelimit:{domain}`). 50 worker processes can scrape 5,000 distinct domains concurrently in **under 15 minutes** while never violating the 1 req/sec limit per individual domain.
3. **Weekly LLM Token Cost Calculation**:
   - **Total open postings across 5,000 tech companies**: ~150,000 postings.
   - **Data/ML Engineering target filter (US/Remote)**: ~4% = 6,000 relevant postings.
   - **Weekly churn rate (new or modified postings)**: ~15% = 900 postings requiring extraction per week.
   - **Cost on GPT-4o-mini**:
     - 900 postings × 600 tokens × $0.25/1M tokens avg = **$0.135 per week ($0.54 / month)**!
   - Even without caching, running all 6,000 postings weekly would cost **~$0.90 per week ($3.60 / month)**.

---

## 7. Notes on Deliverables & AI Assistance

- **Source B (Lever)**: Plaid migrated away from Lever and returns HTTP 404. As instructed in the specification (*"If a board token returns no jobs, swap in another company on the same ATS and note it in your README"*), we added Spotify on Lever while gracefully handling Plaid's 404.
- **AI Tool Usage**:
  - Gemini 3.8 Flash was used for architectural analysis, regex synthesis for messy HN formatting, and authoring unit tests.
