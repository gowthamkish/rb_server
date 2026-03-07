"""
Comprehensive resume text parser.

Accepts raw plain-text extracted from a resume (PDF / DOCX) and returns a
structured dict matching the client-side Resume shape:

  personalInfo  – fullName, email, phone, location, professionalSummary
  experiences   – list of {jobTitle, company, startDate, endDate, currentlyWorking, description}
  education     – list of {school, degree, fieldOfStudy, startDate, endDate, grade}
  skills        – list of {name, level}
"""

from __future__ import annotations

import re
import uuid
from typing import Any

# ────────────────────────────────────────────────────────────────────
# Section heading patterns
# ────────────────────────────────────────────────────────────────────

_SECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "summary": re.compile(
        r"^(?:professional\s+)?(?:summary|profile|about(?:\s+me)?|objective|"
        r"career\s+(?:summary|objective))\s*:?\s*$",
        re.I,
    ),
    "experience": re.compile(
        r"^(?:(?:work|professional|employment|career)\s+)?(?:experience|history)\s*:?\s*$",
        re.I,
    ),
    "education": re.compile(
        r"^(?:education(?:al)?(?:\s+(?:background|qualifications|history))?|"
        r"academic\s+(?:background|qualifications))\s*:?\s*$",
        re.I,
    ),
    "skills": re.compile(
        r"^(?:(?:technical|key|core|professional)?\s*)?skills(?:\s+(?:summary|set))?\s*:?\s*$",
        re.I,
    ),
    "certifications": re.compile(
        r"^(?:certifications?|licenses?|certificates?)\s*:?\s*$",
        re.I,
    ),
    "projects": re.compile(
        r"^(?:(?:personal|academic|notable|key)\s*)?projects?\s*:?\s*$",
        re.I,
    ),
    "languages": re.compile(r"^languages?\s*:?\s*$", re.I),
    "awards": re.compile(r"^(?:awards?|honors?|achievements?)\s*:?\s*$", re.I),
    "references": re.compile(r"^references?\s*:?\s*$", re.I),
    "declaration": re.compile(r"^declaration\s*:?\s*$", re.I),
    "hobbies": re.compile(r"^(?:hobbies|interests?|activities)\s*:?\s*$", re.I),
    # Layout sections common in multi-column / Canva PDFs
    "contacts": re.compile(r"^contacts?\s*:?\s*$", re.I),
    "personal_details": re.compile(r"^personal\s+details?\s*[:\.]?\s*$", re.I),
}

# ────────────────────────────────────────────────────────────────────
# Regex helpers
# ────────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
_PHONE_RE = re.compile(r"(\+?[\d][\d\s\-().]{6,}\d)")
_URL_RE = re.compile(r"(https?://|www\.|github\.com|linkedin\.com|gitlab\.com)", re.I)

_MONTH_NAMES = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE_TOKEN = rf"(?:{_MONTH_NAMES}\.?\s*\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"

_SINGLE_DATE_RE = re.compile(rf"\b({_DATE_TOKEN})\b", re.I)

_DATE_RANGE_RE = re.compile(
    rf"({_DATE_TOKEN})\s*(?:[-–—]|to)\s*({_DATE_TOKEN}|[Pp]resent|[Cc]urrent|[Nn]ow|[Oo]ngoing)",
    re.I,
)

# Pattern: "TITLE | DATE_RANGE" on a single line (Format A)
_TITLE_WITH_DATE_RE = re.compile(
    rf"^(.+?)\s*\|\s*({_DATE_TOKEN})\s*(?:[-–—]|to)\s*({_DATE_TOKEN}|[Pp]resent|[Cc]urrent|[Nn]ow|[Oo]ngoing)\s*$",
    re.I,
)

# Pattern: "School | Degree" (no date range)
_SCHOOL_DEGREE_PIPE_RE = re.compile(
    r"^(.+?)\s*\|\s*([A-Za-z].{3,80})$",
)

_DEGREE_RE = re.compile(
    r"(?:Bachelor(?:'?s)?(?:\s+of\s+(?:Engineering|Science|Arts|Technology|Commerce|Law|Medicine|Education|Fine\s+Arts))?|"
    r"B\.?\s?[A-Z]\.?(?:[A-Za-z\.]+)?|"
    r"Master(?:'?s)?(?:\s+of\s+(?:Engineering|Science|Arts|Technology|Commerce|Law|Business\s+Administration))?|"
    r"M\.?\s?[A-Z]\.?(?:[A-Za-z\.]+)?|"
    r"Doctor(?:ate)?|Ph\.?\s?D\.?|Associate(?:'?s)?|Diploma|"
    r"B\.?Com\.?|M\.?Com\.?|B\.?Sc\.?|M\.?Sc\.?|B\.?C\.?A\.?|M\.?C\.?A\.?|"
    r"B\.?E\.?|M\.?E\.?|B\.?Tech\.?|M\.?Tech\.?|M\.?B\.?A\.?)",
    re.I,
)

