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
        r"^(?:professional\s+)?(?:summary|profile|about(?:\s+me)?|objective|career\s+(?:summary|objective))\s*:?\s*$",
        re.I,
    ),
    "experience": re.compile(
        r"^(?:(?:work|professional|employment|career)\s+)?(?:experience|history)\s*:?\s*$",
        re.I,
    ),
    "education": re.compile(
        r"^(?:education(?:al)?(?:\s+(?:background|qualifications|history))?|academic\s+(?:background|qualifications))\s*:?\s*$",
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
}

# ────────────────────────────────────────────────────────────────────
# Regex helpers
# ────────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
_PHONE_RE = re.compile(r"(\+?[\d][\d\s\-().]{6,}\d)")

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

# Pattern: "TITLE | DATE_RANGE" on a single line
_TITLE_WITH_DATE_RE = re.compile(
    rf"^(.+?)\s*\|\s*({_DATE_TOKEN})\s*(?:[-–—]|to)\s*({_DATE_TOKEN}|[Pp]resent|[Cc]urrent|[Nn]ow|[Oo]ngoing)\s*$",
    re.I,
)

# Pattern: "School | Degree" (no date range)
_SCHOOL_DEGREE_PIPE_RE = re.compile(
    r"^(.+?)\s*\|\s*([A-Za-z].{3,80})$",
)

_DEGREE_RE = re.compile(
    r"(?:Bachelor(?:'?s)?(?:\s+of\s+\w+)?|B\.?\s?[A-Z]\.?(?:[A-Za-z\.]+)?|"
    r"Master(?:'?s)?(?:\s+of\s+\w+)?|M\.?\s?[A-Z]\.?(?:[A-Za-z\.]+)?|"
    r"Doctor(?:ate)?|Ph\.?\s?D\.?|Associate(?:'?s)?|Diploma|"
    r"B\.?Com\.?|M\.?Com\.?|B\.?Sc\.?|M\.?Sc\.?|B\.?C\.?A\.?|M\.?C\.?A\.?|"
    r"B\.?E\.?|M\.?E\.?|B\.?Tech\.?|M\.?Tech\.?|M\.?B\.?A\.?)",
    re.I,
)

_GPA_RE = re.compile(
    r"(?:GPA|CGPA|Grade|Percentage|Score)\s*:?\s*([\d.]+(?:\s*[/%]\s*[\d.]+)?)",
    re.I,
)

_BULLET_RE = re.compile(r"^[\u2022\u2023\u25E6\u2043\u2022\u25CF\u25CB\u25E6\u25AA\u25B8\u25BA\-\*•●○◦▪▸►–]\s*")
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


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _clean_bullet(text: str) -> str:
    return _BULLET_RE.sub("", text).strip()


def _normalise_date(date_str: str) -> str:
    return date_str.strip()


# ────────────────────────────────────────────────────────────────────
# Section splitter
# ────────────────────────────────────────────────────────────────────


def _split_sections(text: str) -> dict[str, list[str]]:
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


def _extract_personal_info(header_lines: list[str], full_text: str) -> dict[str, str]:
    email = ""
    phone = ""
    full_name = ""
    location = ""

    em = _EMAIL_RE.search(full_text)
    if em:
        email = em.group(0)

    ph = _PHONE_RE.search(full_text)
    if ph:
        phone = ph.group(0).strip()

    cleaned_header: list[str] = []
    for line in header_lines:
        if "|" in line and (email in line or (phone and phone.replace("+", "").replace(" ", "") in line.replace(" ", ""))):
            parts = [p.strip() for p in line.split("|")]
            for part in parts:
                if email in part:
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

    if not location:
        for line in header_lines[:8]:
            if email and email in line:
                continue
            candidate = line.split("|")[0].strip()
            if re.match(r"[A-Za-z ]+,\s*[A-Za-z ]+", candidate):
                location = candidate
                break

    for line in cleaned_header[:4] + header_lines[:4]:
        if not line:
            continue
        if email and email in line:
            continue
        clean = _BULLET_RE.sub("", line).strip()
        if re.search(r"https?://|www\.|@|\d{6,}", clean):
            continue
        if "|" in clean:
            clean = clean.split("|")[0].strip()
        if re.match(r"^[A-Za-z .'\-]{2,60}$", clean) and 1 <= len(clean.split()) <= 5:
            full_name = clean
            break

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
# Experience
# ────────────────────────────────────────────────────────────────────

