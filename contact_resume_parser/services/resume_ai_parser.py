"""AI resume structuring: Ollama, OpenAI, and optional HuggingFace NER."""

import json
import os
import re

from odoo.exceptions import UserError
from odoo.tools.translate import _

from .experience_parser import filter_experience_rows, normalize_ai_experience_rows

KNOWN_LANGUAGES = (
    "English", "Hindi", "Marathi", "Tamil", "Telugu", "Kannada", "Malayalam",
    "Bengali", "Gujarati", "Punjabi", "Urdu", "French", "Spanish", "German",
    "Arabic", "Chinese", "Japanese", "Korean", "Portuguese", "Italian", "Russian",
)
SOFT_SKILL_KEYWORDS = (
    "Communication Skills", "Teamwork", "Adaptability", "Problem Solving",
    "Time Management", "Organizational Skills", "Initiative", "Dependability",
    "Positive Attitude",
)
HARD_SKILL_KEYWORDS = (
    "Computer Skills", "Internet Browsing", "Email Communication", "File Management",
    "Angular", "Vue.js", "GraphQL", "MongoDB", "CI/CD", "Flask", ".NET",
    "REST API", "HTML5", "Webhooks", "Pandas", "Jenkins", "Laravel",
    "TensorFlow", "Postman", "Selenium", "PHP", "Azure", "Django",
    "Node.js", "Kubernetes", "React.js", "Socket.io", "Linux",
    "MS Word", "MS-Word", "Excel", "PowerPoint", "Power Point", "Tally",
    "SAP", "ERP", "GST", "Accounting", "Payroll", "QuickBooks",
)

_HF_PIPELINE = None