_GPA_RE = re.compile(
    r"(?:GPA|CGPA|Grade|Percentage|Score)\s*:?\s*([\d.]+(?:\s*[/%]\s*[\d.]+)?)",
    re.I,
)

_BULLET_RE = re.compile(
    r"^[\u2022\u2023\u25E6\u2043\u2022\u25CF\u25CB\u25E6\u25AA\u25B8\u25BA\-\*•●○◦▪▸►–]\s*"
)
_SKILL_CATEGORY_RE = re.compile(r"^([A-Za-z][A-Za-z &/]+?)\s*:\s*(.*)$")
_SKILL_LEVEL_RE = re.compile(
    r"\b(beginner|intermediate|advanced|expert|proficient|familiar)\b", re.I
)
_LEVEL_MAP: dict[str, str] = {
    "beginner": "Beginner",
    "familiar": "Beginner",
    "intermediate": "Intermediate",
    "proficient": "Intermediate",
    "advanced": "Advanced",
    "expert": "Expert",
}

_TITLE_WORDS_RE = re.compile(
    r"\b(?:engineer|developer|manager|analyst|designer|consultant|lead|"
    r"intern|architect|director|specialist|coordinator|administrator|"
    r"executive|officer|associate|assistant|senior|junior|sr\.?|jr\.?|"
    r"head|vp|vice\s*president|chief|cto|ceo|cfo|coo|frontend|backend|"
    r"fullstack|full\s*stack|devops|qa|sdet|tester|programmer|scientist|"
    r"technologist|strategist|advisor)\b",
    re.I,
)

# Lines that are known template/garbage noise
_NOISE_LINE_RE = re.compile(
    r"^(?:declaration|i hereby|belief\.?|"
    r"university/college details?|course studied?|"
    r"personal details?\s*:?\s*|"
    r"responsibilities?\s*:?\s*$)\s*$",
    re.I,
)

# Personal-detail field extractors
_FIRST_NAME_RE = re.compile(r"^first\s+name\s*[:\.]?\s*(.+)$", re.I)
_LAST_NAME_RE = re.compile(r"^last\s+name\s*[:\.]?\s*(.+)$", re.I)
_RESIDENCE_RE = re.compile(r"^(?:residence|address|location|city)\s*[:\.]?\s*(.+)$", re.I)
_DOB_RE = re.compile(r"^date\s+of\s+birth\s*[:\.]?\s*(.+)$", re.I)


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _clean_bullet(text: str) -> str:
    return _BULLET_RE.sub("", text).strip()


def _normalise_date(date_str: str) -> str:
    """
    Convert various date formats into ISO-ish YYYY-MM-DD for front-end
    DatePicker compatibility.

    Handles:
      "Jan 2025"        → "2025-01-01"
      "January 2025"    → "2025-01-01"
      "May 2022"        → "2022-05-01"
      "05/2024"         → "2024-05-01"
      "2012"            → "2012-01-01"
      "July 2018"       → "2018-07-01"
    """
    raw = date_str.strip()
    if not raw:
        return ""

    _MONTH_MAP = {
        "jan": "01", "january": "01",
        "feb": "02", "february": "02",
        "mar": "03", "march": "03",
        "apr": "04", "april": "04",
        "may": "05",
        "jun": "06", "june": "06",
        "jul": "07", "july": "07",
        "aug": "08", "august": "08",
        "sep": "09", "sept": "09", "september": "09",
        "oct": "10", "october": "10",
        "nov": "11", "november": "11",
        "dec": "12", "december": "12",
    }

    # "Jan 2025", "January 2025", "Jan. 2025"
    m = re.match(r"^([A-Za-z]+)\.?\s+(\d{4})$", raw)
    if m:
        month_str = m.group(1).lower()
        month_num = _MONTH_MAP.get(month_str, "01")
        return f"{m.group(2)}-{month_num}-01"

    # "05/2024", "5/2024"
    m = re.match(r"^(\d{1,2})/(\d{4})$", raw)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}-01"

    # Pure year "2012"
    m = re.match(r"^(\d{4})$", raw)
    if m:
        return f"{m.group(1)}-01-01"

    # Already ISO-like "2025-01-01"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw

    return raw


# ────────────────────────────────────────────────────────────────────
# Section splitter
# ────────────────────────────────────────────────────────────────────


def _split_sections(text: str) -> dict[str, list[str]]:
    """
    Walk through lines and bucket them into named sections.
    Lines before any recognised heading go into "header".
    Multi-column PDFs (Canva etc.) produce lines out of logical order;
    we accumulate ALL lines under their matched section regardless of
    where they physically appear.
    """
    lines = text.split("\n")
    sections: dict[str, list[str]] = {"header": []}
    current = "header"

    for raw_line in lines:
        line = raw_line.strip()
        matched_section: str | None = None
        for name, pattern in _SECTION_PATTERNS.items():
            if pattern.match(line):
                matched_section = name
                break
        if matched_section:
            current = matched_section
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)

    return sections


# ────────────────────────────────────────────────────────────────────
# Personal info
# ────────────────────────────────────────────────────────────────────


