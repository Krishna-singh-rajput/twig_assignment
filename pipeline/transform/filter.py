"""Filtering rules for Data/ML Engineering roles located in US or US-Remote."""

from __future__ import annotations

import re
from typing import Optional
from pipeline.models import RawJobPosting


# Target role keywords matching specification:
# "Keep only data engineering and ML engineering roles (data, ML, analytics or platform engineer titles)"
DATA_ML_TITLE_PATTERNS = [
    r"\bdata\s+engineer\b",
    r"\bsenior\s+data\s+engineer\b",
    r"\bstaff\s+data\s+engineer\b",
    r"\bprincipal\s+data\s+engineer\b",
    r"\blead\s+data\s+engineer\b",
    r"\bmachine\s+learning\s+engineer\b",
    r"\bml\s+engineer\b",
    r"\bmlops\s+engineer\b",
    r"\bml\s+platform\b",
    r"\banalytics\s+engineer\b",
    r"\bplatform\s+engineer\b",
    r"\bdata\s+platform\s+engineer\b",
    r"\bdata\s+infrastructure\s+engineer\b",
    r"\bdata\s+pipeline\b",
    r"\bdata\s+architect\b",
    r"\bdata\s+systems\s+engineer\b",
    r"\bdata\s+analytics\s+engineer\b",
    r"\bbig\s+data\s+engineer\b",
    r"\bai\s*/\s*ml\s+engineer\b",
    r"\bapplied\s+machine\s+learning\b",
]

# Explicit exclusions for titles that are not data/ML engineering
EXCLUDE_TITLE_PATTERNS = [
    r"\bfrontend\b",
    r"\bfront-end\b",
    r"\bios\s+engineer\b",
    r"\bandroid\s+engineer\b",
    r"\bsales\b",
    r"\brecruiter\b",
    r"\bmarketing\b",
    r"\baccount\s+executive\b",
    r"\bcustomer\s+success\b",
    r"\bproduct\s+manager\b",
    r"\bdesign\s+engineer\b",
    r"\bhardware\s+engineer\b",
    r"\bfirmware\s+engineer\b",
    r"\bmechanical\s+engineer\b",
    r"\bsilicon\b",
]

# US locations / terms
US_LOCATION_PATTERNS = [
    r"\bunited\s+states\b",
    r"\bus\b",
    r"\busa\b",
    r"\bus-remote\b",
    r"\bremote\s*\(?us\)?\b",
    r"\bremote\s*-\s*us\b",
    r"\bremote\s*,\s*us\b",
    r"\bremote\s*\(?north\s+america\)?\b",
    r"\bnorth\s+america\b",
    r"\bsan\s+francisco\b",
    r"\bsf\b",
    r"\bnew\s+york\b",
    r"\bnyc\b",
    r"\bseattle\b",
    r"\baustin\b",
    r"\bbay\s+area\b",
    r"\bboston\b",
    r"\bchicago\b",
    r"\blos\s+angeles\b",
    r"\bla\b",
    r"\bdenver\b",
    r"\bcolorado\b",
    r"\bcalifornia\b",
    r"\bwashington\b",
    r"\btexas\b",
    r"\bflorida\b",
    r"\bvirginia\b",
    r"\bgeorgia\b",
    r"\batlanta\b",
    r"\bportland\b",
    r"\bsan\s+jose\b",
    r"\bsan\s+diego\b",
    r"\bsunnyvale\b",
    r"\bmountain\s+view\b",
    r"\bpalo\s+alto\b",
    r"\bcambridge\b",
    r"\bbrooklyn\b",
    r"\bmanhattan\b",
    r"\bca\b",
    r"\bny\b",
    r"\bwa\b",
    r"\btx\b",
    r"\bil\b",
    r"\bco\b",
    r"\bma\b",
]