class ResumeAIParserService:
    """Bridge between extracted resume text and structured Odoo fields."""

    def __init__(self, env):
        self.env = env

    def parse(self, raw_text, fallback_details=None):
        fallback_details = dict(fallback_details or {})
        errors = []
        for provider_config in self._provider_configs():
            try:
                ai_data = self._call_provider(raw_text, provider_config)
                ai_details = self._normalize_details(ai_data)
            except Exception as error:
                errors.append("%s: %s" % (provider_config["label"], error))
                continue

            if not self._has_meaningful_result(ai_details):
                errors.append("%s: %s" % (provider_config["label"], _("empty AI response")))
                continue

            merged = dict(fallback_details)
            merged.update({key: value for key, value in ai_details.items() if value})
            merged["_ai_applied"] = True
            merged["message"] = _(
                "Resume extracted via %s. Please review before using the details."
            ) % provider_config["label"]
            return merged

        if errors:
            fallback_details["message"] = _(
                "AI parser unavailable (%s). Regex extraction was used."
            ) % " | ".join(errors)
        else:
            fallback_details["message"] = _(
                "AI parser unavailable. Install Ollama or configure HuggingFace/OpenAI in Settings > Resume Parser."
            )
        return fallback_details

    def _provider_configs(self):
        IrConfig = self.env["ir.config_parameter"].sudo()
        provider_mode = IrConfig.get_param("contact_resume_parser.ai_provider") or "auto"
        configs = []

        if provider_mode in ("auto", "huggingface"):
            hf_model = IrConfig.get_param("contact_resume_parser.huggingface_model")
            if hf_model:
                configs.append({
                    "label": "HuggingFace (%s)" % hf_model,
                    "name": "huggingface",
                    "model": hf_model,
                })

        if provider_mode in ("auto", "ollama"):
            ollama_url = (IrConfig.get_param("contact_resume_parser.ollama_url") or "http://127.0.0.1:11434").rstrip("/")
            ollama_model = (
                IrConfig.get_param("contact_resume_parser.ollama_model")
                or self._detect_ollama_model(ollama_url)
                or "my-odoo-ai:latest"
            )
            configs.append({
                "label": "Ollama (%s)" % ollama_model,
                "name": "ollama",
                "endpoint": "%s/v1/chat/completions" % ollama_url,
                "ollama_url": ollama_url,
                "api_key": "ollama",
                "model": ollama_model,
            })

        if provider_mode in ("auto", "openai"):
            api_key = os.environ.get("OPENAI_API_KEY") or IrConfig.get_param("contact_resume_parser.openai_api_key")
            if api_key:
                configs.append({
                    "label": "OpenAI",
                    "name": "openai",
                    "endpoint": (
                        IrConfig.get_param("contact_resume_parser.openai_endpoint")
                        or os.environ.get("OPENAI_CHAT_COMPLETIONS_ENDPOINT")
                        or "https://api.openai.com/v1/chat/completions"
                    ),
                    "api_key": api_key,
                    "model": (
                        IrConfig.get_param("contact_resume_parser.openai_model")
                        or os.environ.get("OPENAI_MODEL")
                        or "gpt-4o-mini"
                    ),
                })

        if provider_mode == "ollama":
            configs = [c for c in configs if c["name"] == "ollama"]
        elif provider_mode == "openai":
            configs = [c for c in configs if c["name"] == "openai"]
        elif provider_mode == "huggingface":
            configs = [c for c in configs if c["name"] == "huggingface"]
        elif provider_mode == "none":
            configs = []
        return configs

    def _call_provider(self, raw_text, provider_config):
        name = provider_config.get("name")
        if name == "huggingface":
            return self._call_huggingface_ner(raw_text, provider_config["model"])
        if name == "ollama":
            return self._call_ollama(raw_text, provider_config)
        return self._call_openai_compatible(raw_text, provider_config)

    def _call_huggingface_ner(self, raw_text, model_name):
        global _HF_PIPELINE
        try:
            from transformers import pipeline
        except ImportError:
            raise UserError(_(
                "Install HuggingFace dependencies on the Odoo server: pip install transformers torch"
            ))

        if _HF_PIPELINE is None or getattr(_HF_PIPELINE, "_model_name", None) != model_name:
            _HF_PIPELINE = pipeline("ner", model=model_name, aggregation_strategy="simple")
            _HF_PIPELINE._model_name = model_name

        entities = _HF_PIPELINE(raw_text[:8000])
        return self._ner_entities_to_json(entities, raw_text)

    def _ner_entities_to_json(self, entities, raw_text):
        result = {
            "name": None,
            "job_title": None,
            "email": self._normalize_email(self._first_match(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", raw_text)),
            "phone": self._extract_phone(raw_text),
            "address": None,
            "skills": [],
            "experience": [],
            "education": [],
        }
        buckets = {
            "NAME": "name",
            "PER": "name",
            "EMAIL": "email",
            "PHONE": "phone",
            "SKILLS": "skills",
            "EXPERIENCE": "experience",
            "EDUCATION": "education",
            "ORG": "experience",
            "LOC": "address",
        }
        for entity in entities or []:
            label = (entity.get("entity_group") or entity.get("entity") or "").replace("B-", "").replace("I-", "")
            word = (entity.get("word") or "").strip().replace("##", "")
            if not word:
                continue
            bucket = buckets.get(label.upper())
            if bucket == "name" and not result["name"]:
                result["name"] = word
            elif bucket == "email" and not result["email"]:
                result["email"] = word
            elif bucket == "phone" and not result["phone"]:
                result["phone"] = word
            elif bucket == "address" and not result["address"]:
                result["address"] = word
            elif bucket == "skills":
                result["skills"].append(word)
            elif bucket == "experience":
                result["experience"].append({"company": word, "job_title": None, "date_range": None, "location": None, "description": None})
            elif bucket == "education":
                result["education"].append({"institution": word, "degree": None, "date_range": None, "location": None, "description": None})
        return result

    def _call_ollama(self, raw_text, provider_config):
        import requests

        ollama_url = provider_config.get("ollama_url") or "http://127.0.0.1:11434"
        response = requests.post(
            "%s/api/chat" % ollama_url.rstrip("/"),
            headers={"Content-Type": "application/json"},
            json={
                "model": provider_config["model"],
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You extract resume data for an HR agency. Return only valid JSON. "
                            "Use null or [] when a value is missing. Do not invent values."
                        ),
                    },
                    {"role": "user", "content": self._prompt(raw_text)},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            },
            timeout=60,
        )
        if response.status_code >= 400:
            return self._call_openai_compatible(raw_text, provider_config)
        content = (response.json().get("message") or {}).get("content") or ""
        if not content:
            raise UserError(_("Ollama returned an empty response."))
        return self._parse_json(content)

    def _call_openai_compatible(self, raw_text, provider_config):
        import requests

        response = requests.post(
            provider_config["endpoint"],
            headers={
                "Authorization": "Bearer %s" % provider_config["api_key"],
                "Content-Type": "application/json",
            },
            json={
                "model": provider_config["model"],
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You extract resume data for an HR agency. Return only valid JSON. "
                            "Use null or [] when a value is missing. Do not invent values."
                        ),
                    },
                    {"role": "user", "content": self._prompt(raw_text)},
                ],
            },
            timeout=90,
        )
        if response.status_code >= 400:
            raise UserError(_("AI API error %s: %s") % (response.status_code, response.text[:500]))
        content = response.json()["choices"][0]["message"]["content"]
        return self._parse_json(content)

    def _prompt(self, raw_text):
        return """Extract structured data from this resume text. The text may come from OCR and contain layout noise.

Return JSON with exactly these keys:
name, job_title, email, phone, address, website, linkedin, social_media,
summary, skills, hard_skills, soft_skills, languages, certifications, hobbies,
education, experience.

Rules:
- Separate languages from technical skills and soft skills.
- education: array of {date_range, degree, institution, location, description}.
- experience: array of {date_range, job_title, company, location, description}. Use [] if the resume has no work history.
- Do not put education, hobbies, skills, or languages into experience.
- Put company name in company, never inside job_title (e.g. title=DevOps Engineer, company=Mphasis).
- Put city in location only (e.g. Hyderabad), never prefix with "Location:" inside description.
- date_range examples: "Jan 2020 - Present", "2016 - 2019", "June 2017 - Dec 2019".
- Include paragraph text under each job or education entry in description. Copy the text exactly as it appears under that specific job or degree; do not merge responsibilities from other jobs.
- hobbies: list interests from INTERESTS/HOBBIES section. If the section heading exists but icon labels were not OCR'd, use common creative-template interests: Football, Music, Photography, Running.
- Use null or [] for missing values.

Resume text:
%s""" % (raw_text or "")[:14000]

    @staticmethod
    def _parse_json(content):
        content = (content or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        return json.loads(content)

    def _normalize_details(self, data):
        data = data or {}
        languages = self._join_list(data.get("languages"))
        skills = self._join_list(data.get("skills"))
        hard_skills = self._join_list(data.get("hard_skills"))
        soft_skills = self._join_list(data.get("soft_skills"))
        languages, skills, hard_skills, soft_skills = self._reclassify_skills(
            languages, skills, hard_skills, soft_skills
        )
        skills = self.build_combined_skills(hard_skills, soft_skills, skills)
        education_lines = [
            self._normalize_row(row, {
                "date_range": ("date_range", "dates", "date"),
                "degree": ("degree", "qualification", "course"),
                "institution": ("institution", "school", "college", "university"),
                "location": ("location", "place"),
                "description": ("description", "details"),
            })
            for row in self._as_list(data.get("education"))
            if isinstance(row, dict)
        ]
        experience_source = []
        for key in ("experience", "work_experience", "employment", "work_history", "positions"):
            experience_source.extend(self._as_list(data.get(key)))
        experience_lines = filter_experience_rows(normalize_ai_experience_rows(experience_source))
        education_lines = [row for row in education_lines if any(row.values())]
        experience_lines = [row for row in experience_lines if any(row.values())]
        languages = self._format_languages(data.get("languages")) or languages
        return {
            "name": self._text(data.get("name")),
            "job_title": self._text(data.get("job_title")),
            "email": self._normalize_email(self._text(data.get("email"))),
            "phone": self._text(data.get("phone")),
            "address": self._text(data.get("address")),
            "website": self._text(data.get("website")),
            "linkedin": self._text(data.get("linkedin")),
            "social_media": self._format_social(data.get("social_media")),
            "summary": self._text(data.get("summary")),
            "skills": skills,
            "hard_skills": hard_skills,
            "soft_skills": soft_skills,
            "languages": languages,
            "certifications": self._join_list(data.get("certifications")),
            "hobbies": self._join_list(data.get("hobbies")),
            "education": self._rows_to_text(education_lines, ("date_range", "degree", "institution", "location", "description")),
            "experience": self._rows_to_text(experience_lines, ("date_range", "job_title", "company", "location", "description")),
            "education_lines": education_lines,
            "experience_lines": experience_lines,
        }

    def _has_meaningful_result(self, details):
        return any(
            details.get(field)
            for field in ("name", "email", "phone", "skills", "education_lines", "experience_lines")
        )

    @staticmethod
    def _detect_ollama_model(ollama_url):
        try:
            import requests
            response = requests.get("%s/api/tags" % ollama_url.rstrip("/"), timeout=3)
            response.raise_for_status()
            models = response.json().get("models") or []
            if models:
                return models[0].get("name") or models[0].get("model")
        except Exception:
            return False
        return False

    @staticmethod
    def _normalize_email(email):
        if not email:
            return False
        email = str(email).strip().lower()
        email = re.sub(r"\s+", "", email)
        if "@" not in email:
            match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", email)
            email = match.group(0) if match else email
        if "@" not in email:
            return False
        local, _, domain = email.partition("@")
        domain = domain.strip(".")
        if local.lower().endswith(".com"):
            local = local[:-4]
        for junk in ("indiajer", "indiojer", "indiater"):
            if junk != local.lower():
                local = re.sub(junk, "", local, flags=re.IGNORECASE)
                domain = re.sub(junk, "", domain, flags=re.IGNORECASE)
        local = local.strip(".@ ")
        domain = domain.strip(".@ ")
        if re.search(r"\.(com|org|net|co|in)$", local, flags=re.IGNORECASE):
            local = re.sub(r"\.(com|org|net|co|in)$", "", local, flags=re.IGNORECASE)
        local = re.sub(r"[^a-z0-9._+-]", "", local)
        if not local or not domain:
            return False
        normalized = "%s@%s" % (local, domain)
        return normalized if re.match(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$", normalized) else False

    @staticmethod
    def _first_match(pattern, text):
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        return match.group(0).rstrip(".") if match else False

    @staticmethod
    def _extract_phone(text):
        for candidate in re.findall(r"(?:\+?\d[\d\s().-]{7,}\d)", text or ""):
            if re.search(r"\b(?:19|20)\d{2}\b", candidate):
                continue
            digits = re.sub(r"\D", "", candidate)
            if 8 <= len(digits) <= 15:
                return candidate.strip()
        return False

    @staticmethod
    def _as_list(value):
        if not value:
            return []
        return value if isinstance(value, list) else [value]

    @staticmethod
    def _text(value):
        if value in (None, False, ""):
            return False
        if isinstance(value, list):
            return ResumeAIParserService._join_list(value)
        return str(value).strip() or False

    @staticmethod
    def _join_list(value):
        values = []
        for item in ResumeAIParserService._as_list(value):
            if isinstance(item, dict):
                text = ResumeAIParserService._format_language_item(item)
            else:
                text = ResumeAIParserService._text(item)
            if text and text not in values:
                values.append(text)
        return "\n".join(values) or False

    @staticmethod
    def _format_language_item(item):
        if not isinstance(item, dict):
            return ResumeAIParserService._text(item)
        language = ResumeAIParserService._text(
            item.get("language") or item.get("name") or item.get("lang")
        )
        level = ResumeAIParserService._text(
            item.get("level") or item.get("proficiency") or item.get("fluency")
        )
        if language and level and level.lower() not in {"none", "null"}:
            return "%s (%s)" % (language, level)
        return language

    @staticmethod
    def _format_languages(value):
        values = []
        for item in ResumeAIParserService._as_list(value):
            text = ResumeAIParserService._format_language_item(item) if isinstance(item, dict) else ResumeAIParserService._text(item)
            if text and text not in values:
                values.append(text)
        return "\n".join(values) or False

    @staticmethod
    def _format_social(value):
        rows = []
        for item in ResumeAIParserService._as_list(value):
            if isinstance(item, dict):
                platform = ResumeAIParserService._text(item.get("platform") or item.get("name"))
                url = ResumeAIParserService._text(item.get("url") or item.get("link"))
                if platform and url:
                    rows.append("%s: %s" % (platform, url))
            else:
                text = ResumeAIParserService._text(item)
                if text:
                    rows.append(text)
        return "\n".join(rows) or False

    @staticmethod
    def _normalize_row(row, field_aliases):
        result = {}
        for target, aliases in field_aliases.items():
            value = False
            for alias in aliases:
                if alias in row:
                    value = row.get(alias)
                    break
            result[target] = ResumeAIParserService._text(value)
        return result

    @staticmethod
    def _rows_to_text(rows, fields_order):
        chunks = []
        for row in rows:
            chunks.append("\n".join(row.get(field) for field in fields_order if row.get(field)))
        return "\n\n".join(chunks) or False

    @staticmethod
    def _reclassify_skills(languages, skills, hard_skills, soft_skills):
        language_values, skill_values, hard_values, soft_values = [], [], [], []

        def is_language(text):
            normalized = re.sub(r"[^a-z0-9 ]+", "", text.lower())
            return any(lang.lower() in normalized for lang in KNOWN_LANGUAGES)

        def is_hard(text):
            normalized = re.sub(r"[^a-z0-9 ]+", "", text.lower())
            hard = (
                "python", "java", "javascript", "html", "css", "sql", "photoshop",
                "computer skills", "internet browsing", "email communication", "file management",
            )
            return any(keyword in normalized for keyword in hard) or any(
                re.search(rf"\b{re.escape(skill)}\b", text or "", flags=re.IGNORECASE)
                for skill in HARD_SKILL_KEYWORDS
            )

        def is_soft(text):
            normalized = re.sub(r"\s+", " ", text or "")
            return any(
                re.search(rf"\b{re.escape(skill)}\b", normalized, flags=re.IGNORECASE)
                for skill in SOFT_SKILL_KEYWORDS
            )

        for bucket, target in ((languages, language_values), (skills, skill_values), (hard_skills, hard_values), (soft_skills, soft_values)):
            for line in (bucket or "").splitlines():
                clean = line.strip()
                if not clean:
                    continue
                if is_language(clean) and clean not in language_values:
                    language_values.append(clean)
                elif is_hard(clean) and clean not in hard_values:
                    hard_values.append(clean)
                elif is_soft(clean) and clean not in soft_values:
                    soft_values.append(clean)
                elif ResumeAIParserService.is_valid_skill_line(clean) and clean not in skill_values:
                    skill_values.append(clean)
        return (
            "\n".join(language_values) or False,
            "\n".join(skill_values) or False,
            "\n".join(hard_values) or False,
            "\n".join(soft_values) or False,
        )

    @staticmethod
    def _normalize_skill_heading(text):
        normalized = re.sub(r"[^a-z0-9 ]+", "", (text or "").lower())
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def is_valid_skill_line(text):
        clean = re.sub(r"^[^\w#(+]+", "", (text or "").strip())
        clean = re.sub(r"\s+", " ", clean).strip(" @-|")
        if not clean or len(clean) > 60:
            return False
        normalized = ResumeAIParserService._normalize_skill_heading(clean)
        reject_keywords = (
            "career objective", "objective", "eager", "promising career", "entry level",
            "looking for", "contribute", "administration", "enthusiastic individual",
            "personal skills", "technical skills", "hobbies", "education", "experience",
            "languages", "certification", "summary", "profile", "whether", "any other field",
        )
        if any(keyword in normalized for keyword in reject_keywords):
            return False
        if re.search(r"\b(?:19|20)\d{2}\s*[-–—+]", clean):
            return False
        if normalized in {"lead generation", "sales forecasting", "vendor management"}:
            return True
        title_words = (
            "manager", "designer", "director", "developer", "engineer", "analyst",
            "consultant", "specialist", "executive", "intern", "lead", "architect",
            "coordinator", "officer", "associate", "supervisor", "technician",
        )
        if any(word in normalized for word in title_words):
            return False
        if clean.count(".") >= 2 or (clean.count(".") == 1 and len(clean) > 40):
            return False
        if re.search(r"\b(?:am|is|are|was|were|have|has|will|can|where)\b", normalized) and len(clean.split()) > 5:
            return False
        if any(
            re.search(rf"\b{re.escape(skill)}\b", clean, flags=re.IGNORECASE)
            for skill in SOFT_SKILL_KEYWORDS + HARD_SKILL_KEYWORDS
        ):
            return True
        words = clean.split()
        return 1 <= len(words) <= 5 and not re.search(
            r"\b(?:the|a|an|for|where|whether|any|other|team|gain|valuable)\b",
            normalized,
        )

    @staticmethod
    def build_combined_skills(hard_skills, soft_skills, extra_skills=False):
        values = []
        seen = set()
        for source in (soft_skills, hard_skills, extra_skills):
            for line in (source or "").splitlines():
                clean = re.sub(r"^[^\w#(+]+", "", (line or "").strip())
                clean = re.sub(r"\s+", " ", clean).strip(" @-|")
                if not clean or not ResumeAIParserService.is_valid_skill_line(clean):
                    continue
                key = clean.lower()
                if key in seen:
                    continue
                seen.add(key)
                values.append(clean)
        return "\n".join(values) or False