def _extract_personal_info(
    header_lines: list[str],
    full_text: str,
    contacts_lines: list[str] | None = None,
    personal_details_lines: list[str] | None = None,
) -> dict[str, str]:
    email = ""
    phone = ""
    full_name = ""
    location = ""
    address_parts: list[str] = []

    # Grab first email / phone from entire document
    em = _EMAIL_RE.search(full_text)
    if em:
        email = em.group(0)

    ph = _PHONE_RE.search(full_text)
    if ph:
        raw_ph = ph.group(0).strip()
        # Ignore template placeholder numbers (e.g. "+123-456-7890")
        if not re.match(r"^\+?123[-\s]", raw_ph):
            phone = raw_ph

    # ── Priority 1: structured "PERSONAL DETAILS" section ──────────────
    if personal_details_lines:
        first_name = ""
        last_name = ""
        address_parts.clear()
        collecting_address = False
        _PD_KEY_RE = re.compile(
            r"^(?:first|last|middle)\s+name|date\s+of\s+birth|languages?|residence|address|city|nationality|gender",
            re.I,
        )
        for line in personal_details_lines:
            line = line.strip()
            if not line:
                collecting_address = False
                continue
            if _PD_KEY_RE.match(line):
                collecting_address = False
                fn_m = _FIRST_NAME_RE.match(line)
                if fn_m:
                    first_name = fn_m.group(1).strip()
                    continue
                ln_m = _LAST_NAME_RE.match(line)
                if ln_m:
                    last_name = ln_m.group(1).strip()
                    continue
                res_m = _RESIDENCE_RE.match(line)
                if res_m:
                    address_parts = [res_m.group(1).strip()]
                    collecting_address = True
                    continue
            elif collecting_address:
                address_parts.append(line)
        # Extract city from accumulated address parts
        if address_parts and not location:
            addr_tokens = [p.strip().rstrip(",") for p in ", ".join(address_parts).split(",")]
            for part in addr_tokens:
                part = part.strip()
                if not part:
                    continue
                # Skip house/plot numbers
                if re.match(r"^\d", part):
                    continue
                # Skip street-type words
                if re.search(r"\b(?:street|road|nagar|colony|lane|cross|main|block|plot|flat|apt)", part, re.I):
                    continue
                # Skip postal codes (all digits / dashes)
                if re.match(r"^[\d\s–—\-]+$", part):
                    continue
                location = part
                break
        if first_name or last_name:
            full_name = (first_name + " " + last_name).strip()

    # ── Priority 2: contacts section (Canva 2-col: name appears here) ──
    if not full_name and contacts_lines:
        for line in (contacts_lines or [])[:10]:
            if not line:
                continue
            clean = _BULLET_RE.sub("", line).strip()
            if not clean:
                continue
            # Skip contact info lines
            if _EMAIL_RE.search(clean) or _PHONE_RE.search(clean) or _URL_RE.search(clean):
                continue
            # Skip job title / experience lines (have | with title words or multiple pipes)
            if "|" in clean:
                continue
            # Skip date lines
            if _DATE_RANGE_RE.search(clean) or _SINGLE_DATE_RE.search(clean):
                continue
            # Skip section headings
            if any(p.match(clean) for p in _SECTION_PATTERNS.values()):
                continue
            # A name: 1–4 words, mostly letters, reasonably short
            if re.match(r"^[A-Za-z .'\-]{2,50}$", clean) and 1 <= len(clean.split()) <= 4:
                full_name = clean
                break

    # ── Priority 3: header lines ────────────────────────────────────────
    if not full_name:
        cleaned_header: list[str] = []
        for line in header_lines:
            if "|" in line and (
                (email and email in line)
                or (phone and phone.replace("+", "").replace(" ", "") in line.replace(" ", ""))
            ):
                # Contact line – try to pull location from it
                parts = [p.strip() for p in line.split("|")]
                for part in parts:
                    if email and email in part:
                        continue
                    if phone and phone.replace("+", "").replace(" ", "") in part.replace(" ", ""):
                        continue
                    if re.search(r"\d{4,6}", part):
                        loc_candidate = re.sub(r"\d{4,6}", "", part).strip().strip(",").strip()
                        if loc_candidate:
                            location = loc_candidate
                        else:
                            location = part.strip()
                    elif re.match(r"[A-Za-z ]+,\s*[A-Za-z ]+", part):
                        location = part.strip()
            else:
                cleaned_header.append(line)

        for line in cleaned_header[:5] + header_lines[:5]:
            if not line:
                continue
            if email and email in line:
                continue
            clean = _BULLET_RE.sub("", line).strip()
            if _URL_RE.search(clean) or _PHONE_RE.search(clean):
                continue
            if "@" in clean:
                continue
            if "|" in clean:
                clean = clean.split("|")[0].strip()
            if re.match(r"^[A-Za-z .'\-]{2,60}$", clean) and 1 <= len(clean.split()) <= 5:
                full_name = clean
                break

    # ── Location fallback ───────────────────────────────────────────────
    if not location:
        for line in header_lines[:10]:
            if email and email in line:
                continue
            candidate = line.split("|")[0].strip()
            if re.match(r"[A-Za-z ]+,\s*[A-Za-z ]+", candidate) and not _EMAIL_RE.search(candidate):
                location = candidate
                break

    # Build a richer location string from the address parts when available
    if location and personal_details_lines:
        # Try to build a more complete location: "City, State/District, PIN"
        if address_parts:
            full_addr = ", ".join(address_parts) if isinstance(address_parts, list) else str(address_parts)
            # Extract city, district, and PIN from the full address
            addr_tokens = [p.strip().rstrip(",") for p in full_addr.split(",")]
            city = ""
            district = ""
            pin = ""
            for part in addr_tokens:
                part = part.strip()
                if not part:
                    continue
                # PIN code
                pin_m = re.search(r"\b(\d{5,6})\b", part)
                if pin_m:
                    pin = pin_m.group(1)
                    part = re.sub(r"\b\d{5,6}\b", "", part).strip().strip("–—-").strip()
                    if part and part != location:
                        district = part
                    continue
                # Skip house/plot numbers and street names
                if re.match(r"^\d", part):
                    continue
                if re.search(r"\b(?:street|road|nagar|colony|lane|cross|main|block|plot|flat|apt)\b", part, re.I):
                    continue
                if not city:
                    city = part
                elif part != city:
                    district = part
            # Build location: "City, District, PIN" or "City, PIN"
            loc_parts = [p for p in [city or location, district, pin] if p]
            if len(loc_parts) > 1:
                location = ", ".join(loc_parts)

    return {
        "fullName": full_name,
        "email": email,
        "phone": phone,
        "location": location,
    }


