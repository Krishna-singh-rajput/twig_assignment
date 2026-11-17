"""Prompt templates for LLM structured extraction with strict evidence requirements."""

EXTRACTION_SYSTEM_PROMPT = """You are an expert Data Engineering recruitment data extraction system.
Your job is to extract structured job posting attributes from free-text job postings into a strictly valid JSON object.

CRITICAL RULES:
1. NULL OVER GUESSES: If a field is NOT explicitly stated in the posting text, you MUST output null (or empty list for skills). NEVER invent, guess, or assume values.
2. EVIDENCE REQUIRED: For EVERY non-null extracted field, you MUST provide the exact substring from the posting text under the "evidence" object.
3. SALARIES:
   - Only extract base or total target compensation if explicitly stated with numbers.
   - If an hourly rate is stated, convert to annualized salary (rate * 2080).
   - If a range is stated, populate both salary_min and salary_max.
   - If a single number is stated, populate both salary_min and salary_max with that number.
   - If no numbers are stated, salary_min and salary_max MUST be null.
4. SENIORITY: Must be one of ["junior", "mid", "senior", "staff_plus"] or null.
   - junior: Junior, Jr, Associate, Entry Level, Intern
   - mid: Mid-level, Level II, or standard engineer without senior markers
   - senior: Senior, Sr, Lead, Principal I, Level III
   - staff_plus: Staff, Principal, Distinguished, Director, VP
5. REMOTE POLICY: Must be one of ["onsite", "hybrid", "remote"] or null.
6. EMPLOYMENT TYPE: Must be one of ["full_time", "contract", "intern"] or null.
7. VISA SPONSORSHIP: Boolean (true/false) ONLY if explicitly stated (e.g. "We sponsor H1B" -> true, "No visa sponsorship available" -> false). If not mentioned, MUST BE null.
8. OUTPUT FORMAT: Respond ONLY with a valid JSON object matching the requested schema. No markdown formatting or extra text outside the JSON.
"""

EXTRACTION_USER_PROMPT_TEMPLATE = """Extract structured data from the following job posting.

COMPANY HINT: {company_hint}
SOURCE TITLE HINT: {title_hint}
LOCATION HINT: {location_hint}

JOB POSTING TEXT:
\"\"\"
{text}
\"\"\"

Expected JSON Schema:
{{
  "company": "string (canonical company name)",
  "title": "string (canonical job title)",
  "seniority": "junior" | "mid" | "senior" | "staff_plus" | null,
  "city": "string or null",
  "country": "string or null",
  "remote_policy": "onsite" | "hybrid" | "remote" | null,
  "salary_min": number or null,
  "salary_max": number or null,
  "currency": "USD" | "EUR" | "GBP" | string or null,
  "employment_type": "full_time" | "contract" | "intern" | null,
  "skills": ["string", ...],
  "visa_sponsorship": boolean or null,
  "posted_date": "YYYY-MM-DD" or null,
  "evidence": {{
    "company": "exact source snippet",
    "title": "exact source snippet",
    "seniority": "exact source snippet or null",
    "city": "exact source snippet or null",
    "country": "exact source snippet or null",
    "remote_policy": "exact source snippet or null",
    "salary_min": "exact source snippet or null",
    "salary_max": "exact source snippet or null",
    "skills": "exact source snippet or null",
    "visa_sponsorship": "exact source snippet or null"
  }}
}}
"""