# Explicit foreign locations to reject if NOT stated as US or Global remote
EXCLUDE_LOCATION_PATTERNS = [
    r"\blondon\b",
    r"\bunited\s+kingdom\b",
    r"\buk\b",
    r"\bengland\b",
    r"\bgermany\b",
    r"\bberlin\b",
    r"\bmunich\b",
    r"\bfrance\b",
    r"\bparis\b",
    r"\bamsterdam\b",
    r"\bnetherlands\b",
    r"\bireland\b",
    r"\bdublin\b",
    r"\bjapan\b",
    r"\btokyo\b",
    r"\bsingapore\b",
    r"\bindia\b",
    r"\bbangalore\b",
    r"\bbengaluru\b",
    r"\bhyderabad\b",
    r"\baustralia\b",
    r"\bsydney\b",
    r"\bmelbourne\b",
    r"\bsweden\b",
    r"\bstockholm\b",
    r"\bpoland\b",
    r"\bwarsaw\b",
    r"\bspain\b",
    r"\bmadrid\b",
    r"\bbarcelona\b",
    r"\bswitzerland\b",
    r"\bzurich\b",
    r"\bbrazil\b",
    r"\bsao\s+paulo\b",
    r"\bcanada\b",
    r"\btoronto\b",
    r"\bvancouver\b",
    r"\bmontreal\b",
    r"\bsaudi\s+arabia\b",
    r"\bkhobar\b",
    r"\briyadh\b",
    r"\buae\b",
    r"\bdubai\b",
    r"\babu\s+dhabi\b",
    r"\bisrael\b",
    r"\btel\s+aviv\b",
    r"\bchina\b",
    r"\bbeijing\b",
    r"\bshanghai\b",
    r"\bmexico\b",
]


class JobFilter:
    """Filters raw postings to ensure they meet domain criteria:
    1. Data or ML engineering role
    2. Located in the US or US-remote
    """

    @classmethod
    def is_target_role(cls, title: str, body_snippet: str = "") -> bool:
        """Check if job title matches data/ML engineering domains."""
        title_lower = title.lower()

        # Check explicit exclusions first
        for pat in EXCLUDE_TITLE_PATTERNS:
            if re.search(pat, title_lower):
                return False

        # Check positive title patterns
        for pat in DATA_ML_TITLE_PATTERNS:
            if re.search(pat, title_lower):
                return True

        # For Hacker News or unstructured text, title might be generic e.g. "Software Engineer"
        # but body clearly states "Software Engineer - Data Platform" or "Role: Data Engineer"
        combined_text = f"{title_lower}\n{body_snippet.lower()[:800]}"
        for pat in DATA_ML_TITLE_PATTERNS:
            if re.search(pat, combined_text):
                return True

        return False

    @classmethod
    def is_us_or_remote(cls, location_str: Optional[str], body_snippet: str = "") -> bool:
        """Check if location is US or US-Remote."""
        loc = (location_str or "").lower().strip()
        body = (body_snippet or "").lower()[:800]
        combined = f"{loc} | {body}"

        # If location explicitly has US terms
        for pat in US_LOCATION_PATTERNS:
            if re.search(pat, loc):
                return True

        # Check for remote indicators with US
        if "remote" in loc or "remote" in body:
            # Check if any explicit foreign country without US mention
            is_foreign = False
            for f_pat in EXCLUDE_LOCATION_PATTERNS:
                if re.search(f_pat, loc):
                    is_foreign = True
                    break
            if not is_foreign:
                # If it's remote and doesn't state Europe/UK/APAC only, assume US eligible or US company
                return True

        # If location has US city/state patterns in combined text
        for pat in US_LOCATION_PATTERNS:
            if re.search(pat, combined):
                # Ensure it's not disqualified by being solely located in another country
                for f_pat in EXCLUDE_LOCATION_PATTERNS:
                    if re.search(f_pat, loc) and not any(re.search(u_pat, loc) for u_pat in US_LOCATION_PATTERNS):
                        return False
                return True

        return False

    @classmethod
    def should_keep(cls, posting: RawJobPosting) -> bool:
        """Determine if a raw posting passes all filter criteria."""
        if not cls.is_target_role(posting.title_raw, posting.body_raw[:800]):
            return False

        if not cls.is_us_or_remote(posting.location_raw, posting.body_raw[:800]):
            return False

        return True