# ────────────────────────────────────────────────────────────────────
# Summary
# ────────────────────────────────────────────────────────────────────


def _extract_summary(section_lines: list[str]) -> str:
    parts: list[str] = []
    for line in section_lines:
        if not line:
            if parts:
                break
            continue
        parts.append(_clean_bullet(line))
    return " ".join(parts).strip()


# ────────────────────────────────────────────────────────────────────
# Experience helpers
# ────────────────────────────────────────────────────────────────────


def _is_job_entry_start(line: str) -> bool:
    """
    Return True if this line looks like the start of a job entry.
    Handles:
      Format A: "TITLE | MM/YYYY - DATE"    (date in the pipe part)
      Format C: "TITLE | Company Name"       (no date in the pipe part)
      Format D: "TITLE at Company"           (no pipe)
    """
    if not line.strip():
        return False
    # Taglines have 2+ pipes (e.g. "QA Lead | SDET | AI Quality Engineering") – not a job entry
    if line.count("|") > 1:
        return False
    # Format A
    if _TITLE_WITH_DATE_RE.match(line):
        return True
    # Format C: "TITLE | COMPANY" where right side is NOT a date
    if "|" in line:
        parts = line.split("|", 1)
        left = parts[0].strip()
        right = parts[1].strip() if len(parts) > 1 else ""
        # right must NOT be a date range → it's meant to be a company name
        if _TITLE_WORDS_RE.search(left) and not _DATE_RANGE_RE.match(right) and not _SINGLE_DATE_RE.match(right):
            return True
    # Format D: "Technology Lead at Infogain India"
    at_m = re.match(r"^(.+?)\s+at\s+(.+)$", line, re.I)
    if at_m and _TITLE_WORDS_RE.search(at_m.group(1)):
        return True
    return False


def _merge_wrapped_lines(lines: list[str]) -> str:
    """Merge PDF-wrapped continuation lines back into single sentences."""
    if not lines:
        return ""
    merged: list[str] = []
    for line in lines:
        if not line:
            continue
        if merged and not re.search(r"[.!?]$", merged[-1]) and not _BULLET_RE.match(line):
            merged[-1] = merged[-1].rstrip() + " " + line.lstrip()
        else:
            merged.append(line)
    return "\n".join(merged)


# ────────────────────────────────────────────────────────────────────
# Experience extraction
# ────────────────────────────────────────────────────────────────────


