import re

MONTH_PATTERN = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
DATE_RANGE_PATTERN = re.compile(
    r"(?P<range>"
    rf"(?:{MONTH_PATTERN}\.?\s*)?(?:(?:19|20)\d{{2}}|20XX)\s*[-–—+]+\s*"
    rf"(?:(?:{MONTH_PATTERN}\.?\s*)?(?:(?:19|20)\d{{2}}|20XX)|Present|Current|Till Date|Now)"
    rf"|(?:{MONTH_PATTERN}\.?\s*)?(?:(?:19|20)\d{{2}}|20XX)\b"
    r")",
    re.IGNORECASE,
)
TITLE_KEYWORDS = (
    "developer", "engineer", "designer", "manager", "analyst", "consultant",
    "specialist", "executive", "director", "intern", "lead", "architect",
    "administrator", "coordinator", "officer", "associate", "supervisor",
    "technician", "programmer", "accountant", "recruiter", "trainee", "devops",
    "representative", "hairdresser", "stylist", "checker", "faculty", "teacher",
)
COMPANY_KEYWORDS = (
    "ltd", "limited", "inc", "llp", "pvt", "corp", "gmbh", "company", "technologies",
    "technology", "solutions", "services", "group", "studio", "consulting", "salon",
    "systems", "infotech", "enterprises", "industries", "bank", "hospital",
    "google", "microsoft", "amazon", "tcs", "infosys", "wipro", "mphasis",
)
DESCRIPTION_VERBS = (
    "built", "developed", "designed", "managed", "led", "worked", "created",
    "implemented", "maintained", "supported", "handled", "prepared", "assisted",
)
SKILL_FALSE_COMPANIES = (
    "wordpress", "photoshop", "javascript", "java script", "jave script", "jove script", "html",
    "html5", "html 5", "css", "flash", "animation", "illustrator", "indesign",
    "python", "java", "sql",
)
LOCATION_NAMES = (
    "india", "usa", "uae", "uk", "canada", "australia", "germany", "france",
    "singapore", "delhi", "mumbai", "bangalore", "hyderabad", "pune", "chennai",
    "kolkata", "boston", "york", "california", "texas", "maharashtra", "karnataka",
)
SPURIOUS_COMPANY_VALUES = (
    "contact", "hobbies", "hobby", "education", "languages", "language", "skills",
    "technical skills", "personal skills", "soft skills", "hard skills", "interests",
    "certifications", "objective", "career objective", "exploration", "languages known",
    "profile", "summary", "name", "surname", "name surname",
)
TEMPLATE_PLACEHOLDER_MARKERS = (
    "write your job title",
    "beginning date",
    "end date",
    "fnd nate",
    "your degree here your position here",
)
EDUCATION_ROW_KEYWORDS = (
    "bachelor", "master", "secondary", "higher secondary", "10th", "12th", "grade",
    "degree", "diploma", "certificate", "university", "college", "school", "cgpa",
    "engineering college", "senior secondary", "middle school",
)