_TITLE_WORDS_RE = re.compile(
    r"\b(?:engineer|developer|manager|analyst|designer|consultant|lead|"
    r"intern|architect|director|specialist|coordinator|administrator|"
    r"executive|officer|associate|assistant|senior|junior|sr\.?|jr\.?|"
    r"head|vp|vice\s*president|chief|cto|ceo|cfo|coo|frontend|backend|"
    r"fullstack|full\s*stack|devops|qa|tester|programmer|scientist)\b",
    re.I,
)


def _merge_wrapped_lines(lines: list[str]) -> str:
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


def _extract_experiences(section_lines: list[str]) -> list[dict[str, Any]]:
    """
    Format A (title+date on one line):
        SENIOR CONSULTANT | 05/2024 - Current
        Capgemini - Bengaluru, India
        Bullet description...

    Format B (blank-line separated, date on its own line):
        Senior Software Engineer
        Google | Jan 2021 - Present
        • bullet
    """
    experiences: list[dict[str, Any]] = []
    if not section_lines:
        return experiences

    title_date_count = sum(1 for l in section_lines if l and _TITLE_WITH_DATE_RE.match(l))
    use_format_a = title_date_count > 0

    blocks: list[list[str]] = []
    current_block: list[str] = []

    if use_format_a:
        for line in section_lines:
            if _TITLE_WITH_DATE_RE.match(line) and current_block:
                blocks.append(current_block)
                current_block = [line]
            else:
                current_block.append(line)
    else:
        for line in section_lines:
            if not line:
                if current_block:
                    blocks.append(current_block)
                    current_block = []
            else:
                current_block.append(line)

    if current_block:
        blocks.append(current_block)

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
        remaining: list[str] = []

        if use_format_a:
            first = non_blank[0]
            m = _TITLE_WITH_DATE_RE.match(first)
            if m:
                job_title = m.group(1).strip().rstrip("|–—-,").strip()
                start_date = _normalise_date(m.group(2))
                end_raw = m.group(3).strip()
                if re.match(r"(?:present|current|now|ongoing)", end_raw, re.I):
                    currently_working = True
                    end_date = ""
                else:
                    end_date = _normalise_date(end_raw)
                remaining = non_blank[1:]
            else:
                remaining = non_blank
        else:
            remaining = non_blank

        header_done = False
        company_candidates: list[str] = []

        for line in remaining:
            clean = _clean_bullet(line)
            if not header_done:
                if _BULLET_RE.match(line):
                    header_done = True
                    desc_parts.append(clean)
                    continue
                dr_m = _DATE_RANGE_RE.search(clean)
                if dr_m and not start_date:
                    start_date = _normalise_date(dr_m.group(1))
                    end_raw = dr_m.group(2).strip()
                    if re.match(r"(?:present|current|now|ongoing)", end_raw, re.I):
                        currently_working = True
                        end_date = ""
                    else:
                        end_date = _normalise_date(end_raw)
                    prefix = _DATE_RANGE_RE.sub("", clean).strip().rstrip("|–—-,").strip()
                    if prefix and not job_title:
                        job_title = prefix
                    elif prefix and not company:
                        company = prefix
                    continue
                company_candidates.append(clean)
            else:
                desc_parts.append(clean)

        if not company and company_candidates:
            raw_company = company_candidates[0]
            # Strip " - Location" suffix: "Capgemini - Bengaluru, India" → "Capgemini"
            loc_split = re.split(r"\s+-\s+", raw_company, maxsplit=1)
            if len(loc_split) == 2 and not _TITLE_WORDS_RE.search(loc_split[0]):
                company = loc_split[0].strip()
            else:
                company = raw_company
            # Remaining company_candidates after the first are descriptions
            if len(company_candidates) > 1:
                desc_parts = [_clean_bullet(l) for l in remaining[len(company_candidates):] if l.strip()]
        elif not job_title and company_candidates:
            job_title = company_candidates[0]

        job_title = job_title.strip("|–—-,").strip()
        company = company.strip("|–—-,").strip()
        merged_desc = _merge_wrapped_lines(desc_parts)

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
# Education
# ────────────────────────────────────────────────────────────────────