def _extract_experiences(section_lines: list[str]) -> list[dict[str, Any]]:
    """
    Handles multiple formats including mixed-format sections.

    Format A – title+date on same line:
        SENIOR CONSULTANT | 05/2024 - Current
        Capgemini - Bengaluru, India
        Bullet description...

    Format B – blank-line separated:
        Senior Software Engineer
        Google | Jan 2021 - Present
        • bullet

    Format C – title+company on same line, date on next line:
        Technology Lead | Infogain India Pvt Ltd
        Jan 2025 – Present
        Description bullets...

    Format D – standalone title line, date as continuation:
        Senior Test Engineer | GSR Business Service Pvt Ltd
        Jan 2016 to May 2018
        Description...
    """
    experiences: list[dict[str, Any]] = []
    if not section_lines:
        return experiences

    # ── Split into per-entry blocks ────────────────────────────────────
    # A new block starts whenever we detect a job entry start line
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in section_lines:
        if _is_job_entry_start(line):
            if current_block:
                # Don't start a new block for a blank-only current block
                non_blank = [l for l in current_block if l.strip()]
                if non_blank:
                    blocks.append(current_block)
            current_block = [line]
        else:
            current_block.append(line)

    if current_block and any(l.strip() for l in current_block):
        blocks.append(current_block)

    # Fallback: if no entry starts detected, split on blank lines
    if not blocks:
        for line in section_lines:
            if not line.strip():
                if current_block:
                    blocks.append(current_block)
                    current_block = []
            else:
                current_block.append(line)
        if current_block:
            blocks.append(current_block)

    # ── Parse each block ────────────────────────────────────────────────
    for block in blocks:
        non_blank = [l for l in block if l.strip()]
        if not non_blank:
            continue

        job_title = ""
        company = ""
        start_date = ""
        end_date = ""
        currently_working = False
        desc_parts: list[str] = []

        first = non_blank[0]

        # Format A: "TITLE | DATE_RANGE"
        fa_m = _TITLE_WITH_DATE_RE.match(first)
        if fa_m:
            job_title = fa_m.group(1).strip().rstrip("|–—-,").strip()
            start_date = _normalise_date(fa_m.group(2))
            end_raw = fa_m.group(3).strip()
            if re.match(r"(?:present|current|now|ongoing)", end_raw, re.I):
                currently_working = True
            else:
                end_date = _normalise_date(end_raw)
            remaining = non_blank[1:]
        # Format C: "TITLE | COMPANY" (no date in the pipe part)
        elif "|" in first and not _DATE_RANGE_RE.search(first.split("|", 1)[1] if "|" in first else ""):
            parts = first.split("|", 1)
            left = parts[0].strip().rstrip()
            right = parts[1].strip() if len(parts) > 1 else ""
            if _TITLE_WORDS_RE.search(left):
                job_title = left
                company = right
            else:
                job_title = left
                company = right
            remaining = non_blank[1:]
        else:
            # No pipe: entire first line is the job title
            job_title = first
            remaining = non_blank[1:]

        # ── Scan remaining lines for date, company, description ───────────
        header_done = False
        for line in remaining:
            clean = _clean_bullet(line)
            if not header_done:
                if _BULLET_RE.match(line):
                    header_done = True
                    desc_parts.append(clean)
                    continue
                # Date range on its own line
                dr_m = _DATE_RANGE_RE.search(clean)
                if dr_m and not start_date:
                    start_date = _normalise_date(dr_m.group(1))
                    end_raw = dr_m.group(2).strip()
                    if re.match(r"(?:present|current|now|ongoing)", end_raw, re.I):
                        currently_working = True
                    else:
                        end_date = _normalise_date(end_raw)
                    # Anything before/after date on the same line = possible company/domain note
                    prefix = _DATE_RANGE_RE.sub("", clean).strip().strip("()|–—-,")
                    if prefix and not company:
                        company = prefix.split("|")[0].strip()
                    continue
                # Company line: only if company not yet set AND line looks like a name (not a description)
                if not company and clean and not _DATE_RANGE_RE.search(clean):
                    # A description line starts with an action verb or is too long to be a name
                    _looks_like_desc = (
                        len(clean.split()) > 8
                        or re.match(
                            r"^(?:designed|developed|built|led|managed|created|implemented|"
                            r"worked|responsible|handled|maintained|ensured|performed|"
                            r"analyzed|achieved|drove|established|delivered|deployed|"
                            r"launched|conducted|coordinated|improved|collaborated|mentored)",
                            clean, re.I,
                        )
                    )
                    if _looks_like_desc:
                        header_done = True
                        desc_parts.append(clean)
                    else:
                        # Strip trailing location part e.g. "Capgemini - Bengaluru, India"
                        loc_split = re.split(r"\s+-\s+", clean, maxsplit=1)
                        if len(loc_split) == 2 and not _TITLE_WORDS_RE.search(loc_split[0]):
                            company = loc_split[0].strip()
                        else:
                            company = clean
                    continue
                # Company continuation: short line with no date after company is set but date not yet found
                if company and not start_date and clean and len(clean.split()) <= 3 and not _DATE_RANGE_RE.search(clean):
                    company = (company + " " + clean).strip()
                    continue
                # Lines after both company and date are known → descriptions
                if company and start_date:
                    header_done = True
                    if clean:
                        desc_parts.append(clean)
            else:
                if clean:
                    desc_parts.append(clean)

        job_title = job_title.strip("|–—-,").strip()
        company = company.strip("|–—-,").strip()
        # Ensure space before parenthetical domain: "CompanyName(DOMAIN)" → "CompanyName (DOMAIN)"
        company = re.sub(r"(\w)\(", r"\1 (", company)
        merged_desc = _merge_wrapped_lines(desc_parts)

        # Skip entries that look like personal projects (not professional experience)
        if re.search(r"\bpersonal\s+project\b", job_title, re.I) and not company and not start_date:
            continue
        # Skip entries with no meaningful content
        if not job_title and not company:
            continue

        if job_title or company:
            experiences.append(
                {
                    "id": _uid(),
                    "jobTitle": job_title,
                    "company": company,
                    "startDate": start_date,
                    "endDate": end_date,
                    "currentlyWorking": currently_working,
                    "description": merged_desc,
                }
            )

    return experiences