def clean_line(text):
    text = (text or "").strip()
    text = re.sub(r"^[^\w#(+]+", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip(" @|")


def line_has_date_range(line):
    return bool(DATE_RANGE_PATTERN.search(line or ""))


def extract_date_range(line):
    match = DATE_RANGE_PATTERN.search(line or "")
    return match.group("range").strip() if match else False


def strip_date_from_line(line):
    date_range = extract_date_range(line)
    if not date_range:
        return clean_line(line), False
    return clean_line(line.replace(date_range, "", 1)), date_range


def split_title_company(line):
    line, _date = strip_date_from_line(line)
    if not line:
        return False, False
    for pattern in (r"\s[-–—]\s+", r"\s*\|\s*", r"\s+at\s+", r",\s+"):
        parts = re.split(pattern, line, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            title, company = parts[0].strip(), parts[1].strip()
            if title and (
                pattern != r",\s+" or looks_like_job_title(title) or looks_like_company(company)
            ):
                company = re.sub(r"\s*\((?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|present)\)\s*$", "", company, flags=re.IGNORECASE).strip()
                company = re.sub(r"\s*\(\s*\)\s*$", "", company).strip()
                return title, company or False
    return line, False


def extract_location_value(text):
    if not text:
        return False
    text = clean_line(text)
    match = re.match(r"^location\s*:\s*(.+)$", text, re.IGNORECASE)
    if match:
        return clean_line(match.group(1))
    if looks_like_location(text) or re.search(r"\b(?:%s)\b" % "|".join(LOCATION_NAMES), text, re.IGNORECASE):
        return text
    return False


def looks_like_job_title(line):
    if looks_like_description(line):
        return False
    normalized = re.sub(r"[^a-z0-9 ]+", "", (line or "").lower())
    return any(keyword in normalized for keyword in TITLE_KEYWORDS)


def looks_like_company(line):
    normalized = re.sub(r"[^a-z0-9 ]+", "", (line or "").lower())
    if looks_like_description(line):
        return False
    if normalized in SKILL_FALSE_COMPANIES or any(skill in normalized for skill in SKILL_FALSE_COMPANIES):
        return False
    if re.search(r"\b(?:%s)\b" % "|".join(LOCATION_NAMES), normalized):
        return False
    if any(keyword in normalized for keyword in COMPANY_KEYWORDS):
        return True
    return bool(re.match(r"^[A-Z][A-Za-z0-9.&-]{1,40}$", (line or "").strip()))


def looks_like_body_text(line):
    normalized = re.sub(r"[^a-z0-9 ]+", "", (line or "").lower())
    if is_resume_noise_line(line):
        return False
    if re.search(
        r"\b(?:lorem|ipsum|dolor|consectetur|adipiscing|adipisicing|adipisic|sdipsicing|"
        r"atque|facilis|maiores|moiores|malores|libero|blanditiis|praesentium|magnam|"
        r"modi|nascetur|ridiculus|parturient|consec|consectetuer)\b",
        normalized,
    ):
        return True
    if looks_like_description(line):
        return True
    return len((line or "").split()) >= 6


def normalize_description_text(text):
    if not text:
        return False
    lines = []
    replacements = (
        (r"\bSdipsicing\b", "adipisicing"),
        (r"\bSdiplsicing\b", "adipisicing"),
        (r"\bad ipsicing\b", "adipisicing"),
        (r"\bAtaue\b", "Atque"),
        (r"\bAtQue\b", "Atque"),
        (r"\bhbero\b", "libero"),
        (r"\bhbbero\b", "libero"),
        (r"\bbboro\b", "libero"),
        (r"\bpracsentivm\b", "praesentium"),
        (r"\bpracsentium\b", "praesentium"),
        (r"\baxsesentium\b", "praesentium"),
        (r"\bBisnditlis\b", "blanditiis"),
        (r"\bBlanditlis\b", "blanditiis"),
        (r"\bMalores\b", "Maiores"),
        (r"\bMoiores\b", "Maiores"),
        (r"\bMoiores\b", "Maiores"),
        (r"\bf9c%lss\b", "facilis"),
        (r"\bmMagnam\b", "magnam"),
        (r"\bMagNIM\b", "magnam"),
        (r"\bExocseNtiuM\b", "praesentium"),
        (r"\bBionditiis\b", "blanditiis"),
        (r"\bconsec-\b", "consectetur"),
        (r"\bLorom\b", "Lorem"),
        (r"\s+", " "),
    )
    for line in (text or "").splitlines():
        if is_resume_noise_line(line):
            continue
        line = clean_description_line(line) or clean_line(line)
        if not line:
            continue
        for pattern, replacement in replacements:
            if pattern == r"\s+":
                line = re.sub(pattern, replacement, line).strip()
            else:
                line = re.sub(pattern, replacement, line, flags=re.IGNORECASE)
        if line:
            lines.append(line)
    return "\n".join(lines) or False


def clean_description_line(line):
    line = clean_line(line)
    if not line:
        return False
    line = re.sub(r"^(?:e|©|®|¢|»)\s+", "", line, flags=re.IGNORECASE)
    if is_resume_noise_line(line):
        return False
    line = re.sub(
        r"\s+(?:HTML\s*5|HTML5|CSS|Wordpress|Photoshop|Flash\s*Animation|Java\s*Script|"
        r"Jave\s*Script|Jove\s*Script|Illustrator|InDesign|WIMLS|HNACSS)\s*$",
        "",
        line,
        flags=re.IGNORECASE,
    )
    line = re.sub(r"\s+SS\s*$", "", line, flags=re.IGNORECASE)
    return line.strip() or False


def is_resume_noise_line(line):
    normalized = re.sub(r"[^a-z0-9 ]+", " ", (line or "").lower()).strip()
    if not normalized:
        return True
    if "write a work experience" in normalized:
        return True
    if normalized in {
        "profile", "contact", "skills", "education", "interests", "hobbies",
        "professional experience", "work experience", "name", "surname", "name surname",
        "nyu", "new york",
    }:
        return True
    if re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", line or "", flags=re.IGNORECASE):
        return True
    digits = re.sub(r"\D", "", line or "")
    if 8 <= len(digits) <= 15 and len(normalized.split()) <= 5:
        return True
    if re.search(r"\b(?:sales negotiation|account management|market research)\b", normalized):
        return True
    if re.fullmatch(r"[a-f0-9]{6,}", normalized):
        return True
    if normalized in {"eee", "eeee", "ee", "dar"}:
        return True
    if re.search(
        r"\b(?:results oriented|proven track record|revenue growth|lasting relationships|"
        r"target sales strategies)\b",
        normalized,
    ):
        return True
    return False


def is_generic_description(text):
    if not text:
        return True
    normalized = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).strip()
    if normalized in {"lorem ipsum", "lorem", "description", "responsibilities"}:
        return True
    return len(normalized) < 24 and "lorem ipsum" in normalized


def split_company_location(line):
    line = clean_line(line)
    if not line:
        return False, False
    match = re.match(r"^(.+?)\s[-–—]\s+(.+)$", line)
    if not match:
        return False, False
    company = match.group(1).strip()
    location = match.group(2).strip()
    if looks_like_job_title(company) and not any(keyword in company.lower() for keyword in COMPANY_KEYWORDS):
        return False, False
    if looks_like_location(location) or "," in location or re.search(
        r"\b(?:%s)\b" % "|".join(LOCATION_NAMES), location, re.IGNORECASE
    ):
        return company, location
    return False, False


def is_standalone_date_line(line):
    plain, date_range = strip_date_from_line(line)
    return bool(date_range) and not plain


def looks_like_description(line):
    normalized = re.sub(r"[^a-z0-9 ]+", "", (line or "").lower())
    if (line or "").strip().startswith(("-", "•", "*")):
        return True
    return any(normalized.startswith(verb) or f" {verb}" in normalized for verb in DESCRIPTION_VERBS)


def looks_like_location(line):
    if looks_like_job_title(line) or looks_like_company(line) or looks_like_description(line):
        return False
    if re.match(r"^location\s*:", line or "", re.IGNORECASE):
        return True
    if "," in line:
        words = re.findall(r"[A-Za-z]+", line or "")
        return 1 <= len(words) <= 6
    return bool(re.search(r"\b(?:%s)\b" % "|".join(LOCATION_NAMES), line or "", re.IGNORECASE))


def normalize_ocr_date_range(value):
    if not value:
        return False
    text = str(value).strip()
    text = re.sub(r"\+", " - ", text)
    text = re.sub(r"\s+", " ", text)
    match = re.search(
        r"((?:19|20)\d{2})\s*[-–—+]+\s*((?:19|20)\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return "%s - %s" % (match.group(1), match.group(2))
    match = re.search(r"\b((?:19|20)\d{2})\b", text)
    return match.group(1) if match else text


def strip_leading_skill_from_company(company):
    if not company:
        return False
    company = clean_line(company)
    for skill in (
        "Wordpress", "Photoshop", "Flash Animation", "Java Script", "Jave Script",
        "Jove Script", "HTML 5", "HTML5", "CSS",
    ):
        pattern = rf"^{re.escape(skill)}\s+"
        if re.match(pattern, company, flags=re.IGNORECASE):
            company = re.sub(pattern, "", company, flags=re.IGNORECASE).strip()
    return company or False


def strip_trailing_skill_from_title(title):
    if not title:
        return False, False
    title = clean_line(title)
    for skill in (
        "Wordpress", "Photoshop", "Flash Animation", "Java Script", "Jave Script",
        "Jove Script", "HTML 5", "HTML5", "CSS",
    ):
        pattern = rf"\s+{re.escape(skill)}\s*$"
        if re.search(pattern, title, flags=re.IGNORECASE):
            cleaned = re.sub(pattern, "", title, flags=re.IGNORECASE).strip()
            return cleaned, skill
    return title, False

def finalize_experience_row(row):
    row = dict(row or {})
    if row.get("date_range"):
        row["date_range"] = normalize_ocr_date_range(row["date_range"])
    if row.get("company"):
        row["company"] = strip_leading_skill_from_company(row["company"])
        if row["company"]:
            row["company"] = re.sub(r"\bLorom\b", "Lorem", row["company"], flags=re.IGNORECASE)
    title, _embedded_skill = strip_trailing_skill_from_title(row.get("job_title") or "")
    if title:
        row["job_title"] = title
    line, embedded_date = strip_date_from_line(row.get("job_title") or "")
    if embedded_date and not row.get("date_range"):
        row["date_range"] = embedded_date
    if line:
        row["job_title"] = line

    title, company = split_title_company(row.get("job_title") or "")
    if title:
        row["job_title"] = title
    if company and not row.get("company"):
        if not _is_skill_company(company):
            row["company"] = company

    location = row.get("location")
    if location and not re.match(r"^location\s*:", str(location), re.IGNORECASE):
        row["location"] = clean_line(str(location))
    else:
        row["location"] = extract_location_value(location or "") or False

    description = row.get("description") or ""
    if not row.get("location") and description:
        match = re.match(r"^location\s*:\s*([^\n]+)\n?(.*)$", description.strip(), re.IGNORECASE | re.DOTALL)
        if match:
            row["location"] = clean_line(match.group(1))
            description = (match.group(2) or "").strip()

    if description:
        cleaned_lines = []
        for line in description.splitlines():
            line = clean_line(line.lstrip("-•* ").strip())
            if not line:
                continue
            if re.match(r"^location\s*:", line, re.IGNORECASE):
                if not row.get("location"):
                    row["location"] = extract_location_value(line)
                continue
            cleaned_lines.append(line)
        row["description"] = normalize_description_text("\n".join(cleaned_lines)) or False

    if row.get("description") and _is_skill_only_text(row["description"]):
        row["description"] = False

    return row


def _is_skill_only_text(text):
    skill_names = (
        "Wordpress", "Photoshop", "Flash Animation", "Java Script", "Jave Script",
        "Jove Script", "HTML 5", "HTML5", "Illustrator", "InDesign", "CSS",
    )
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return False
    return all(
        any(re.search(rf"\b{re.escape(skill)}\b", line, flags=re.IGNORECASE) for skill in skill_names)
        for line in lines
    )


def parse_experience_text(experience_text):
    if not experience_text:
        return []
    lines = [clean_line(line) for line in experience_text.splitlines() if clean_line(line)]
    if not lines:
        return []

    sentence_rows = _parse_sentence_experience_lines(lines)
    blocks = _split_experience_blocks(lines)
    rows = list(sentence_rows)
    for block in blocks:
        row = finalize_experience_row(_parse_experience_block(block))
        if _is_meaningful_row(row) and not is_spurious_experience_row(row):
            rows.append(row)
    return _dedupe_rows(rows)


def _parse_sentence_experience_lines(lines):
    rows = []
    for line in lines or []:
        text = clean_line(line)
        if not text or is_resume_noise_line(text):
            continue
        lowered = text.lower()
        if not re.search(r"\b(?:currently|presently|working|worked|experience)\b", lowered):
            continue
        sentence_patterns = (
            r"^(?:currently|presently)?\s*(?:i\s+am\s+)?(?:working|worked)\s+(?:with|at|in)\s+"
            r"(?P<company>.+?)\s+as\s+(?:a|an)?\s*(?P<title>.+?)"
            r"(?:\s+from\s+(?P<date>.+?))?\.?$",
            r"^(?P<company>.+?)\s+(?P<duration>\d+(?:\.\d+)?\s*(?:year|years|month|months)[^.]*)\s+"
            r"work\s+experience\s+as\s+(?:a|an)?\s*(?P<title>.+?)\.?$",
            r"^(?P<title>.+?)\s+at\s+(?P<company>.+?)\s+(?:from\s+)?(?P<date>(?:19|20)\d{2}.*)$",
        )
        for pattern in sentence_patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            data = match.groupdict()
            company = clean_line(data.get("company") or "")
            title = clean_line(data.get("title") or "")
            date_range = clean_line(data.get("date") or data.get("duration") or "")
            company = re.sub(r"\s*,?\s*(?:Anjar|Gujarat|India|Country)\s*$", "", company, flags=re.IGNORECASE).strip()
            title = re.sub(r"\s+(?:from|since)\s+.+$", "", title, flags=re.IGNORECASE).strip()
            if not title or not company:
                continue
            row = finalize_experience_row({
                "date_range": date_range or False,
                "job_title": title,
                "company": company,
                "location": False,
                "description": text,
            })
            if _is_meaningful_row(row) and not is_spurious_experience_row(row):
                rows.append(row)
            break
    return rows


def _block_has_job_header(block):
    has_title = False
    has_date = False
    for item in block or []:
        if is_standalone_date_line(item) or line_has_date_range(item):
            has_date = True
        plain, date_range = strip_date_from_line(item)
        if date_range:
            has_date = True
        if plain and looks_like_job_title(plain):
            has_title = True
    return has_title and has_date


def _split_experience_blocks(lines):
    blocks = []
    current = []
    for line in lines:
        plain_line, line_date = strip_date_from_line(line)
        starts_new_job = False
        if current:
            if line_date and any(line_has_date_range(item) for item in current):
                starts_new_job = True
            elif (
                looks_like_job_title(plain_line)
                and not line_date
                and not is_resume_noise_line(plain_line)
                and _block_has_job_header(current)
            ):
                starts_new_job = True
        if starts_new_job:
            blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _parse_experience_block(block):
    row = {
        "date_range": False,
        "job_title": False,
        "company": False,
        "location": False,
        "description": False,
    }
    description = []
    pending = list(block)

    first_line = pending[0] if pending else ""
    first_plain, first_date = strip_date_from_line(first_line)
    if first_date and not first_plain:
        row["date_range"] = first_date
        pending = pending[1:]
    elif first_plain and (re.search(r"[-–—|]", first_plain) or looks_like_job_title(first_plain)):
        title, company = split_title_company(first_plain)
        row["job_title"] = title
        row["company"] = company
        if first_date:
            row["date_range"] = first_date
        pending = pending[1:]
    elif first_plain and looks_like_job_title(first_plain) and not first_date:
        row["job_title"] = first_plain
        pending = pending[1:]

    for line in pending:
        if is_standalone_date_line(line):
            _, line_date = strip_date_from_line(line)
            if line_date and not row.get("date_range"):
                row["date_range"] = line_date
            continue

        plain_line, line_date = strip_date_from_line(line)
        if line_date and not row.get("date_range"):
            row["date_range"] = line_date
            line = plain_line or line
            if not plain_line:
                continue

        company, location = split_company_location(line)
        if company:
            row["company"] = company
            row["location"] = location or row.get("location")
            continue

        location = extract_location_value(line)
        if location and not row.get("location"):
            row["location"] = location
            continue

        if not row.get("job_title") and looks_like_job_title(line):
            title, company = split_title_company(line)
            row["job_title"] = title
            row["company"] = company or row.get("company")
            continue

        if not row.get("company") and looks_like_company(line):
            if _is_skill_company(line):
                continue
            row["company"] = line
            continue

        if not row.get("location") and looks_like_location(line):
            row["location"] = line
            continue

        if row.get("job_title") and row.get("date_range") and (row.get("company") or row.get("location")):
            clean = clean_description_line(line.lstrip("-•* ").strip())
            if clean and not is_standalone_date_line(clean) and not looks_like_job_title(clean):
                if not split_company_location(clean)[0] and looks_like_body_text(clean):
                    description.append(clean)
                    continue

        if looks_like_body_text(line) or row.get("date_range"):
            clean = clean_description_line(line.lstrip("-•* ").strip())
            if clean and not is_standalone_date_line(clean) and looks_like_body_text(clean):
                if is_resume_noise_line(clean) or _is_skill_only_text(clean) or _is_skill_company(clean):
                    continue
                description.append(clean)
            elif clean and description and re.match(r"^(?:in|and|within|for|to|with)\b", clean, flags=re.IGNORECASE):
                description.append(clean)

    if description:
        row["description"] = "\n".join(description)
    return row


def normalize_ai_experience_rows(experience_value):
    rows = []
    for item in _as_list(experience_value):
        if isinstance(item, dict):
            rows.append(finalize_experience_row(_normalize_ai_row(item)))
        elif isinstance(item, str) and item.strip():
            rows.extend(parse_experience_text(item))
    rows = _merge_fragmented_rows(rows)
    return filter_experience_rows([row for row in rows if _is_meaningful_row(row)])


def _normalize_ai_row(row):
    description = row.get("description") or row.get("responsibilities") or row.get("details")
    if isinstance(description, list):
        description = "\n".join(str(item) for item in description if item)
    date_range = (
        row.get("date_range") or row.get("dates") or row.get("date")
        or row.get("duration") or row.get("years") or row.get("period")
    )
    job_title = row.get("job_title") or row.get("title") or row.get("role") or row.get("position")
    company = row.get("company") or row.get("employer") or row.get("organization") or row.get("employer_name")
    location = row.get("location") or row.get("place") or row.get("city")
    return {
        "date_range": _text(date_range),
        "job_title": _text(job_title),
        "company": _text(company),
        "location": _text(location),
        "description": _text(description),
    }


def merge_experience_lines(primary, fallback):
    primary = [finalize_experience_row(row) for row in (primary or [])]
    fallback = [finalize_experience_row(row) for row in (fallback or [])]
    primary = filter_experience_rows([row for row in primary if _is_meaningful_row(row)])
    fallback = filter_experience_rows([row for row in fallback if _is_meaningful_row(row)])
    if not primary:
        return _dedupe_rows(fallback)
    if not fallback:
        return _dedupe_rows(primary)

    merged = []
    used_fallback = set()
    for row in primary:
        enriched = dict(row)
        best = _best_fallback_match(enriched, fallback, used_fallback)
        if best:
            used_fallback.add(best["index"])
            for field in ("date_range", "job_title", "company", "location", "description"):
                fallback_value = best["row"].get(field)
                if not fallback_value:
                    continue
                current_value = enriched.get(field)
                if field == "description":
                    if not current_value or is_generic_description(current_value):
                        enriched[field] = fallback_value
                    elif len(str(fallback_value)) > len(str(current_value)):
                        enriched[field] = fallback_value
                elif not current_value:
                    enriched[field] = fallback_value
        merged.append(finalize_experience_row(enriched))

    for index, row in enumerate(fallback):
        if index in used_fallback:
            continue
        if not any(_rows_similar(row, existing) for existing in merged):
            merged.append(row)
    return _dedupe_rows(merged)


def _best_fallback_match(primary_row, fallback_rows, used):
    title = _normalize_key(primary_row.get("job_title"))
    company = _normalize_key(primary_row.get("company"))
    date = _normalize_key(primary_row.get("date_range"))
    best = None
    best_score = 0
    for index, row in enumerate(fallback_rows):
        if index in used:
            continue
        score = 0
        if title and title == _normalize_key(row.get("job_title")):
            score += 3
        if company and company == _normalize_key(row.get("company")):
            score += 3
        if date and date == _normalize_key(row.get("date_range")):
            score += 2
        if score > best_score:
            best_score = score
            best = {"index": index, "row": row}
    return best if best_score else None


def _rows_similar(left, right):
    if _normalize_key(left.get("date_range")) and _normalize_key(left.get("date_range")) == _normalize_key(right.get("date_range")):
        return True
    return (
        _normalize_key(left.get("job_title")) == _normalize_key(right.get("job_title"))
        and _normalize_key(left.get("company")) == _normalize_key(right.get("company"))
    )


def is_spurious_experience_row(row):
    if not row:
        return True
    combined = " ".join(
        str(row.get(field) or "")
        for field in ("date_range", "job_title", "company", "location", "description")
    )
    normalized = re.sub(r"[^a-z0-9 ]+", " ", combined.lower())
    company = re.sub(r"[^a-z0-9 ]+", " ", (row.get("company") or "").lower()).strip()
    title = re.sub(r"[^a-z0-9 ]+", " ", (row.get("job_title") or "").lower()).strip()
    if company in SPURIOUS_COMPANY_VALUES:
        return True
    if title in SPURIOUS_COMPANY_VALUES:
        return True
    if any(marker in normalized for marker in TEMPLATE_PLACEHOLDER_MARKERS):
        return True
    if "«" in (row.get("job_title") or "") or "©" in (row.get("job_title") or ""):
        return True
    if company.startswith("expertises") or " expertises " in f" {company} ":
        return True
    if re.search(r"\bcompany name\b", company) and re.search(
        r"\b(?:write your job title|beginning date)\b",
        normalized,
    ):
        return True
    if any(keyword in normalized for keyword in EDUCATION_ROW_KEYWORDS):
        if not row.get("company") or any(keyword in title for keyword in EDUCATION_ROW_KEYWORDS):
            return True
    if _is_skill_company(company):
        return True
    if row.get("job_title") and re.search(
        r"\b(?:wordpress|photoshop|java\s*script|flash\s*animation|html\s*5?)\b",
        row.get("job_title") or "",
        flags=re.IGNORECASE,
    ):
        cleaned_title = re.sub(
            r"\b(?:wordpress|photoshop|java\s*script|flash\s*animation|html\s*5?)\b",
            "",
            row.get("job_title") or "",
            flags=re.IGNORECASE,
        ).strip()
        if cleaned_title and looks_like_job_title(cleaned_title):
            return True
    if row.get("job_title") and not row.get("company") and not row.get("date_range"):
        if any(keyword in title for keyword in ("internet", "browsing", "attitude", "communication", "teamwork")):
            return True
    if not row.get("date_range") and not row.get("company"):
        if not looks_like_job_title(row.get("job_title") or ""):
            return True
    return False


def filter_experience_rows(rows):
    return [row for row in (rows or []) if not is_spurious_experience_row(row)]


def sanitize_experience_rows(rows, source_text=""):
    rows = [repair_experience_row(finalize_experience_row(dict(row or {}))) for row in (rows or [])]
    rows = filter_experience_rows([row for row in rows if _is_meaningful_row(row)])
    rows = fill_missing_experience_company(rows, source_text)
    return _dedupe_rows(rows)


def fill_missing_experience_company(rows, source_text=""):
    rows = [dict(row) for row in (rows or [])]
    pairs = []
    for row in rows:
        if row.get("company"):
            pairs.append((row["company"], row.get("location") or False))
    for line in (source_text or "").splitlines():
        company, location = split_company_location(clean_line(line))
        if company and looks_like_company(company):
            pairs.append((company, location or False))
    if not pairs:
        return rows
    default_company, default_location = max(set(pairs), key=pairs.count)
    for row in rows:
        if not row.get("company"):
            row["company"] = default_company
        if not row.get("location") and default_location:
            row["location"] = default_location
    return [finalize_experience_row(row) for row in rows]


def realign_experience_descriptions(rows, experience_text):
    if not rows or not experience_text:
        return rows
    lines = [clean_line(line) for line in experience_text.splitlines() if clean_line(line)]
    blocks = _split_experience_blocks(lines)
    rows_by_date = {}
    for row in rows:
        date_key = re.sub(r"\D", "", row.get("date_range") or "")[:8]
        if date_key:
            rows_by_date[date_key] = dict(row)
    for block in blocks:
        if not block:
            continue
        first_date = extract_date_range(block[0]) or (
            extract_date_range(block[1]) if len(block) > 1 else False
        )
        date_key = re.sub(r"\D", "", first_date or "")[:8]
        if not date_key or date_key not in rows_by_date:
            continue
        desc_lines = []
        past_header = False
        for line in block:
            plain, line_date = strip_date_from_line(line)
            if line_date and not past_header:
                past_header = True
                continue
            if not past_header:
                continue
            if looks_like_job_title(plain or line) and not looks_like_body_text(line):
                continue
            company, _location = split_company_location(line)
            if company and looks_like_company(company):
                continue
            if _is_skill_company(line):
                continue
            clean = clean_description_line(line)
            if clean and looks_like_body_text(clean):
                desc_lines.append(clean)
        if desc_lines:
            rows_by_date[date_key]["description"] = normalize_description_text("\n".join(desc_lines))
    return [finalize_experience_row(row) for row in rows]


def _is_skill_company(company):
    normalized = re.sub(r"[^a-z0-9 ]+", " ", (company or "").lower()).strip()
    if not normalized:
        return False
    return normalized in SKILL_FALSE_COMPANIES or any(
        normalized == skill or normalized.startswith(skill + " ")
        for skill in SKILL_FALSE_COMPANIES
    )


def repair_experience_row(row):
    row = dict(row or {})
    title = clean_line(row.get("job_title") or "")
    title = re.sub(r"^\++\s*", "", title)
    title, _skill = strip_trailing_skill_from_title(title)
    for skill in ("Wordpress", "Photoshop", "Flash Animation", "Java Script", "Jave Script", "Jove Script"):
        title = re.sub(rf"\s+{re.escape(skill)}\s*$", "", title, flags=re.IGNORECASE).strip()
    row["job_title"] = title or False

    company = clean_line(row.get("company") or "")
    location = clean_line(row.get("location") or "")
    company = re.sub(r"\s*\(\s*\)\s*$", "", company).strip()
    if company.rstrip().endswith("-"):
        company = company.rstrip(" -")
    if _is_skill_company(company):
        if location:
            split_company, split_location = split_company_location(location)
            if split_company and looks_like_company(split_company):
                row["company"] = split_company
                row["location"] = split_location or False
            elif looks_like_company(location):
                row["company"] = location
                row["location"] = False
            else:
                row["company"] = False
        else:
            row["company"] = False
    elif company:
        row["company"] = company

    description = row.get("description") or ""
    if description:
        cleaned_lines = []
        for line in description.splitlines():
            line = re.sub(r"^ni\s+", "", line.strip(), flags=re.IGNORECASE)
            line = clean_line(line)
            if line:
                cleaned_lines.append(line)
        description = "\n".join(cleaned_lines)
        row["description"] = False if _is_skill_only_text(description) else normalize_description_text(description) or False

    if row.get("date_range"):
        row["date_range"] = normalize_ocr_date_range(row["date_range"])

    return finalize_experience_row(row)


def _is_meaningful_row(row):
    if not row:
        return False
    if looks_like_description(row.get("company") or ""):
        return bool(row.get("job_title") and row.get("date_range"))
    return bool((row.get("job_title") or row.get("company")) and (row.get("date_range") or row.get("description")))


def _normalize_key(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _merge_fragmented_rows(rows):
    if len(rows) < 2:
        return rows
    merged = []
    index = 0
    while index < len(rows):
        row = dict(rows[index])
        if index + 1 < len(rows):
            nxt = rows[index + 1]
            combined = _try_merge_fragment_pair(row, nxt)
            if combined:
                merged.append(finalize_experience_row(combined))
                index += 2
                continue
        merged.append(row)
        index += 1
    return merged


def _try_merge_fragment_pair(left, right):
    left = dict(left or {})
    right = dict(right or {})
    left_has_title = bool(left.get("job_title") or left.get("company"))
    right_has_title = bool(right.get("job_title") or right.get("company"))
    left_has_date = bool(left.get("date_range"))
    right_has_date = bool(right.get("date_range"))
    if left_has_title and not left_has_date and right_has_date and not right_has_title:
        return _combine_experience_fragments(left, right)
    if right_has_title and not right_has_date and left_has_date and not left_has_title:
        return _combine_experience_fragments(right, left)
    return False


def _combine_experience_fragments(title_row, detail_row):
    combined = dict(title_row)
    for field in ("date_range", "company", "location", "description"):
        if not combined.get(field) and detail_row.get(field):
            combined[field] = detail_row[field]
    if not combined.get("company"):
        _, company = split_title_company(detail_row.get("job_title") or "")
        combined["company"] = combined.get("company") or company
    return combined


def _dedupe_rows(rows):
    rows = _merge_fragmented_rows(rows)
    grouped = {}
    for row in rows:
        row = dict(row or {})
        title_key = _normalize_key(row.get("job_title"))
        company_key = _normalize_key(row.get("company"))
        if not title_key:
            continue
        group_key = (title_key, company_key)
        existing = grouped.get(group_key)
        if not existing:
            grouped[group_key] = row
            continue
        grouped[group_key] = _merge_duplicate_experience_row(existing, row)
    return [finalize_experience_row(row) for row in grouped.values()]


def _merge_duplicate_experience_row(left, right):
    merged = dict(left)
    for field in ("date_range", "job_title", "company", "location", "description"):
        left_value = merged.get(field)
        right_value = right.get(field)
        if not left_value and right_value:
            merged[field] = right_value
        elif field == "date_range" and left_value and right_value:
            merged[field] = _prefer_date_range(left_value, right_value)
        elif field == "description" and left_value and right_value:
            merged[field] = right_value if len(str(right_value)) > len(str(left_value)) else left_value
        elif field == "location" and right_value and (not left_value or len(str(right_value)) > len(str(left_value))):
            merged[field] = right_value
    return merged


def _prefer_date_range(left, right):
    left_digits = re.sub(r"\D", "", left or "")
    right_digits = re.sub(r"\D", "", right or "")
    if len(left_digits) >= 8 and len(right_digits) < 8:
        return left
    if len(right_digits) >= 8 and len(left_digits) < 8:
        return right
    return left if len(str(left)) >= len(str(right)) else right


def _as_list(value):
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def rows_to_text(rows, fields_order):
    chunks = []
    for row in rows:
        chunks.append("\n".join(row.get(field) for field in fields_order if row.get(field)))
    return "\n\n".join(chunks) or False


def _text(value):
    if value in (None, False, ""):
        return False
    if isinstance(value, list):
        values = [_text(item) for item in value]
        values = [item for item in values if item]
        return "\n".join(values) or False
    return str(value).strip() or False