_NOISE_LINE_RE = re.compile(r"^(?:declaration|i hereby|belief\.?).*$", re.I)


def _extract_education(section_lines: list[str]) -> list[dict[str, Any]]:
    """
    Format A (pipe-separated school | degree, then field + single date):
        Sona College of Technology - Salem | Bachelor of Engineering (B.E)
        Computer Science Engineering, 05/2015

    Format B (blank-separated, multi-line):
        Stanford University
        B.S. Computer Science | 2014 - 2018
        GPA: 3.8
    """
    educations: list[dict[str, Any]] = []
    clean_lines = [l for l in section_lines if not _NOISE_LINE_RE.match(l.strip())]

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
        non_blank = [l for l in block if l.strip() and not _NOISE_LINE_RE.match(l.strip())]
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
                if _NOISE_LINE_RE.match(line.strip()):
                    continue
                gpa_m = _GPA_RE.search(line)
                if gpa_m:
                    grade = gpa_m.group(1).strip()
                    continue

                # Date range (e.g. "2014 - 2018")
                dr_m = _DATE_RANGE_RE.search(line)
                if dr_m:
                    start_date = _normalise_date(dr_m.group(1))
                    end_raw = dr_m.group(2).strip()
                    end_date = "" if re.match(r"(?:present|current|now|ongoing)", end_raw, re.I) else _normalise_date(end_raw)
                    prefix = _DATE_RANGE_RE.sub("", line).strip().rstrip(",|–—-").strip()
                    if prefix and not field_of_study:
                        field_of_study = prefix
                    continue

                # Single graduation date: "Computer Science Engineering, 05/2015"
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
            # Format B / C: parse lines individually
            full_text = " ".join(non_blank)

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

            if deg_m:
                after = full_text[deg_m.end():].strip()
                after = re.sub(r"^(?:in|of)\s+", "", after, flags=re.I)
                fos_m = re.match(r"([A-Za-z &/,]+?)(?:\s*[\(\|–—\-]|\d|\bGPA\b|\bCGPA\b|$)", after, re.I)
                if fos_m:
                    field_of_study = fos_m.group(1).strip().rstrip(",|-–—")

            for line in non_blank:
                if _NOISE_LINE_RE.match(line.strip()):
                    continue
                clean = _BULLET_RE.sub("", line).strip()
                if _DEGREE_RE.search(clean) or _GPA_RE.search(clean):
                    continue
                stripped = _DATE_RANGE_RE.sub("", _SINGLE_DATE_RE.sub("", clean)).strip()
                if not stripped:
                    continue
                school = stripped.rstrip("|–—-,").strip()
                break

        field_of_study = field_of_study.strip().rstrip(",").strip()
        school = school.strip()
        degree = degree.strip()

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
# Skills
# ────────────────────────────────────────────────────────────────────


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
            if any(p.match(token) for p in _SECTION_PATTERNS.values()):
                continue
            level = "Intermediate"
            lm = _SKILL_LEVEL_RE.search(token)
            if lm:
                level = _LEVEL_MAP.get(lm.group(1).lower(), "Intermediate")
                token = _SKILL_LEVEL_RE.sub("", token).strip().rstrip("()- ")
            if not token or token.lower() in seen:
                continue
            seen.add(token.lower())
            skills.append({"id": _uid(), "name": token, "level": level})

    return skills


# ────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────


def parse_resume_text(text: str) -> dict[str, Any]:
    sections = _split_sections(text)

    personal = _extract_personal_info(sections.get("header", []), text)

    summary = ""
    if "summary" in sections:
        summary = _extract_summary(sections["summary"])
    if not summary:
        tail = [l for l in sections.get("header", [])[4:] if l.strip()]
        if tail and len(" ".join(tail)) > 40:
            summary = " ".join(_clean_bullet(l) for l in tail).strip()

    personal["professionalSummary"] = summary

    experiences = _extract_experiences(sections.get("experience", []))
    education = _extract_education(sections.get("education", []))
    skills = _extract_skills(sections.get("skills", []))

    return {
        "personalInfo": personal,
        "experiences": experiences,
        "education": education,
        "skills": skills,
    }