# ────────────────────────────────────────────────────────────────────
# Education extraction
# ────────────────────────────────────────────────────────────────────


def _is_edu_noise(line: str) -> bool:
    """Return True for known template/garbage education lines."""
    stripped = line.strip()
    if not stripped:
        return True
    if _NOISE_LINE_RE.match(stripped):
        return True
    # Canva template placeholders
    if re.match(
        r"^(?:university/college details?|course studied?|"
        r"description\s*:?\s*$|responsibilities\s*:?\s*$)",
        stripped, re.I
    ):
        return True
    return False


def _extract_education(section_lines: list[str]) -> list[dict[str, Any]]:
    """
    Handles:
    Format A – pipe-separated on first line:
        Sona College of Technology | Bachelor of Engineering (B.E)
        Computer Science Engineering, 05/2015

    Format B – multi-line block:
        Bachelor of Engineering –           ← degree spans lines
        Computer Science and Engineering
        Sapthagiri College of Engineering, Anna University
        2007 - 2011
    """
    educations: list[dict[str, Any]] = []
    # First filter out all noise lines
    clean_lines = [l for l in section_lines if not _is_edu_noise(l)]
    if not clean_lines:
        return educations

    # Split into blocks on blank lines
    blocks: list[list[str]] = []
    current_block: list[str] = []
    for line in clean_lines:
        if not line.strip():
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(line.strip())
    if current_block:
        blocks.append(current_block)

    for block in blocks:
        non_blank = [l for l in block if l.strip() and not _is_edu_noise(l)]
        if not non_blank:
            continue

        school = ""
        degree = ""
        field_of_study = ""
        start_date = ""
        end_date = ""
        grade = ""

        first_line = non_blank[0]
        pipe_m = _SCHOOL_DEGREE_PIPE_RE.match(first_line)

        # Format A: "School | Degree" with no date range on the first line
        if pipe_m and not _DATE_RANGE_RE.search(first_line) and _DEGREE_RE.search(pipe_m.group(2)):
            school = pipe_m.group(1).strip()
            raw_degree_part = pipe_m.group(2).strip()
            deg_m = _DEGREE_RE.search(raw_degree_part)
            if deg_m:
                degree = deg_m.group(0)

            for line in non_blank[1:]:
                if _is_edu_noise(line):
                    continue
                gpa_m = _GPA_RE.search(line)
                if gpa_m:
                    grade = gpa_m.group(1).strip()
                    continue
                dr_m = _DATE_RANGE_RE.search(line)
                if dr_m:
                    start_date = _normalise_date(dr_m.group(1))
                    end_raw = dr_m.group(2).strip()
                    end_date = "" if re.match(r"(?:present|current|now|ongoing)", end_raw, re.I) else _normalise_date(end_raw)
                    prefix = _DATE_RANGE_RE.sub("", line).strip().rstrip(",|–—-").strip()
                    if prefix and not field_of_study:
                        field_of_study = prefix
                    continue
                sd_m = _SINGLE_DATE_RE.search(line)
                if sd_m:
                    end_date = _normalise_date(sd_m.group(1))
                    fos = _SINGLE_DATE_RE.sub("", line).strip().rstrip(",|–—-").strip()
                    if fos and not field_of_study:
                        field_of_study = fos
                    continue
                if not field_of_study:
                    field_of_study = line.rstrip(",|–—-").strip()

        else:
            # Format B: consolidate multi-line blocks
            # Join continuation lines: those following a line ending with "–", "-", "and", or "&"
            joined_lines: list[str] = []
            for line in non_blank:
                if joined_lines and (
                    joined_lines[-1].endswith("–")
                    or joined_lines[-1].endswith("-")
                    or re.search(r"\b(?:and|&)\s*$", joined_lines[-1], re.I)
                ):
                    joined_lines[-1] = joined_lines[-1].rstrip("–-").strip() + " " + line.strip()
                else:
                    joined_lines.append(line)

            full_text = " ".join(joined_lines)

            deg_m = _DEGREE_RE.search(full_text)
            if deg_m:
                degree = deg_m.group(0)

            dr_m = _DATE_RANGE_RE.search(full_text)
            if dr_m:
                start_date = _normalise_date(dr_m.group(1))
                end_raw = dr_m.group(2).strip()
                end_date = "" if re.match(r"(?:present|current|now|ongoing)", end_raw, re.I) else _normalise_date(end_raw)
            else:
                sd_m = _SINGLE_DATE_RE.search(full_text)
                if sd_m:
                    end_date = _normalise_date(sd_m.group(1))

            gpa_m = _GPA_RE.search(full_text)
            if gpa_m:
                grade = gpa_m.group(1).strip()

            # Field of study: extract from the specific line containing the degree keyword,
            # NOT from the full joined text (which also contains the school name).
            if deg_m:
                degree_line = ""
                deg_line_m = None
                for jl in joined_lines:
                    dm = _DEGREE_RE.search(jl)
                    if dm:
                        degree_line = jl
                        deg_line_m = dm
                        break
                after_raw = degree_line[deg_line_m.end():].strip() if deg_line_m else full_text[deg_m.end():].strip()
                after_raw = re.sub(r"^(?:in|of|–|-|,)\s*", "", after_raw, flags=re.I)
                fos_m = re.match(
                    r"([A-Za-z &/,]+?)(?:\s*[\(\|–—\-]|\s*\d|\bGPA\b|\bCGPA\b|"
                    r"\b(?:university|college|institute|school|academy)\b|$)",
                    after_raw, re.I
                )
                if fos_m:
                    raw_fos = fos_m.group(1).strip().rstrip(",|-–—").strip()
                    field_of_study = raw_fos[:80]

            # School: first line that contains university/college indicator and doesn't have degree/date
            # Also join split school names (e.g. "Sapthagiri College of" + "Engineering, Anna University")
            school_candidate = ""
            for i, line in enumerate(joined_lines):
                if _is_edu_noise(line):
                    continue
                clean = _BULLET_RE.sub("", line).strip()
                if _DEGREE_RE.search(clean) or _GPA_RE.search(clean):
                    continue
                stripped = _DATE_RANGE_RE.sub("", _SINGLE_DATE_RE.sub("", clean)).strip().rstrip("|–—-,").strip()
                if not stripped:
                    continue
                # Prefer lines that contain university/college indicators
                if re.search(r"\b(?:university|college|institute|school|academy)\b", stripped, re.I):
                    # Check if this line ends with a preposition → name continues on next line
                    if re.search(r"\b(?:of|at|in|and)\s*$", stripped, re.I) and i + 1 < len(joined_lines):
                        next_line = joined_lines[i + 1].strip()
                        if next_line and not _DEGREE_RE.search(next_line) and not _DATE_RANGE_RE.search(next_line):
                            stripped = stripped + " " + next_line.rstrip(",|–—-").strip()
                    school = stripped
                    break
                elif not school_candidate:
                    school_candidate = stripped
            if not school and school_candidate:
                school = school_candidate

        field_of_study = field_of_study.strip().rstrip(",").strip()
        school = school.strip()
        degree = degree.strip()

        # Skip pure garbage blocks
        if re.match(r"^(?:mation|description|responsibilities)", school, re.I):
            continue

        if school or degree:
            educations.append(
                {
                    "id": _uid(),
                    "school": school,
                    "degree": degree,
                    "fieldOfStudy": field_of_study,
                    "startDate": start_date,
                    "endDate": end_date,
                    "grade": grade,
                }
            )

    return educations


# ────────────────────────────────────────────────────────────────────
# Skills extraction
# ────────────────────────────────────────────────────────────────────

# Items that look like contact info / personal data → never a skill
_SKILL_NOISE_RE = re.compile(
    r"(?:"
    r"@|"                               # email
    r"^\+?\d[\d\s\-\(\)]{5,}$|"         # phone number
    r"www\.|http|github\.com|linkedin|gitlab|"   # URLs
    r"^\d{5,}$|"                        # pure zip/postal
    r"^(?:contacts?|references?)$"      # section heading noise
    r")",
    re.I,
)

# Common Canva / template placeholder skills that should be filtered out
_CANVA_TEMPLATE_SKILLS = {
    "visual design", "process flows", "storyboards", "ui/ux",
    "user flows", "wireframes", "prototyping", "user research",
    "design thinking", "figma", "sketch", "adobe xd",
    "information architecture", "interaction design",
    # Add more known Canva defaults as they are discovered
}


def _extract_skills(section_lines: list[str]) -> list[dict[str, str]]:
    skills: list[dict[str, str]] = []
    seen: set[str] = set()

    # Merge continuation lines (previous line ended with comma → next line continues)
    merged_lines: list[str] = []
    for line in section_lines:
        if not line:
            continue
        if _SKILL_CATEGORY_RE.match(line):
            merged_lines.append(line)
        elif merged_lines and merged_lines[-1].endswith(","):
            merged_lines[-1] = merged_lines[-1].rstrip() + " " + line.strip()
        else:
            merged_lines.append(line)

    for line in merged_lines:
        clean = _clean_bullet(line)
        if not clean:
            continue

        # Skip contact-info / noise lines entirely
        if _SKILL_NOISE_RE.search(clean):
            continue
        if _EMAIL_RE.search(clean):
            continue
        if _PHONE_RE.match(clean.replace(" ", "")):
            continue

        cat_m = _SKILL_CATEGORY_RE.match(clean)
        if cat_m:
            tokens = re.split(r"[,;|•●·/]", cat_m.group(2))
        elif ":" in clean:
            _, _, after = clean.partition(":")
            tokens = re.split(r"[,;|•●·/]", after)
        else:
            tokens = re.split(r"[,;|•●·]", clean)

        for token in tokens:
            token = token.strip().strip("-–—").strip()
            if not token or len(token) > 60:
                continue
            # Skip contact-info tokens
            if _SKILL_NOISE_RE.search(token) or _EMAIL_RE.search(token):
                continue
            # Skip URL path fragments (e.g. "/ai-qa-framework" from split github URLs)
            if token.startswith("/") or token.startswith("http"):
                continue
            # Skip section-heading noise
            if any(p.match(token) for p in _SECTION_PATTERNS.values()):
                continue
            level = "Intermediate"
            lm = _SKILL_LEVEL_RE.search(token)
            if lm:
                level = _LEVEL_MAP.get(lm.group(1).lower(), "Intermediate")
                token = _SKILL_LEVEL_RE.sub("", token).strip().rstrip("()- ")
            if not token or token.lower() in seen:
                continue
            # Skip items that are clearly NOT skills (long sentences, pure punctuation)
            if len(token) < 2:
                continue
            # Skip known Canva / template placeholder skills
            if token.lower() in _CANVA_TEMPLATE_SKILLS:
                continue
            seen.add(token.lower())
            skills.append({"id": _uid(), "name": token, "level": level})

    return skills


# ────────────────────────────────────────────────────────────────────
# 7. LANGUAGES
# ────────────────────────────────────────────────────────────────────

_LANG_LINE_RE = re.compile(
    r"languages?\s*[:\-–]\s*(.+)", re.I
)

def _extract_languages(
    lang_section_lines: list[str],
    personal_details_lines: list[str] | None,
) -> list[dict[str, str]]:
    """Extract languages from the languages section or personal details.

    Sources checked (in priority order):
    1. Dedicated "Languages" section  → already split by _split_sections
    2. "Language : X, Y" line inside PERSONAL DETAILS section
    """
    raw_names: list[str] = []

    # Source 1: dedicated languages section
    for line in lang_section_lines:
        line = line.strip()
        if not line:
            continue
        # Skip the heading itself
        if re.match(r"^languages?\s*:?\s*$", line, re.I):
            continue
        # Might be comma-separated: "English, Tamil, Hindi"
        for chunk in re.split(r"[,;/|]", line):
            chunk = chunk.strip().strip("•–-").strip()
            if chunk and len(chunk) < 40:
                raw_names.append(chunk)

    # Source 2: personal details "Languages : ..." line
    if not raw_names and personal_details_lines:
        for line in personal_details_lines:
            m = _LANG_LINE_RE.match(line.strip())
            if m:
                for chunk in re.split(r"[,;/|]", m.group(1)):
                    chunk = chunk.strip().strip("•–-").strip()
                    if chunk and len(chunk) < 40:
                        raw_names.append(chunk)
                break

    # Deduplicate and build result
    seen: set[str] = set()
    languages: list[dict[str, str]] = []
    for name in raw_names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        languages.append({"id": _uid(), "name": name, "level": "Intermediate"})

    return languages


# ────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────


def parse_resume_text(text: str) -> dict[str, Any]:
    sections = _split_sections(text)

    # ── Personal info ──────────────────────────────────────────────────
    personal = _extract_personal_info(
        header_lines=sections.get("header", []),
        full_text=text,
        contacts_lines=sections.get("contacts"),
        personal_details_lines=sections.get("personal_details"),
    )

    # ── Summary ────────────────────────────────────────────────────────
    summary = ""
    if "summary" in sections:
        summary = _extract_summary(sections["summary"])
    if not summary:
        tail = [l for l in sections.get("header", [])[4:] if l.strip()]
        if tail and len(" ".join(tail)) > 40:
            summary = " ".join(_clean_bullet(l) for l in tail).strip()

    personal["professionalSummary"] = summary

    # ── Experiences ────────────────────────────────────────────────────
    # Merge experience lines from ALL sections that may contain work entries.
    # In 2-column PDFs (Canva etc.) some entries land under 'contacts'.
    exp_lines: list[str] = list(sections.get("experience", []))
    contacts_lines = sections.get("contacts", [])
    # Include contacts lines that contain job-entry indicators
    contact_exp_lines: list[str] = []
    for line in contacts_lines:
        if _is_job_entry_start(line) or _DATE_RANGE_RE.search(line):
            contact_exp_lines.append(line)
        elif contact_exp_lines:
            # continuation line after a job start
            contact_exp_lines.append(line)
    exp_lines = exp_lines + contact_exp_lines

    experiences = _extract_experiences(exp_lines)

    # ── Education ──────────────────────────────────────────────────────
    education = _extract_education(sections.get("education", []))

    # ── Skills ─────────────────────────────────────────────────────────
    # Deduplicate across multiple "Skills" occurrences (page 1 real + page 2 template)
    skills = _extract_skills(sections.get("skills", []))

    # ── Languages ──────────────────────────────────────────────────────
    languages = _extract_languages(
        sections.get("languages", []),
        sections.get("personal_details"),
    )

    return {
        "personalInfo": personal,
        "experiences": experiences,
        "education": education,
        "skills": skills,
        "languages": languages,
    }
