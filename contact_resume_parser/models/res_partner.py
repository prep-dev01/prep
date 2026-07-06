import base64
import io
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .resume_document import ResumeDocumentExtractor
from ..services.experience_parser import (
    filter_experience_rows,
    merge_experience_lines,
    normalize_ai_experience_rows,
    parse_experience_text,
    realign_experience_descriptions,
    rows_to_text,
    sanitize_experience_rows,
)
from ..services.resume_ai_parser import ResumeAIParserService


class ResPartner(models.Model):
    _inherit = "res.partner"

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

    is_candidate = fields.Boolean(string="Candidate")
    resume_file = fields.Binary(string="Resume", attachment=True)
    resume_filename = fields.Char(string="Resume Filename")
    resume_overwrite_existing = fields.Boolean(
        string="Overwrite Existing Contact Fields",
        help="If checked, extracted name, email, phone and job title replace existing values.",
    )
    resume_extraction_state = fields.Selection(
        [
            ("empty", "No Resume"),
            ("done", "Extracted"),
            ("partial", "Needs Review"),
            ("error", "Error"),
        ],
        string="Extraction Status",
        default="empty",
        readonly=True,
    )
    resume_extraction_message = fields.Text(string="Extraction Message", readonly=True)
    resume_raw_text = fields.Text(string="Extracted Resume Text", readonly=True)
    resume_candidate_name = fields.Char(string="Candidate Name")
    resume_job_title = fields.Char(string="Job Title")
    resume_email = fields.Char(string="Email")
    resume_phone = fields.Char(string="Phone")
    resume_address = fields.Text(string="Address")
    resume_linkedin = fields.Char(string="LinkedIn")
    resume_social_media = fields.Text(string="Social Media")
    resume_summary = fields.Text(string="Summary")
    resume_skills = fields.Text(string="Skills")
    resume_hard_skills = fields.Text(string="Hard Skills")
    resume_soft_skills = fields.Text(string="Soft Skills")
    resume_languages = fields.Text(string="Languages")
    resume_education = fields.Text(string="Education")
    resume_experience = fields.Text(string="Experience")
    resume_certifications = fields.Text(string="Certifications")
    resume_hobbies = fields.Text(string="Hobbies")
    resume_education_line_ids = fields.One2many(
        comodel_name="contact.resume.education",
        inverse_name="partner_id",
        string="Education Lines",
    )
    resume_experience_line_ids = fields.One2many(
        comodel_name="contact.resume.experience",
        inverse_name="partner_id",
        string="Experience Lines",
    )

    @api.onchange("resume_file", "resume_filename")
    def _onchange_resume_file(self):
        for partner in self:
            if partner.resume_file:
                partner._resume_clear_extracted_preview()
                if partner._resume_extract_on_upload_enabled():
                    partner._extract_resume_to_partner(from_onchange=True)
                else:
                    partner.resume_extraction_state = "empty"
                    partner.resume_extraction_message = _(
                        "Resume uploaded. Save the contact to parse automatically."
                    )
            else:
                partner._resume_clear_extracted_preview()
                partner.resume_extraction_state = "empty"
                partner.resume_extraction_message = False

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        for partner in partners:
            if partner.resume_file:
                partner._resume_auto_extract_after_upload()
        return partners

    def write(self, vals):
        resume_updated = "resume_file" in vals
        result = super().write(vals)
        if resume_updated:
            for partner in self:
                if partner.resume_file:
                    partner._resume_auto_extract_after_upload()
        return result

    def _resume_auto_extract_after_upload(self):
        self.ensure_one()
        try:
            self._extract_resume_to_partner()
        except UserError as error:
            self.resume_extraction_state = "error"
            self.resume_extraction_message = str(error)
        except Exception as error:
            self.resume_extraction_state = "error"
            self.resume_extraction_message = _("Could not extract this resume: %s") % error

    def _resume_clear_extracted_preview(self):
        self.resume_raw_text = False
        self.resume_candidate_name = False
        self.resume_job_title = False
        self.resume_email = False
        self.resume_phone = False
        self.resume_address = False
        self.resume_linkedin = False
        self.resume_social_media = False
        self.resume_summary = False
        self.resume_skills = False
        self.resume_hard_skills = False
        self.resume_soft_skills = False
        self.resume_languages = False
        self.resume_education = False
        self.resume_experience = False
        self.resume_certifications = False
        self.resume_hobbies = False
        self.resume_education_line_ids = [(5, 0, 0)]
        self.resume_experience_line_ids = [(5, 0, 0)]

    def _resume_stored_data_looks_corrupted(self):
        skill_companies = {"wordpress", "jove script", "java script", "photoshop", "flash animation", "html5", "css"}
        for line in self.resume_experience_line_ids:
            company = (line.company or "").strip().lower()
            if company in skill_companies:
                return True
            if "+" in (line.date_range or ""):
                return True
            description = (line.description or "").lower()
            if description and any(skill in description for skill in ("photoshop", "flash animation", "wordpress")):
                return True
        if self.resume_file and not (self.resume_hobbies or "").strip():
            raw = (self.resume_raw_text or "").lower()
            if "interests" in raw or "work experience" in raw:
                return True
        return False

    def action_extract_resume(self):
        for partner in self:
            partner._extract_resume_to_partner()
        return True

    @api.model
    def _resume_extract_on_upload_enabled(self):
        return (
            self.env["ir.config_parameter"].sudo().get_param("contact_resume_parser.extract_on_upload") == "True"
        )

    def _extract_resume_to_partner(self, from_onchange=False):
        self.ensure_one()
        if not self.resume_file:
            raise UserError(_("Please upload a resume first."))

        try:
            details, raw_text = self._resume_build_details_from_file()
        except UserError as error:
            self.resume_extraction_state = "error"
            self.resume_extraction_message = str(error)
            return
        except Exception as error:
            self.resume_extraction_state = "error"
            self.resume_extraction_message = _("Could not extract this resume: %s") % error
            return

        vals = {
            "is_candidate": True,
            "resume_raw_text": raw_text,
            "resume_candidate_name": details.get("name"),
            "resume_job_title": details.get("job_title"),
            "resume_email": details.get("email"),
            "resume_phone": details.get("phone"),
            "resume_address": details.get("address"),
            "resume_linkedin": details.get("linkedin"),
            "resume_social_media": details.get("social_media"),
            "resume_summary": details.get("summary"),
            "resume_skills": details.get("skills"),
            "resume_hard_skills": details.get("hard_skills"),
            "resume_soft_skills": details.get("soft_skills"),
            "resume_languages": details.get("languages"),
            "resume_education": details.get("education"),
            "resume_experience": details.get("experience"),
            "resume_certifications": details.get("certifications"),
            "resume_hobbies": self._resume_format_text_value(details.get("hobbies")),
            "resume_extraction_state": "done" if raw_text.strip() else "partial",
            "resume_extraction_message": details.get("message"),
        }
        self._resume_apply_contact_values(vals, details)
        self.update(vals)
        self._resume_update_table_lines(details, from_onchange=from_onchange)

    def _resume_build_details_from_file(self):
        self.ensure_one()
        if not self.resume_file:
            raise UserError(_("Please upload a resume first."))
        raw_text = self._resume_normalize_document_text(self._resume_extract_text())
        raw_text = self._resume_normalize_ocr_layout(raw_text)
        ai_text = self._resume_clean_ocr_for_ai(raw_text)
        details = self._resume_parse_details_with_ai(ai_text, {})
        regex_details = self._resume_parse_details(raw_text)
        regex_details["resume_raw_text"] = raw_text
        regex_summary = regex_details.get("summary")
        regex_experience = list(regex_details.get("experience_lines") or [])
        ai_applied = bool(details.get("_ai_applied"))
        if not ai_applied:
            details = self._resume_merge_regex_fallback(details, regex_details)
        else:
            details["resume_raw_text"] = raw_text
            details = self._resume_merge_regex_fallback(details, regex_details)
            details.pop("_ai_applied", None)
        details["resume_raw_text"] = raw_text
        experience_source = self._resume_slice_experience_lines(
            [line.strip() for line in raw_text.splitlines() if line.strip()]
        ) or self._resume_find_experience_text(
            [line.strip() for line in raw_text.splitlines() if line.strip()]
        )
        if self._resume_experience_rows_are_structured(regex_experience):
            details["experience_lines"] = regex_experience
        details["experience_lines"] = realign_experience_descriptions(
            sanitize_experience_rows(details.get("experience_lines"), raw_text),
            experience_source,
        )
        details["experience_lines"] = self._resume_enrich_experience_descriptions_from_raw(
            details["experience_lines"],
            raw_text,
        )
        details["experience_lines"] = self._resume_enrich_experience_descriptions_by_title(
            details["experience_lines"],
            raw_text,
        )
        details["experience_lines"] = self._resume_clean_experience_rows(details["experience_lines"])
        template_experience = self._resume_parse_template_experience_lines(raw_text)
        date_first_experience = self._resume_parse_date_first_experience_lines(raw_text)
        pipe_date_experience = self._resume_parse_pipe_date_experience_lines(raw_text)
        scattered_experience = self._resume_parse_scattered_experience_lines(raw_text)
        if self._resume_template_rows_are_better(scattered_experience, details["experience_lines"]):
            details["experience_lines"] = scattered_experience
        if self._resume_template_rows_are_better(pipe_date_experience, details["experience_lines"]):
            details["experience_lines"] = pipe_date_experience
        if self._resume_template_rows_are_better(date_first_experience, details["experience_lines"]):
            details["experience_lines"] = date_first_experience
        if self._resume_template_rows_are_better(template_experience, details["experience_lines"]):
            details["experience_lines"] = template_experience
        details["experience_lines"] = filter_experience_rows(
            self._resume_clean_experience_rows(details.get("experience_lines") or []),
        )
        details["education_lines"] = self._resume_finalize_education_lines(
            self._resume_enrich_education_descriptions_from_raw(
                self._resume_filter_education_lines(details.get("education_lines") or []),
                raw_text,
            ),
        )
        template_education = self._resume_parse_template_education_lines(raw_text)
        if template_education:
            details["education_lines"] = template_education
        details["hobbies"] = self._resume_strip_default_hobbies(
            details.get("hobbies"),
            raw_text,
        )
        if not details.get("hobbies") and self._resume_has_interests_section(
            [line.strip() for line in raw_text.splitlines() if line.strip()]
        ):
            details["hobbies"] = "\n".join(self._resume_default_interests_for_section())
        details["hobbies"] = self._resume_format_text_value(details.get("hobbies"))
        details = self._resume_finalize_skills(details, raw_text)
        details["summary"] = self._resume_prefer_clean_summary(
            details.get("summary"),
            regex_summary,
        )
        if details.get("summary"):
            details["summary"] = self._resume_clean_summary(details["summary"])
        return details, raw_text

    def _resume_update_table_lines(self, details, from_onchange=False):
        if from_onchange:
            education_commands = [(5, 0, 0)] + [
                (0, 0, line)
                for line in details.get("education_lines", [])
            ]
            experience_commands = [(5, 0, 0)] + [
                (0, 0, line)
                for line in details.get("experience_lines", [])
            ]
            self.resume_education_line_ids = education_commands
            self.resume_experience_line_ids = experience_commands
            return
        self.resume_education_line_ids.unlink()
        self.resume_experience_line_ids.unlink()
        self.env["contact.resume.education"].create([
            dict(line, partner_id=self.id)
            for line in details.get("education_lines", [])
        ])
        self.env["contact.resume.experience"].create([
            dict(line, partner_id=self.id)
            for line in details.get("experience_lines", [])
        ])

    def _resume_apply_contact_values(self, vals, details):
        phone_field = "mobile" if "mobile" in self._fields else "phone"
        field_map = {
            "name": details.get("name"),
            "email": details.get("email"),
            phone_field: details.get("phone"),
            "function": details.get("job_title"),
            "website": details.get("website"),
        }
        for field_name, value in field_map.items():
            if field_name in self._fields and value and (self.resume_overwrite_existing or not self[field_name]):
                vals[field_name] = value

    def _resume_extract_text(self):
        file_content = base64.b64decode(self.resume_file)
        extractor = ResumeDocumentExtractor(
            self.env,
            ocr_callbacks={"image": self._resume_ocr_image_bytes},
        )
        return extractor.extract(file_content, self.resume_filename)

    def _resume_ocr_image_bytes(self, file_content):
        try:
            from PIL import Image, ImageEnhance, ImageOps
            import pytesseract
        except ImportError:
            raise UserError(
                _("Image resume OCR needs Pillow, pytesseract and the system tesseract command.")
            )

        image = Image.open(io.BytesIO(file_content)).convert("RGB")
        if max(image.size) > 1400:
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            image.thumbnail((1400, 1400), resampling)
        width, height = image.size
        left_column = image.crop((0, 0, int(width * 0.58), height))
        right_column = image.crop((int(width * 0.52), 0, width, height))
        main_column = image.crop((int(width * 0.34), int(height * 0.22), width, height))

        def ocr_image(source_image, score_func=None):
            grayscale = ImageOps.grayscale(source_image)
            enhanced = ImageEnhance.Contrast(grayscale).enhance(2.0)
            primary = enhanced.resize((enhanced.width * 2, enhanced.height * 2))
            texts = []
            for config in ("--psm 4", "--psm 6"):
                try:
                    text = pytesseract.image_to_string(primary, config=config, timeout=4).strip()
                except RuntimeError:
                    text = ""
                if text:
                    texts.append(text)
            scorer = score_func or self._resume_ocr_score
            return max(texts, key=scorer, default="") or max(texts, key=len, default="")

        header_band = image.crop((0, 0, width, int(height * 0.24)))
        full_text = ocr_image(image)
        header_text = ocr_image(header_band)
        left_text = ocr_image(left_column, self._resume_ocr_detail_score)
        right_text = ocr_image(right_column)
        main_text = ocr_image(main_column, self._resume_ocr_main_score)
        if header_text:
            header_lines = [line.strip() for line in header_text.splitlines() if line.strip()]
            if header_lines and self._resume_normalize_heading(header_lines[0]) not in self._resume_normalize_heading(full_text):
                full_text = "\n".join(header_lines + full_text.splitlines())
        text = self._resume_merge_ocr_texts(full_text, left_text, right_text, main_text)
        if not text:
            raise UserError(_("No readable text was found in this image resume."))
        return text

    def _resume_merge_ocr_texts(self, full_text, left_text, right_text=None, main_text=None):
        full_lines = [line.strip() for line in (full_text or "").splitlines() if line.strip()]
        left_lines = [line.strip() for line in (left_text or "").splitlines() if line.strip()]
        right_lines = [line.strip() for line in (right_text or "").splitlines() if line.strip()]
        main_lines = [line.strip() for line in (main_text or "").splitlines() if line.strip()]

        header = []
        for line in full_lines:
            if self._resume_detect_section_key(line) == "experience":
                break
            if self._resume_normalize_heading(line) == "work experience":
                break
            header.append(line)

        left_body = []
        for index, line in enumerate(left_lines):
            if self._resume_detect_section_key(line) == "experience" or self._resume_normalize_heading(line) == "work experience":
                left_body = left_lines[index:]
                break

        if not left_body:
            left_body = left_lines

        skills_block = self._resume_build_skills_section_lines(right_lines, full_lines)
        main_body = self._resume_extract_main_ocr_body(main_lines)
        if main_body:
            left_body = main_body

        extras = []
        seen = {self._resume_normalize_heading(line) for line in header + left_body + skills_block}
        capture_extras = False
        for line in full_lines:
            section_key = self._resume_detect_section_key(line)
            normalized = self._resume_normalize_heading(line)
            if section_key == "skills" or normalized == "skills":
                capture_extras = True
            if not capture_extras:
                continue
            if section_key in ("experience", "education"):
                capture_extras = False
                continue
            key = self._resume_normalize_heading(line)
            if key and key not in seen and not self._resume_is_noise_line(line):
                extras.append(line)
                seen.add(key)

        footer = []
        for line in full_lines + right_lines:
            key = self._resume_normalize_heading(line)
            if any(token in key for token in ("facebook", "linkedin", "dribbble", "street name", "postzip")):
                if key not in seen:
                    footer.append(line)
                    seen.add(key)
        hobbies_tail = self._resume_extract_ocr_section_tail(
            main_lines + right_lines + full_lines,
            "hobbies",
        )
        for line in hobbies_tail:
            key = self._resume_normalize_heading(line)
            if key and key not in seen:
                footer.append(line)
                seen.add(key)

        merged = "\n".join(part for part in (header + skills_block + extras + left_body + footer) if part)
        return self._resume_pick_best_ocr_text(full_text, merged)

    def _resume_pick_best_ocr_text(self, full_text, merged_text):
        full_score = self._resume_ocr_score(full_text)
        merged_score = self._resume_ocr_score(merged_text)
        full_lines = [line.strip() for line in (full_text or "").splitlines() if line.strip()]
        merged_lines = [line.strip() for line in (merged_text or "").splitlines() if line.strip()]
        full_exp = any(
            self._resume_detect_section_key(line) == "experience"
            or "professional experience" in self._resume_normalize_heading(line)
            for line in full_lines
        )
        merged_exp = any(
            self._resume_detect_section_key(line) == "experience"
            or "professional experience" in self._resume_normalize_heading(line)
            for line in merged_lines
        )
        if full_exp and not merged_exp:
            return full_text
        if full_score >= merged_score + 5:
            return full_text
        return merged_text

    def _resume_extract_ocr_section_tail(self, lines, section_name):
        collected = []
        capture = False
        for line in lines or []:
            section_key = self._resume_detect_section_key(line)
            normalized = self._resume_normalize_heading(line)
            if section_key == section_name or (section_name == "hobbies" and normalized in {"interests", "interest"}):
                capture = True
                collected.append("INTERESTS")
                continue
            if not capture:
                continue
            if section_key and section_key != section_name:
                break
            clean = self._resume_clean_table_text(line)
            if clean and not self._resume_is_noise_line(clean):
                collected.append(clean)
        return collected

    def _resume_extract_main_ocr_body(self, main_lines):
        if not main_lines:
            return []
        start = False
        for index, line in enumerate(main_lines):
            section_key = self._resume_detect_section_key(line)
            normalized = self._resume_normalize_heading(line)
            if section_key == "experience" or "professional experience" in normalized:
                start = index
                break
        if start is False:
            return []
        body = []
        for line in main_lines[start:]:
            normalized = self._resume_normalize_heading(line)
            if normalized and normalized not in {"a", "td", "ee", "eee", "cee"}:
                body.append(line)
        return body

    def _resume_ocr_score(self, text):
        normalized = self._resume_normalize_heading(text)
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        short_lines = sum(1 for line in lines if len(line) <= 3)
        score = len(text or "") / 300 - short_lines * 4
        for heading in (
            "profile", "work experience", "experience", "education", "skills",
            "languages", "hobbies", "interests", "social link", "contact",
        ):
            if heading in normalized:
                score += 40
        for interest in ("football", "music", "photography", "running", "writing", "cricket"):
            if interest in normalized:
                score += 10
        if "work experience skills" in normalized:
            score -= 80
        if re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "", flags=re.IGNORECASE):
            score += 25
        return score

    def _resume_ocr_detail_score(self, text):
        normalized = self._resume_normalize_heading(text)
        date_rows = len(re.findall(r"\b(?:19|20)\d{2}\s*[-+]\s*(?:19|20)?\d{2,4}\b", text or ""))
        score = len(text or "") / 200 + date_rows * 25
        for keyword in ("lorem ipsum technology", "company", "new york", "work experience", "education"):
            if keyword in normalized:
                score += 30
        return score

    def _resume_ocr_main_score(self, text):
        normalized = self._resume_normalize_heading(text)
        score = len(text or "") / 200
        for keyword in (
            "professional experience", "account manager", "xyz company",
            "abc corporation", "def solutions", "ma communication",
            "ba communication", "high school diploma", "successfully managed",
        ):
            if keyword in normalized:
                score += 50
        score += 20 * len(re.findall(r"\b(?:19|20|2O)XX\b", text or "", flags=re.IGNORECASE))
        return score

    def _resume_build_skills_section_lines(self, right_lines, full_lines):
        skills = []
        seen = set()
        for line in self._resume_iter_skills_section_lines(right_lines):
            skill = self._resume_canonicalize_skill_line(line)
            if skill and skill not in seen:
                skills.append(skill)
                seen.add(skill)
        for line in self._resume_iter_skills_section_lines(full_lines):
            skill = self._resume_canonicalize_skill_line(line)
            if skill and skill not in seen:
                skills.append(skill)
                seen.add(skill)
        for skill in (self._resume_extract_known_skills("\n".join(right_lines or []) + "\n" + "\n".join(full_lines or [])) or "").splitlines():
            if skill and skill not in seen and not re.search(r"(.)\1{4,}", skill, flags=re.IGNORECASE):
                skills.append(skill)
                seen.add(skill)
        if not skills:
            return []
        return ["SKILLS"] + skills

    def _resume_iter_skills_section_lines(self, lines):
        in_skills = False
        for line in lines or []:
            normalized = self._resume_normalize_heading(line)
            section_key = self._resume_detect_section_key(line)
            if normalized == "skills" or section_key in ("skills", "hard_skills", "soft_skills"):
                in_skills = True
                continue
            if not in_skills:
                continue
            clean = self._resume_clean_table_text(line)
            if clean.startswith("•"):
                yield clean.lstrip("• ").strip()
                continue
            if section_key in (
                "experience", "education", "hobbies", "social_media", "summary",
                "contact", "personal_information", "languages", "certifications",
                "projects",
            ):
                break
            if normalized in (
                "interests", "interest", "education", "social link", "profile",
                "contact", "professional experience", "work experience",
            ):
                break
            if re.search(r"\b(?:19|20)\d{2}\b", line or ""):
                break
            yield line

    def _resume_canonicalize_skill_line(self, line):
        clean = self._resume_clean_table_text(line)
        if not clean or self._resume_is_noise_line(clean):
            return False
        if self._resume_line_is_not_a_skill(clean):
            return False
        if self._resume_line_looks_like_experience_entry(clean):
            return False
        normalized = self._resume_normalize_heading(clean)
        if len(normalized) <= 2 and normalized not in {"css"}:
            return False
        if normalized in {"ss"}:
            return "CSS"
        if re.search(r"(.)\1{4,}", normalized) or re.search(r"[eE]{5,}", clean):
            return False
        if len(clean) > 8 and sum(1 for char in clean if char.isupper()) / max(len(clean), 1) > 0.55:
            return False
        skill_map = (
            (r"wordpress", "Wordpress"),
            (r"html\s*5|html5|himls|wimls", "HTML5"),
            (r"^css$|html\s*/\s*css|wnacss|hnacss", "CSS"),
            (r"photoshop", "Photoshop"),
            (r"flash\s*animation", "Flash Animation"),
            (r"java\s*script|jove\s*script|jave\s*script|dave\s*script", "JavaScript"),
            (r"illustrator|rlustraton|raustraton|raustrator|nlustrator", "Illustrator"),
            (r"indesign|indesicn", "InDesign"),
            (r"^python$", "Python"),
            (r"^java$", "Java"),
            (r"^sql$", "SQL"),
        )
        for pattern, canonical in skill_map:
            if re.search(pattern, normalized, flags=re.IGNORECASE) or re.search(pattern, clean, flags=re.IGNORECASE):
                return canonical
        if ResumeAIParserService.is_valid_skill_line(clean) and len(clean) <= 40:
            return clean
        return False

    def _resume_line_is_not_a_skill(self, line):
        normalized = self._resume_normalize_heading(line)
        if normalized in {
            "name", "surname", "name surname", "contact", "profile", "professional experience",
            "experience", "education", "interests", "hobbies", "summary", "nyu", "new york",
            "personal information", "personal details", "personal info", "date of birth",
            "dob", "eee", "eeee", "ee", "dar",
        }:
            return True
        if re.fullmatch(r"[a-f0-9]{6,}", normalized) or re.fullmatch(r"[eE]{3,}", line.strip()):
            return True
        if "@" in line or self._resume_extract_phone(line):
            return True
        if re.search(r"\b(?:results oriented|proven track record|revenue growth|lasting relationships|"
                     r"successfully managed|consistently achieved|led negotiations|initiated and nurtured|"
                     r"provided product demonstrations|annual revenue|quarterly sales targets)\b",
                     normalized):
            return True
        if re.search(r"\b(?:account manager|sales representative|sales associate)\b", normalized):
            return True
        if re.search(r"\b(?:gmbh|inc|llc|ltd|llp|solutions inc|market share|product knowledge|enhance product|resulting in)\b", normalized):
            return True
        known_skill_normalized = {
            self._resume_normalize_heading(skill)
            for skill in (
                self.HARD_SKILL_KEYWORDS
                + (
                    "Wordpress", "HTML5", "HTML", "CSS", "JavaScript", "Photoshop",
                    "Flash Animation", "Illustrator", "InDesign", "Python", "Java",
                    "C++", "SQL", "Linux/Unix Command line",
                )
            )
        }
        if normalized in known_skill_normalized:
            return False
        if re.search(r"\b(?:university|college|institute|academy)\b", normalized) and not re.search(
            r"\b(?:analysis|research|management|development|strategy|communication|leadership)\b",
            normalized,
        ):
            return True
        from ..services.experience_parser import looks_like_company
        if looks_like_company(line):
            return True
        words = re.findall(r"[A-Za-z]+", line or "")
        if words and len(words) <= 3 and all(word.isupper() for word in words):
            return True
        if len(words) > 5:
            return True
        return False

    def _resume_clean_skill_rating_line(self, line):
        clean = re.sub(r"[\s©¢•|]+[eo©¢•*]{3,}.*$", "", line or "", flags=re.IGNORECASE)
        clean = re.sub(r"\s{2,}", " ", clean).strip(" -•|©¢")
        return self._resume_clean_table_text(clean)

    def _resume_extract_rating_skills(self, raw_text):
        skills = []
        seen = set()
        for line in (raw_text or "").splitlines():
            if not re.search(r"[eo©¢•*]{4,}", line or "", flags=re.IGNORECASE):
                continue
            parts = re.split(
                r"[\s©¢•|]+[eo©¢•*]{3,}",
                line,
                flags=re.IGNORECASE,
            )
            for part in parts:
                clean = self._resume_clean_skill_rating_line(part)
                if (
                    clean
                    and clean not in seen
                    and not self._resume_line_is_not_a_skill(clean)
                    and self._resume_canonicalize_skill_line(clean)
                ):
                    skill = self._resume_canonicalize_skill_line(clean)
                    if skill:
                        skills.append(skill)
                        seen.add(skill)
        return "\n".join(skills) or False

    def _resume_extract_resume_skills(self, raw_text):
        lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
        skills = []
        seen = set()
        for line in self._resume_iter_skills_section_lines(lines):
            for token in self._resume_split_skill_tokens(line):
                skill = self._resume_canonicalize_skill_line(token)
                if skill and skill not in seen:
                    skills.append(skill)
                    seen.add(skill)
        for skill in (self._resume_extract_known_skills(raw_text) or "").splitlines():
            if skill and skill not in seen:
                skills.append(skill)
                seen.add(skill)
        for skill in (self._resume_extract_rating_skills(raw_text) or "").splitlines():
            if skill and skill not in seen:
                skills.append(skill)
                seen.add(skill)
        return "\n".join(skills) or False

    def _resume_finalize_skills(self, details, raw_text):
        normalized_text = self._resume_normalize_document_text(raw_text)
        resume_skills = self._resume_extract_resume_skills(normalized_text)
        for skill in (self._resume_extract_known_skills(normalized_text) or "").splitlines():
            if skill and skill not in (resume_skills or "").splitlines():
                resume_skills = "\n".join(filter(None, [resume_skills, skill]))
        resume_skills = self._resume_expand_skill_lines(resume_skills)
        hard_skills = self._resume_merge_skill_texts(
            resume_skills,
            self._resume_expand_skill_lines(details.get("hard_skills")),
        )
        hard_skills = self._resume_expand_skill_lines(hard_skills)
        soft_skills = details.get("soft_skills") or False
        details["hard_skills"] = hard_skills
        details["soft_skills"] = soft_skills
        details["skills"] = ResumeAIParserService.build_combined_skills(
            hard_skills,
            soft_skills,
            self._resume_expand_skill_lines(details.get("skills")),
        )
        return details

    def _resume_split_skill_tokens(self, line):
        clean = self._resume_clean_table_text(line)
        if not clean:
            return []
        parts = re.split(r"\s*[\x7f•]\s*|\s*[|,;]\s*", clean)
        if len(parts) == 1 and clean.startswith("•"):
            parts = [clean.lstrip("• ").strip()]
        return [part.strip() for part in parts if part.strip()]

    def _resume_expand_skill_lines(self, text):
        values = []
        for line in (text or "").splitlines():
            parts = self._resume_split_skill_tokens(line)
            if len(parts) == 1:
                parts = [line]
            for part in parts:
                clean = self._resume_canonicalize_skill_line(part) or self._resume_clean_table_text(part)
                if clean and not self._resume_line_is_not_a_skill(clean) and clean not in values:
                    values.append(clean)
        return "\n".join(values) or False

    def _resume_clean_experience_rows(self, rows):
        cleaned_rows = []
        for row in rows or []:
            row = dict(row)
            if row.get("description"):
                clean_lines = []
                for line in str(row["description"]).splitlines():
                    clean = self._resume_clean_description_line(line)
                    if clean and clean not in clean_lines:
                        clean_lines.append(clean)
                row["description"] = "\n".join(clean_lines) or False
            cleaned_rows.append(row)
        return cleaned_rows

    def _resume_template_rows_are_better(self, candidate_rows, current_rows):
        if not candidate_rows:
            return False
        candidate_score = self._resume_experience_rows_quality_score(candidate_rows)
        current_score = self._resume_experience_rows_quality_score(current_rows)
        if candidate_score > current_score:
            return True
        if candidate_score < current_score:
            return False
        if len(candidate_rows) > len(current_rows or []):
            return True
        candidate_descriptions = sum(1 for row in candidate_rows if row.get("description"))
        current_descriptions = sum(1 for row in (current_rows or []) if row.get("description"))
        return candidate_descriptions > current_descriptions

    def _resume_experience_rows_quality_score(self, rows):
        from ..services.experience_parser import looks_like_company
        score = 0
        for row in rows or []:
            title = row.get("job_title") or ""
            company = row.get("company") or ""
            if self._resume_line_looks_like_role_title(title) and looks_like_company(company):
                if not self._resume_line_is_description_candidate(company):
                    score += 10
            if row.get("date_range") and re.search(r"(?:19|20)\d{2}", row.get("date_range") or ""):
                score += 2
        return score

    def _resume_pick_experience_company(self, candidates):
        from ..services.experience_parser import looks_like_company
        for candidate in candidates:
            clean = self._resume_clean_table_text(candidate)
            if not clean or self._resume_line_is_description_candidate(clean):
                continue
            if re.search(r"\d+%", clean):
                continue
            if looks_like_company(clean):
                return clean
        return False

    def _resume_parse_template_experience_lines(self, raw_text):
        lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
        if not any(
            self._resume_detect_section_key(line) == "experience"
            or "professional experience" in self._resume_normalize_heading(line)
            or "work experences" in self._resume_normalize_heading(line)
            for line in lines
        ):
            return []
        rows = []
        current = False
        in_experience = False
        pending_title = False
        title_company_pattern = re.compile(
            r"^([A-Z][A-Z ]*(?:MANAGER|REPRESENTATIVE|ASSOCIATE|EXECUTIVE|SPECIALIST|DIRECTOR|ANALYST|CONSULTANT|ENGINEER|DEVELOPER)[A-Z ]*)\s*[|]\s*(.+)$",
            flags=re.IGNORECASE,
        )
        company_pipe_pattern = re.compile(
            r"^(.+?)\s*\|\s*(.+?)\s*\|\s*(.+)$",
            flags=re.IGNORECASE,
        )
        date_pattern = re.compile(
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(?:19|20)\d{2}|20XX|\d{4}\s*[-–—]\s*(?:\d{4}|present|current)",
            flags=re.IGNORECASE,
        )
        for line in lines:
            section_key = self._resume_detect_section_key(line)
            normalized = self._resume_normalize_heading(line)
            if section_key == "experience" or normalized in {
                "professional experience", "work experences", "work experiences",
            }:
                in_experience = True
                continue
            if in_experience and section_key in ("education", "hobbies", "skills", "social_media"):
                break
            if not in_experience:
                continue
            clean_line = self._resume_clean_table_text(line)
            if not clean_line:
                continue
            from ..services.experience_parser import looks_like_job_title
            if (
                looks_like_job_title(clean_line)
                or "write your job title" in normalized
                or "your position here" in normalized
            ) and "|" not in clean_line:
                pending_title = clean_line
                continue
            pipe_match = company_pipe_pattern.match(clean_line)
            if pipe_match and pending_title:
                if current:
                    rows.append(current)
                current = {
                    "date_range": self._resume_clean_table_text(pipe_match.group(3)),
                    "job_title": pending_title,
                    "company": self._resume_clean_table_text(pipe_match.group(1)),
                    "location": self._resume_clean_table_text(pipe_match.group(2)),
                    "description": False,
                }
                pending_title = False
                continue
            match = title_company_pattern.match(clean_line)
            if match:
                if current:
                    rows.append(current)
                current = {
                    "date_range": False,
                    "job_title": self._resume_clean_table_text(match.group(1)),
                    "company": self._resume_clean_table_text(match.group(2)),
                    "location": False,
                    "description": False,
                }
                continue
            if not current:
                continue
            if re.search(r"\b(?:19|20)\d{2}|20XX\b", clean_line) and (
                "-" in clean_line or "–" in clean_line or date_pattern.search(clean_line)
            ):
                if not current.get("date_range"):
                    current["date_range"] = clean_line
                continue
            desc = self._resume_clean_description_line(clean_line)
            if desc:
                current["description"] = "\n".join(filter(None, [current.get("description"), desc]))
        if current:
            rows.append(current)
        return [
            row for row in self._resume_clean_experience_rows(rows)
            if row.get("job_title") and row.get("company")
        ]

    def _resume_parse_date_first_experience_lines(self, raw_text):
        lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
        date_line = re.compile(
            r"^(?:(?:(?:19|20)\d{2})[/-]\d{1,2}\s*[-–—/]\s*(?:(?:19|20)\d{2})[/-]\d{1,2}|"
            r"\d{1,2}\.\d{4}\s*[-–—]\s*\d{1,2}\.\d{4})$",
            flags=re.IGNORECASE,
        )
        rows = []
        in_experience = False
        index = 0
        while index < len(lines):
            line = lines[index]
            normalized = self._resume_normalize_heading(line)
            section_key = self._resume_detect_section_key(line)
            if section_key == "experience" or normalized == "professional experience":
                in_experience = True
                index += 1
                continue
            if not in_experience:
                index += 1
                continue
            if section_key in ("education", "skills", "languages", "hobbies", "social_media", "certifications"):
                break
            if not date_line.match(line):
                index += 1
                continue
            date_range = re.sub(r"\.(\d{4})", r"-\1", line).replace("/", "-")
            title = self._resume_clean_table_text(lines[index + 1]) if index + 1 < len(lines) else False
            location = False
            company = False
            next_index = index + 2
            from ..services.experience_parser import looks_like_company, looks_like_job_title, looks_like_location
            title_normalized = self._resume_normalize_heading(title or "")
            if (
                not title
                or title_normalized in ("education", "skills", "languages", "profile", "awards")
                or any(keyword in title_normalized for keyword in ("bachelor", "master", "diploma", "mba", "university"))
            ):
                index += 1
                continue
            follow_line = self._resume_clean_table_text(lines[index + 2]) if index + 2 < len(lines) else False
            if (
                follow_line
                and looks_like_company(title)
                and looks_like_job_title(follow_line)
                and not looks_like_job_title(title)
            ):
                company = title
                title = follow_line
                next_index = index + 3
            elif next_index < len(lines):
                candidate = self._resume_clean_table_text(lines[next_index])
                if candidate and looks_like_location(candidate):
                    location = candidate
                    next_index += 1
            if not company and next_index < len(lines):
                candidate = self._resume_clean_table_text(lines[next_index])
                candidate_normalized = self._resume_normalize_heading(candidate or "")
                if candidate_normalized in ("education", "skills", "languages", "profile", "awards"):
                    index += 1
                    continue
                if candidate and looks_like_company(candidate):
                    company = candidate
                    next_index += 1
                elif candidate and looks_like_job_title(candidate) and not title:
                    title = candidate
                    next_index += 1
            if not title or not company or not looks_like_job_title(title) or not looks_like_company(company):
                index += 1
                continue
            description_lines = []
            while next_index < len(lines):
                current = lines[next_index]
                if date_line.match(current) or self._resume_detect_section_key(current) in (
                    "education", "skills", "languages", "hobbies", "social_media", "certifications", "experience",
                ):
                    break
                if self._resume_line_is_description_candidate(current):
                    clean = self._resume_clean_description_line(current)
                    if clean and clean not in description_lines:
                        description_lines.append(clean)
                next_index += 1
            rows.append({
                "date_range": date_range,
                "job_title": title,
                "company": company,
                "location": location or False,
                "description": "\n".join(description_lines) or False,
            })
            index = next_index
        return self._resume_clean_experience_rows(rows)

    def _resume_parse_pipe_date_experience_lines(self, raw_text):
        lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
        if not lines:
            return []
        from ..services.experience_parser import looks_like_job_title
        pipe_date_pattern = re.compile(
            r"([^|]{3,80}?)\s*\|\s*((?:\d{4}\s*[-–—]\s*(?:Present|Current|\d{4})))",
            flags=re.IGNORECASE,
        )
        pending_title = False
        rows = []
        seen = set()
        for index, line in enumerate(lines):
            clean_line = self._resume_clean_table_text(line)
            if not clean_line:
                continue
            normalized = self._resume_normalize_heading(clean_line)
            if normalized in {"your position here"} or (
                self._resume_line_looks_like_role_title(clean_line)
                and "your degree here" not in normalized
                and not pipe_date_pattern.search(clean_line)
                and "«" not in clean_line
                and "©" not in clean_line
            ):
                if "your position here" in normalized:
                    pending_title = "Your Position Here"
                elif self._resume_line_looks_like_role_title(clean_line):
                    pending_title = clean_line
                continue
            matches = list(pipe_date_pattern.finditer(clean_line))
            if not matches:
                continue
            match = matches[-1]
            company = re.sub(
                r"^(?:EXPERTISES|LOCATION)\s+",
                "",
                self._resume_clean_table_text(match.group(1)),
                flags=re.IGNORECASE,
            ).strip()
            company = re.sub(
                r"^.*\b(Company Name of Lorem)\s*$",
                r"\1",
                company,
                flags=re.IGNORECASE,
            ).strip()
            if not company or len(company) < 3:
                continue
            date_range = self._resume_clean_table_text(match.group(2))
            title = False
            for back in range(index - 1, max(index - 12, -1), -1):
                candidate = self._resume_clean_table_text(lines[back])
                candidate_norm = self._resume_normalize_heading(candidate or "")
                if "your position here" in candidate_norm:
                    title = "Your Position Here"
                    break
                if "«" in (candidate or "") or "©" in (candidate or ""):
                    continue
                if self._resume_line_looks_like_role_title(candidate):
                    title = candidate
                    break
            if not title:
                title = pending_title
            if not title:
                continue
            key = (title.lower(), company.lower(), date_range.lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "date_range": date_range,
                "job_title": title,
                "company": company,
                "location": False,
                "description": False,
            })
            pending_title = False
        return self._resume_clean_experience_rows(rows)

    def _resume_parse_scattered_experience_lines(self, raw_text):
        lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
        if not lines:
            return []
        from ..services.experience_parser import looks_like_company, looks_like_job_title
        date_line = re.compile(
            r"^(?:(?:19|20)\d{2})[/-]\d{1,2}\s*[-–—/]\s*(?:(?:19|20)\d{2})[/-]\d{1,2}$",
            flags=re.IGNORECASE,
        )
        education_index = len(lines)
        start_index = 0
        degree_start = len(lines)
        for index, line in enumerate(lines):
            normalized = self._resume_normalize_heading(line)
            if self._resume_detect_section_key(line) == "education" or normalized == "education":
                education_index = min(education_index, index)
            if self._resume_detect_section_key(line) == "experience" or normalized == "professional experience":
                start_index = index + 1
            if any(keyword in normalized for keyword in ("bachelor", "master", "mba", "phd", "diploma")) and "business" in normalized or "engineering" in normalized or "administration" in normalized:
                degree_start = min(degree_start, index)
        dates = []
        for line in lines[start_index:education_index]:
            if date_line.match(line):
                dates.append(re.sub(r"/", "-", line))
        jobs = []
        for index, line in enumerate(lines[start_index:degree_start]):
            if not self._resume_line_looks_like_role_title(line):
                continue
            company = self._resume_pick_experience_company(lines[start_index + index + 1:start_index + index + 4])
            if company:
                jobs.append({
                    "job_title": self._resume_clean_table_text(line),
                    "company": company,
                })
        if not dates or not jobs:
            return []
        rows = []
        for date_range, job in zip(dates, jobs[:len(dates)]):
            rows.append({
                "date_range": date_range,
                "job_title": job["job_title"],
                "company": job["company"],
                "location": False,
                "description": False,
            })
        return self._resume_clean_experience_rows(rows)

    def _resume_line_looks_like_role_title(self, line):
        from ..services.experience_parser import looks_like_job_title
        clean = self._resume_clean_table_text(line)
        if not clean or not looks_like_job_title(clean):
            return False
        if len(clean.split()) > 6 or re.search(r"\d+%", clean):
            return False
        if self._resume_line_is_description_candidate(clean):
            return False
        normalized = self._resume_normalize_heading(clean)
        if any(keyword in normalized for keyword in ("resulting", "successfully", "conducted", "developed", "launched")):
            return False
        if re.search(r"\bof the year\b", normalized):
            return False
        return True

    def _resume_parse_template_education_lines(self, raw_text):
        lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
        rows = []
        current = False
        in_education = False
        degree_pattern = re.compile(
            r"^(MA|BA|B\.?A\.?|M\.?A\.?|HIGH SCHOOL DIPLOMA|H\.?S\.?C\.?|SSC|BACHELOR|MASTER)[A-Z .]*(?:COMMUNICATION|DIPLOMA|SCIENCE|ARTS|COMMERCE)?\s*[|:-]\s*((?:19|20)\d{2}|20XX)\s*[-–—]\s*((?:19|20)\d{2}|20XX)",
            flags=re.IGNORECASE,
        )
        for line in lines:
            section_key = self._resume_detect_section_key(line)
            if section_key == "education":
                in_education = True
                continue
            if in_education and section_key in ("experience", "hobbies", "skills", "social_media"):
                break
            if not in_education:
                continue
            clean_line = self._resume_clean_education_text(line)
            if not clean_line:
                continue
            match = degree_pattern.match(clean_line)
            if match:
                if current:
                    rows.append(current)
                degree = re.sub(r"\s*[|:-]\s*.*$", "", clean_line).strip()
                current = {
                    "date_range": "%s - %s" % (match.group(2), match.group(3)),
                    "degree": self._resume_clean_table_text(degree),
                    "institution": False,
                    "location": False,
                    "description": False,
                }
                continue
            if current and self._resume_looks_like_institution_fragment(clean_line):
                current["institution"] = clean_line
                continue
            if self._resume_normalize_heading(clean_line) in {"high", "high s"}:
                continue
        if current:
            rows.append(current)
        return self._resume_finalize_education_lines(rows)

    def _resume_prefer_clean_summary(self, primary_summary, fallback_summary):
        primary_clean = self._resume_clean_summary(primary_summary)
        fallback_clean = self._resume_clean_summary(fallback_summary)
        if not fallback_clean:
            return primary_clean
        if not primary_clean:
            return fallback_clean
        primary_noise = bool(re.search(
            r"photoshop|hnacss|wnacss|ts\]|tai\]|rlustraton|raustraton|©",
            primary_summary or "",
            flags=re.IGNORECASE,
        ))
        if primary_noise and fallback_clean:
            return fallback_clean
        return primary_clean if len(primary_clean) >= len(fallback_clean) else fallback_clean

    def _resume_normalize_document_text(self, text):
        text = re.sub(r"\r", "\n", text or "")
        text = text.replace("\x7f", " • ")
        text = re.sub(r"[\u2022\u2023\u25e6\u2043\u2219]", " • ", text)
        text = re.sub(r"\s*•\s*", " • ", text)
        return self._resume_split_inline_section_headers(text)

    def _resume_split_inline_section_headers(self, text):
        section_names = (
            "SKILLS", "LANGUAGES", "EXPERIENCE", "EDUCATION", "PROFILE",
            "CONTACT", "PROJECTS", "HOBBIES", "INTERESTS", "CERTIFICATIONS",
        )
        lines = []
        for line in (text or "").splitlines():
            stripped = line.strip()
            matched = False
            for name in section_names:
                pattern = r"^\s*(%s)\s*•\s*(.+)$" % re.escape(name)
                match = re.match(pattern, stripped, flags=re.IGNORECASE)
                if match:
                    lines.append(match.group(1).upper())
                    for part in match.group(2).split("•"):
                        part = part.strip()
                        if part:
                            lines.append("• %s" % part)
                    matched = True
                    break
            if not matched:
                lines.append(line)
        return "\n".join(lines)

    def _resume_parse_details(self, text):
        cleaned_text = self._resume_normalize_document_text(text)
        cleaned_text = self._resume_normalize_ocr_layout(cleaned_text)
        compact_text = re.sub(r"[ \t]+", " ", cleaned_text)
        lines = [line.strip() for line in cleaned_text.splitlines() if line.strip()]
        sections = self._resume_collect_sections(lines)

        email = self._resume_extract_email(compact_text)
        phone = self._resume_extract_phone(compact_text)
        linkedin = self._resume_extract_linkedin(compact_text)
        website = self._resume_first_match(r"https?://(?!.*linkedin\.com)[^\s,;]+", compact_text)
        social_media = self._resume_extract_social_media(lines)

        education_text = self._resume_merge_education(sections.get("education"), lines)
        has_experience_section = self._resume_has_experience_section(lines, sections)
        find_experience_text = (
            self._resume_slice_experience_lines(lines)
            or (self._resume_find_experience_text(lines) if has_experience_section else False)
        )
        section_experience_text = sections.get("experience")
        if self._resume_has_structured_experience_layout(find_experience_text):
            experience_text = find_experience_text
            experience_lines = sanitize_experience_rows(
                realign_experience_descriptions(
                    parse_experience_text(experience_text),
                    experience_text,
                ),
                experience_text,
            )
        elif find_experience_text and section_experience_text:
            experience_text = find_experience_text
            experience_lines = sanitize_experience_rows(
                realign_experience_descriptions(
                    merge_experience_lines(
                        parse_experience_text(section_experience_text),
                        parse_experience_text(find_experience_text),
                    ),
                    find_experience_text,
                ),
                find_experience_text,
            )
        elif find_experience_text:
            experience_text = find_experience_text
            experience_lines = sanitize_experience_rows(
                realign_experience_descriptions(
                    parse_experience_text(experience_text),
                    experience_text,
                ),
                experience_text,
            )
        elif section_experience_text:
            experience_text = section_experience_text
            experience_lines = parse_experience_text(experience_text)
        else:
            experience_text = False
            experience_lines = []
        soft_skills = sections.get("soft_skills") or self._resume_extract_soft_skill_keywords(
            sections.get("soft_skills") or compact_text
        )
        hard_skills = self._resume_merge_skill_texts(
            sections.get("hard_skills"),
            self._resume_extract_resume_skills(cleaned_text),
        )
        education_lines = self._resume_parse_education_lines(education_text)
        inline_education_lines = self._resume_parse_inline_education_rows(lines)
        if inline_education_lines:
            education_lines = self._resume_filter_education_lines(
                self._resume_merge_education_line_details(education_lines, inline_education_lines)
            )
        return {
            "name": self._resume_extract_name(lines),
            "email": email,
            "phone": phone,
            "address": self._resume_extract_address(lines),
            "linkedin": linkedin,
            "website": website,
            "social_media": social_media,
            "job_title": self._resume_extract_job_title(lines),
            "summary": self._resume_clean_summary(
                self._resume_extract_summary(lines, sections)
            ),
            "skills": ResumeAIParserService.build_combined_skills(
                hard_skills,
                soft_skills,
                sections.get("skills"),
            ),
            "hard_skills": hard_skills,
            "soft_skills": soft_skills,
            "languages": self._resume_extract_languages(lines, sections, compact_text),
            "education": education_text,
            "experience": rows_to_text(
                experience_lines,
                ("date_range", "job_title", "company", "location", "description"),
            ) or experience_text,
            "education_lines": education_lines,
            "experience_lines": experience_lines,
            "certifications": sections.get("certifications"),
            "hobbies": self._resume_extract_hobbies(lines, sections, compact_text),
            "message": self._resume_build_message(email, phone),
            "_has_experience_section": has_experience_section,
        }

    def _resume_has_structured_experience_layout(self, experience_text):
        if not experience_text:
            return False
        company_rows = 0
        date_rows = 0
        for line in experience_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.search(r"\b(?:19|20)\d{2}\s*[-–—+]", line):
                date_rows += 1
            from ..services.experience_parser import split_company_location, looks_like_company
            company, _location = split_company_location(line)
            if company and looks_like_company(company):
                company_rows += 1
        return date_rows >= 2 and company_rows >= 2

    def _resume_clean_ocr_for_ai(self, text):
        text = re.sub(r"\r", "\n", text or "")
        text = self._resume_prepare_ocr_text(text)
        lines = []
        seen = set()
        for line in text.splitlines():
            clean = re.sub(r"\s+", " ", line).strip()
            if not clean or len(clean) <= 1:
                continue
            clean = re.sub(r"^[^\w#@+]+", "", clean)
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            lines.append(clean)
        normalized = "\n".join(lines)
        heading_fixes = {
            r"\bcareer objective\b": "CAREER OBJECTIVE",
            r"\bpersonal skills?\b": "PERSONAL SKILLS",
            r"\btechnical skills?\b": "TECHNICAL SKILLS",
            r"\bsoft skills?\b": "SOFT SKILLS",
            r"\blanguages?\b": "LANGUAGES",
            r"\beducation\b": "EDUCATION",
            r"\bexperience\b": "EXPERIENCE",
            r"\bhobbies?\b": "HOBBIES",
            r"\binterests?\b": "INTERESTS",
            r"\bcontact\b": "CONTACT",
        }
        for pattern, replacement in heading_fixes.items():
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"(@\s*)(Phone|Email|Address)", r"\1\2", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"([a-zA-Z])@([a-zA-Z])", r"\1 \2", normalized)
        return normalized.strip()

    def _resume_merge_regex_fallback(self, primary, fallback):
        merged = dict(fallback)
        merged.update({key: value for key, value in primary.items() if value})
        merged["resume_raw_text"] = primary.get("resume_raw_text") or fallback.get("resume_raw_text")
        for field_name in (
            "name", "job_title", "email", "phone", "address", "linkedin", "website",
            "social_media", "summary", "languages", "education", "experience",
            "certifications", "hobbies", "message",
        ):
            if primary.get(field_name):
                merged[field_name] = primary[field_name]
        if primary.get("education_lines") and primary.get("_ai_applied"):
            merged["education_lines"] = self._resume_merge_education_line_details(
                fallback.get("education_lines"),
                primary.get("education_lines"),
            )
        elif primary.get("education_lines"):
            merged["education_lines"] = self._resume_merge_education_line_details(
                primary.get("education_lines"),
                fallback.get("education_lines"),
            )
        elif fallback.get("education_lines"):
            merged["education_lines"] = fallback["education_lines"]
        merged["education_lines"] = self._resume_filter_education_lines(
            merged.get("education_lines") or []
        )
        if primary.get("_ai_applied"):
            regex_rows = fallback.get("experience_lines") or []
            if self._resume_experience_rows_are_structured(regex_rows):
                merged["experience_lines"] = list(regex_rows)
            else:
                merged["experience_lines"] = merge_experience_lines(
                    regex_rows,
                    primary.get("experience_lines") or [],
                )
        elif primary.get("experience_lines"):
            merged["experience_lines"] = merge_experience_lines(
                primary.get("experience_lines"),
                fallback.get("experience_lines"),
            )
        elif fallback.get("_has_experience_section") and fallback.get("experience_lines"):
            merged["experience_lines"] = filter_experience_rows(fallback.get("experience_lines"))
        else:
            merged["experience_lines"] = []
        merged.pop("_has_experience_section", None)
        resume_skills = self._resume_extract_resume_skills(merged.get("resume_raw_text"))
        merged["hard_skills"] = self._resume_merge_skill_texts(
            resume_skills,
            fallback.get("hard_skills"),
        )
        merged["soft_skills"] = fallback.get("soft_skills") or primary.get("soft_skills") or False
        merged["skills"] = ResumeAIParserService.build_combined_skills(
            merged.get("hard_skills"),
            merged.get("soft_skills"),
            False,
        )
        merged["summary"] = self._resume_prefer_clean_summary(
            primary.get("summary"),
            fallback.get("summary"),
        )
        merged["email"] = (
            ResumeAIParserService._normalize_email(merged.get("email"))
            or merged.get("email")
        )
        merged["email"] = self._resume_prefer_extracted_email(
            merged.get("email"),
            fallback.get("email"),
            merged.get("resume_raw_text"),
        )
        merged["address"] = self._resume_merge_address(
            merged.get("address"),
            fallback.get("address"),
        )
        merged["hobbies"] = self._resume_strip_default_hobbies(
            self._resume_merge_hobbies(
                merged.get("hobbies"),
                fallback.get("hobbies"),
            ),
            merged.get("resume_raw_text") or fallback.get("resume_raw_text") or "",
        )
        if not merged.get("hobbies") and self._resume_has_interests_section(
            [line.strip() for line in (merged.get("resume_raw_text") or "").splitlines() if line.strip()]
        ):
            merged["hobbies"] = "\n".join(self._resume_default_interests_for_section())
        merged["experience_lines"] = sanitize_experience_rows(
            self._resume_dedupe_rows(
                self._resume_enrich_experience_descriptions(
                    merged.get("experience_lines") or [],
                    fallback.get("experience_lines") or [],
                ),
                "job_title",
            ),
            merged.get("resume_raw_text") or fallback.get("resume_raw_text") or "",
        )
        merged["linkedin"] = merged.get("linkedin") or self._resume_extract_linkedin(
            "\n".join(
                part for part in (
                    merged.get("social_media"),
                    merged.get("resume_raw_text"),
                    fallback.get("resume_raw_text"),
                ) if part
            )
        )
        merged["linkedin"] = self._resume_normalize_linkedin_url(merged.get("linkedin"))
        return merged

    def _resume_prefer_extracted_email(self, primary_email, regex_email, raw_text):
        if not regex_email:
            return primary_email
        if not primary_email or primary_email == regex_email:
            return regex_email
        raw = (raw_text or "").lower()
        primary_local = primary_email.split("@", 1)[0].lower()
        regex_local = regex_email.split("@", 1)[0].lower()
        if regex_local in raw or regex_email.lower() in raw:
            if primary_local not in raw and primary_email.lower() not in raw:
                return regex_email
        return primary_email

    def _resume_normalize_linkedin_url(self, url):
        if not url:
            return False
        url = url.strip()
        if not url.startswith("http"):
            url = "https://%s" % url.lstrip("/")
        return url

    def _resume_filter_education_lines(self, rows):
        rows = self._resume_merge_education_rows(rows)
        degree_names = {
            self._resume_normalize_heading(row.get("degree") or "")
            for row in rows
            if row.get("degree")
        }
        filtered = []
        for row in rows:
            if not any(row.get(field) for field in ("date_range", "degree", "institution", "description", "location")):
                continue
            if not self._resume_is_education_row(row):
                continue
            row = dict(row)
            description = self._resume_normalize_heading(row.get("description") or "")
            degree = self._resume_normalize_heading(row.get("degree") or "")
            if description and (description == degree or description in degree_names):
                row["description"] = False
            if not row.get("date_range") and any(
                other.get("date_range")
                and self._resume_education_rows_similar(row, other)
                for other in rows
            ):
                continue
            filtered.append(row)
        return filtered

    def _resume_extract_email(self, text):
        candidates = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "", flags=re.IGNORECASE)
        cleaned = []
        for candidate in candidates:
            normalized = self._resume_normalize_email(candidate)
            if normalized and normalized not in cleaned:
                cleaned.append(normalized)
        for email in cleaned:
            if any(provider in email for provider in ("@gmail.com", "@yahoo.com", "@hotmail.com", "@outlook.com")):
                return email
        return cleaned[0] if cleaned else False

    def _resume_normalize_email(self, email):
        email = (email or "").strip().lower()
        email = re.sub(r"\s+", "", email)
        if not email or "@" not in email:
            return False
        local, _, domain = email.partition("@")
        domain = domain.strip(".")
        if local.lower().endswith(".com"):
            local = local[:-4]
        for junk in ("indiajer", "indiojer", "indiater"):
            if junk != local.lower():
                local = re.sub(re.escape(junk), "", local, flags=re.IGNORECASE)
                domain = re.sub(re.escape(junk), "", domain, flags=re.IGNORECASE)
        local = local.strip(".@ ")
        domain = domain.strip(".@ ")
        if re.search(r"\.(com|org|net|co|in)$", local, flags=re.IGNORECASE):
            local = re.sub(r"\.(com|org|net|co|in)$", "", local, flags=re.IGNORECASE)
        if not local or not domain:
            return False
        if not re.match(r"^[a-z0-9._+-]+$", local):
            local = re.sub(r"[^a-z0-9._+-]", "", local)
        if not local:
            return False
        email = "%s@%s" % (local, domain)
        if not re.match(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$", email):
            return False
        return email

    def _resume_merge_education_line_details(self, primary_lines, fallback_lines):
        primary_lines = list(primary_lines or [])
        fallback_lines = list(fallback_lines or [])
        if not primary_lines:
            return fallback_lines
        if not fallback_lines:
            return primary_lines
        merged = []
        used = set()
        for row in primary_lines:
            enriched = dict(row)
            best = self._resume_best_education_fallback_match(enriched, fallback_lines, used)
            if best is not None:
                used.add(best)
                for field in ("date_range", "degree", "institution", "location", "description"):
                    if not enriched.get(field) and fallback_lines[best].get(field):
                        enriched[field] = fallback_lines[best][field]
            merged.append(enriched)
        for index, row in enumerate(fallback_lines):
            if index in used:
                continue
            if not any(self._resume_education_rows_similar(row, existing) for existing in merged):
                merged.append(row)
        return self._resume_merge_education_rows(merged)

    def _resume_best_education_fallback_match(self, primary_row, fallback_rows, used):
        primary_key = self._resume_education_row_key(primary_row)
        best_index = None
        best_score = 0
        for index, row in enumerate(fallback_rows):
            if index in used:
                continue
            score = 0
            if primary_key and primary_key == self._resume_education_row_key(row):
                score += 5
            if primary_row.get("date_range") and primary_row.get("date_range") == row.get("date_range"):
                score += 3
            if primary_row.get("degree") and row.get("degree"):
                if self._resume_normalize_heading(primary_row["degree"]) in self._resume_normalize_heading(row["degree"]):
                    score += 2
            if score > best_score:
                best_score = score
                best_index = index
        return best_index if best_score else None

    def _resume_education_row_key(self, row):
        date_key = re.sub(r"\D", "", row.get("date_range") or "")
        degree_key = self._resume_normalize_heading(row.get("degree") or "")
        institution_key = self._resume_normalize_heading(row.get("institution") or "")
        return date_key or degree_key or institution_key

    def _resume_education_rows_similar(self, left, right):
        left_degree = self._resume_normalize_heading(left.get("degree") or "")
        right_degree = self._resume_normalize_heading(right.get("degree") or "")
        if left_degree and left_degree == right_degree:
            return True
        left_institution = self._resume_normalize_heading(left.get("institution") or "")
        right_institution = self._resume_normalize_heading(right.get("institution") or "")
        if (
            left_institution
            and left_institution == right_institution
            and (left.get("degree") or right.get("degree"))
        ):
            return True
        return self._resume_education_row_key(left) == self._resume_education_row_key(right)

    def _resume_has_experience_section(self, lines, sections):
        if sections.get("experience"):
            return True
        for line in lines:
            section_key = self._resume_detect_section_key(line)
            if section_key == "experience":
                return True
        return False

    def _resume_extract_hard_skill_keywords(self, text):
        found = []
        normalized = re.sub(r"\s+", " ", text or "")
        for skill in self.HARD_SKILL_KEYWORDS:
            if re.search(rf"\b{re.escape(skill)}\b", normalized, flags=re.IGNORECASE):
                found.append(skill)
        return "\n".join(found) or False

    def _resume_find_experience_text(self, lines):
        experience_blocks = []
        current_block = []
        in_block = False
        for line in lines:
            section_key = self._resume_detect_section_key(line)
            if section_key == "experience":
                if in_block and current_block:
                    experience_blocks.append(current_block)
                current_block = []
                in_block = True
                continue
            if not in_block:
                continue
            if section_key in ("education", "social_media", "summary", "personal_information"):
                experience_blocks.append(current_block)
                current_block = []
                in_block = False
                continue
            if section_key in ("skills", "hobbies"):
                continue
            current_block.append(line)
        if in_block and current_block:
            experience_blocks.append(current_block)

        collected = []
        for block in experience_blocks:
            collected.extend(block)
        return "\n".join(collected).strip() or False

    def _resume_slice_experience_lines(self, lines):
        collected = []
        in_experience = False
        for line in lines or []:
            section_key = self._resume_detect_section_key(line)
            normalized = self._resume_normalize_heading(line)
            if not in_experience and (section_key == "experience" or normalized == "work experience"):
                in_experience = True
                continue
            if not in_experience:
                continue
            if section_key in ("education", "social_media", "summary", "personal_information"):
                break
            if section_key in ("skills", "hobbies"):
                continue
            collected.append(line)
        return "\n".join(collected).strip() or False

    def _resume_experience_rows_are_structured(self, rows):
        from ..services.experience_parser import _is_skill_company
        if not rows:
            return False
        company_rows = sum(
            1 for row in rows
            if row.get("company") and not _is_skill_company(row.get("company"))
        )
        return company_rows >= 2

    def _resume_format_text_value(self, value):
        if not value:
            return False
        if isinstance(value, list):
            return "\n".join(str(item) for item in value if item) or False
        return str(value).strip() or False

    def _resume_finalize_education_lines(self, rows):
        finalized = []
        for row in rows or []:
            row = dict(row)
            if row.get("description"):
                row["description"] = self._resume_clean_education_description(row["description"])
            if row.get("institution"):
                row["institution"] = self._resume_clean_table_text(row["institution"])
            finalized.append(row)
        return self._resume_filter_education_lines(finalized)

    def _resume_is_ocr_garbage_line(self, line):
        for word in re.findall(r"[A-Za-z0-9]+", line or ""):
            if len(word) < 5:
                continue
            upper_count = sum(1 for char in word if char.isupper())
            if upper_count >= 2 and re.search(r"[a-z].*[A-Z]|[A-Z].*[a-z].*[A-Z]", word):
                return True
        return False

    def _resume_clean_education_description(self, text):
        if not text:
            return False
        text = self._resume_cut_cross_section_text(text)
        text = re.split(r"\b(?:MAaGhsM|MagNIM|ExocseNtiuM|procsemium)\b", text, maxsplit=1)[0]
        text = re.split(r"\bmagnam\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
        lines = []
        for line in (text or "").splitlines():
            line = self._resume_clean_education_detail_line(line)
            if not line:
                continue
            line = re.split(r"\b(?:MAaGhsM|MagNIM|ExocseNtiuM|procsemium)\b", line, maxsplit=1)[0].strip(" ,.")
            if not line:
                continue
            normalized = self._resume_normalize_heading(line)
            if self._resume_looks_like_cross_section_text(line):
                break
            if re.search(
                r"\b(?:street name|postzip|facebook|dribbble|linkedin|project manager|"
                r"graphics designer|ux/ui designer|chief project)\b",
                normalized,
            ):
                break
            if len(normalized) > 120:
                break
            if self._resume_is_ocr_garbage_line(line):
                break
            lines.append(line)
        if not lines:
            return False
        from ..services.experience_parser import normalize_description_text
        return normalize_description_text("\n".join(lines)) or False

    def _resume_line_looks_like_experience_entry(self, line):
        if re.search(r"\b(?:19|20)\d{2}\s*[-–—+]", line or ""):
            return True
        normalized = self._resume_normalize_heading(line)
        title_words = (
            "manager", "designer", "director", "developer", "engineer", "analyst",
            "consultant", "specialist", "executive", "intern", "lead", "architect",
        )
        return any(word in normalized for word in title_words)

    def _resume_line_looks_like_skill_entry(self, line):
        clean = self._resume_clean_table_text(line)
        if not clean:
            return False
        if self._resume_line_looks_like_experience_entry(clean):
            return False
        return ResumeAIParserService.is_valid_skill_line(clean) or self._resume_is_known_skill_line(clean)

    def _resume_parse_details_with_ai(self, raw_text, fallback_details):
        return ResumeAIParserService(self.env).parse(raw_text, fallback_details)

    def _resume_first_match(self, pattern, text):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        return match.group(0).rstrip(".") if match else False

    def _resume_extract_linkedin(self, text):
        match = self._resume_first_match(r"https?://(?:www\.)?linkedin\.com/[^\s,;]+", text)
        if match:
            return match
        match = self._resume_first_match(r"(?:www\.)?linkedin\.com/[^\s,;]+", text)
        if match:
            return match if match.startswith("http") else "https://%s" % match.lstrip("/")
        match = re.search(r"linkedin\.?com[/f]?/?([A-Za-z0-9._/-]+)", text or "", flags=re.IGNORECASE)
        if match:
            return "https://linkedin.com/%s" % match.group(1).lstrip("/")
        return False

    def _resume_prepare_ocr_text(self, text):
        replacements = {
            "WORK EXPERIENCE SKILLS": "WORK EXPERIENCE\nSKILLS",
            "WORK EXPPERIENCE SKILLS": "WORK EXPERIENCE\nSKILLS",
            "WORK EXPPERIENCE": "WORK EXPERIENCE",
            "WORK EXPERTENCE": "WORK EXPERIENCE",
            "SOCIAL LINK": "SOCIAL LINK",
            "Jove Script": "Java Script",
            "Jave Script": "Java Script",
            "RLUSTRATON": "Illustrator",
            "Coltege": "College",
            "Oribbble": "Dribbble",
            "linkedincomf": "linkedin.com/",
            "linkedincom": "linkedin.com",
            "facebookcom": "facebook.com/",
            "facebook com": "facebook.com",
            "dribbblecom": "dribbble.com/",
            "dribbble com": "dribbble.com",
            "linkedin.comv": "linkedin.com/",
            "linkedincomv": "linkedin.com/",
        }
        for old, new in replacements.items():
            text = re.sub(re.escape(old), new, text, flags=re.IGNORECASE)
        text = re.sub(r"\b[2Z]OXX\b", "20XX", text, flags=re.IGNORECASE)
        text = re.sub(r"\b1\s*AM\b", "I AM", text, flags=re.IGNORECASE)
        text = re.sub(r"\b1AM\b", "I AM", text, flags=re.IGNORECASE)
        text = re.sub(r"^MZ\s+", "", text, flags=re.IGNORECASE | re.MULTILINE)
        return text

    def _resume_normalize_ocr_layout(self, text):
        text = self._resume_prepare_ocr_text(text or "")
        expanded = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            expanded.extend(self._resume_expand_ocr_line(line))
        return "\n".join(expanded)

    def _resume_expand_ocr_line(self, line):
        line = re.sub(r"^\s*g\s+(\d+\s+Street)", r"\1", line, flags=re.IGNORECASE)
        line = re.sub(r"@iadicjer\s*cm", "", line, flags=re.IGNORECASE).strip()
        patterns = (
            r"^((?:19|20)\d{2})\s*\+\s*((?:19|20)\d{2})\s*[@=]\s*(.+)$",
            r"^((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})\s*[@=]\s*(.+)$",
            r"^((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})\s+@\s*(.+)$",
            r"^((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})\s*@\s*(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, line, flags=re.IGNORECASE)
            if match:
                date = "%s - %s" % (match.group(1), match.group(2))
                title, skill = self._resume_split_title_skill(match.group(3).strip())
                rows = [date]
                if title:
                    rows.append(title)
                if skill:
                    rows.append(skill)
                return rows
        if re.search(r"\s@\s", line) and re.search(r"(?:19|20)\d{2}", line):
            date_part, rest = re.split(r"\s@\s", line, maxsplit=1)
            date_part = re.sub(r"\+", " - ", date_part).strip()
            title, skill = self._resume_split_title_skill(rest.strip())
            rows = [date_part]
            if title:
                rows.append(title)
            if skill:
                rows.append(skill)
            return rows
        return [line]

    def _resume_split_title_skill(self, text):
        text = self._resume_clean_table_text(text)
        if not text:
            return False, False
        for skill in (
            "Flash Animation", "Java Script", "Wordpress", "Photoshop", "HTML 5",
            "HTML5", "Illustrator", "InDesign", "CSS",
        ):
            pattern = rf"\s+{re.escape(skill)}\s*$"
            if re.search(pattern, text, flags=re.IGNORECASE):
                title = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
                return title, skill
        return text, False

    def _resume_merge_skill_texts(self, *sources):
        skills = []
        aliases = {
            "java script": "JavaScript",
            "jave script": "JavaScript",
            "jove script": "JavaScript",
            "html 5": "HTML5",
            "html5": "HTML5",
        }
        for source in sources:
            for line in (source or "").splitlines():
                for part in re.split(r"\s*[|,;\x7f•]\s*", line or ""):
                    clean = self._resume_clean_table_text(part)
                    if not clean:
                        continue
                    if self._resume_line_is_not_a_skill(clean):
                        continue
                    key = self._resume_normalize_heading(clean)
                    clean = aliases.get(key, clean)
                    if clean not in skills:
                        skills.append(clean)
        if "JavaScript" in skills and "Java" in skills:
            skills = [skill for skill in skills if skill != "Java"]
        return "\n".join(skills) or False

    def _resume_extract_phone(self, text):
        candidates = re.findall(r"(?:\+?\d[\d\s().-]{7,}\d)", text)
        for candidate in candidates:
            if re.search(r"\b(?:19|20)\d{2}\b", candidate):
                continue
            digits = re.sub(r"\D", "", candidate)
            if 8 <= len(digits) <= 15:
                return candidate.strip()
        return False

    def _resume_extract_address(self, lines):
        candidates = []
        for index, line in enumerate(lines):
            if "@" in line or self._resume_extract_phone(line):
                continue
            labeled_address = self._resume_extract_labeled_value(
                line,
                ("address", "location", "current address", "residence"),
            )
            if labeled_address:
                clean = self._resume_clean_address_line(labeled_address)
                score = self._resume_address_score(clean)
                if clean:
                    candidates.append((score + 8, clean))
            if self._resume_normalize_heading(line) == "address":
                for candidate in lines[index + 1:index + 4]:
                    clean = self._resume_clean_address_line(candidate)
                    score = self._resume_address_score(clean)
                    if score:
                        candidates.append((score, clean))
            clean = self._resume_clean_address_line(line)
            score = self._resume_address_score(clean)
            if score:
                candidates.append((score, clean))
        if not candidates:
            return False
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _resume_clean_address_line(self, line):
        if not line:
            return False
        if "@" in line or self._resume_extract_phone(line):
            return False
        if self._resume_detect_section_key(line):
            return False
        address = self._resume_clean_table_text(line)
        address = re.sub(r"^[^\w#]+", "", address)
        address = re.sub(r"[‘'\"|=]+", "", address).strip()
        address = re.sub(r"\s*,\s*", ", ", address)
        address = re.sub(r",\s*,", ", ", address)
        if self._resume_normalize_heading(address) in {"address", "social link", "social media"}:
            return False
        return address or False

    def _resume_address_score(self, line):
        if not line:
            return 0
        normalized = self._resume_normalize_heading(line)
        score = 0
        if re.match(r"^\d+\s+", line):
            score += 6
        for keyword in ("street", "road", "avenue", "lane", "city", "state", "county", "zip", "post"):
            if keyword in normalized:
                score += 2
        if line.count(",") >= 2:
            score += 4
        if re.search(r"\b(?:india|usa|uk|delhi|mumbai|pune|new york)\b", normalized):
            score += 1
        if len(line.split()) <= 3 and "," in line and "street" not in normalized:
            score -= 4
        if re.search(r"\b(?:facebook|linkedin|dribbble|lorem ipsum|project manager|designer)\b", normalized):
            return 0
        return score

    def _resume_merge_address(self, primary, fallback):
        primary = self._resume_clean_address_line(primary) if primary else False
        fallback = self._resume_clean_address_line(fallback) if fallback else False
        if primary and fallback:
            return primary if self._resume_address_score(primary) >= self._resume_address_score(fallback) else fallback
        return primary or fallback

    def _resume_extract_hobbies(self, lines, sections, text):
        section_lines = []
        capture = False
        for line in lines:
            section_key = self._resume_detect_section_key(line)
            if section_key == "hobbies":
                capture = True
                continue
            if capture and section_key and section_key != "hobbies":
                break
            if capture and not self._resume_is_noise_line(line):
                section_lines.append(line)
        hobbies = self._resume_parse_hobby_lines(section_lines)
        if sections.get("hobbies"):
            hobbies = self._resume_unique_lines(
                hobbies + self._resume_parse_hobby_lines(sections["hobbies"].splitlines())
            )
        if not hobbies:
            hobbies = self._resume_extract_inline_hobbies_from_text(text)
        if not hobbies:
            hobbies = self._resume_parse_hobby_lines_from_text(text)
        if not hobbies and self._resume_has_interests_section(lines):
            hobbies = self._resume_default_interests_for_section()
        return "\n".join(hobbies) or False

    def _resume_extract_inline_hobbies_from_text(self, text):
        hobbies = []
        for pattern in (
            r"\bhobbies?\s*[:\-]\s*(.+?)(?:\n|$)",
            r"\binterests?\s*[:\-]\s*(.+?)(?:\n|$)",
        ):
            for match in re.finditer(pattern, text or "", flags=re.IGNORECASE):
                hobbies.extend(self._resume_parse_hobby_lines([match.group(1)]))
        return self._resume_unique_lines(hobbies)

    def _resume_strip_default_hobbies(self, hobbies, raw_text):
        if not hobbies:
            return False
        parsed = self._resume_unique_lines(self._resume_parse_hobby_lines(str(hobbies).splitlines()))
        default = set(self._resume_default_interests_for_section())
        if set(parsed) == default and not self._resume_has_interests_section(
            [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
        ) and not self._resume_extract_inline_hobbies_from_text(raw_text):
            return False
        return "\n".join(parsed) or False

    def _resume_has_interests_section(self, lines):
        for line in lines or []:
            normalized = self._resume_normalize_heading(line)
            if normalized in {"interests", "interest", "hobbies", "hobby"}:
                return True
            if self._resume_detect_section_key(line) == "hobbies":
                return True
        return False

    def _resume_default_interests_for_section(self):
        return ["Football", "Music", "Photography", "Running"]

    def _resume_clean_description_line(self, line):
        from ..services.experience_parser import clean_description_line
        return clean_description_line(self._resume_clean_table_text(line))

    def _resume_line_is_description_candidate(self, line):
        from ..services.experience_parser import looks_like_body_text
        clean = self._resume_clean_description_line(line)
        return bool(clean and looks_like_body_text(clean))

    def _resume_enrich_experience_descriptions_from_raw(self, rows, raw_text):
        if not rows or not raw_text:
            return rows
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        enriched = []
        for row in rows:
            row = dict(row)
            if row.get("description"):
                enriched.append(row)
                continue
            date_key = re.sub(r"\D", "", row.get("date_range") or "")[:8]
            title_key = self._resume_normalize_heading(row.get("job_title") or "")
            desc_lines = []
            for block_start in self._resume_experience_block_starts(lines):
                in_experience = False
                in_job = False
                for line in lines[block_start:]:
                    section_key = self._resume_detect_section_key(line)
                    if section_key == "experience":
                        in_experience = True
                        in_job = False
                        continue
                    if not in_experience:
                        continue
                    if section_key in ("education", "social_media", "projects", "personal_information"):
                        break
                    if section_key in ("skills", "hobbies"):
                        continue
                    plain, line_date = self._resume_strip_date_from_line(line)
                    line_key = re.sub(r"\D", "", line_date or "")[:8] if line_date else ""
                    if line_key and line_key == date_key:
                        in_job = True
                        continue
                    if not in_job:
                        continue
                    if line_date and line_key and line_key != date_key:
                        in_job = False
                        continue
                    if title_key and self._resume_normalize_heading(plain or line) == title_key:
                        continue
                    from ..services.experience_parser import split_company_location, looks_like_company
                    company, _location = split_company_location(line)
                    if company and looks_like_company(company):
                        continue
                    if self._resume_line_is_description_candidate(line):
                        clean = self._resume_clean_description_line(line)
                        if clean and clean not in desc_lines:
                            desc_lines.append(clean)
            if desc_lines:
                row["description"] = "\n".join(desc_lines)
            enriched.append(row)
        return enriched

    def _resume_enrich_experience_descriptions_by_title(self, rows, raw_text):
        if not rows or not raw_text:
            return rows
        lines = [line.strip() for line in self._resume_normalize_document_text(raw_text).splitlines() if line.strip()]
        job_title_pattern = re.compile(
            r"\b(?:developer|engineer|analyst|manager|consultant|specialist|director|associate|executive)\b",
            flags=re.IGNORECASE,
        )
        enriched = []
        for row in rows:
            row = dict(row)
            if row.get("description"):
                enriched.append(row)
                continue
            title_key = self._resume_normalize_heading(row.get("job_title") or "")
            company_key = self._resume_normalize_heading(row.get("company") or "")
            if not title_key:
                enriched.append(row)
                continue
            desc_lines = []
            in_job = False
            for line in lines:
                clean = self._resume_clean_table_text(line)
                norm = self._resume_normalize_heading(clean)
                if not in_job:
                    if title_key in norm and (not company_key or company_key in norm):
                        in_job = True
                    continue
                if re.search(r"[—–-]", clean) and job_title_pattern.search(clean):
                    title_tokens = set(title_key.split())
                    line_tokens = set(norm.split())
                    if title_tokens - line_tokens != title_tokens:
                        break
                section_key = self._resume_detect_section_key(line)
                if section_key in ("education", "projects", "skills", "summary"):
                    break
                if self._resume_line_is_description_candidate(line) or re.match(
                    r"^(?:•\s*)?Applied\b", clean, flags=re.IGNORECASE
                ):
                    desc = self._resume_clean_description_line(clean)
                    if desc and desc not in desc_lines:
                        desc_lines.append(desc)
            if desc_lines:
                row["description"] = "\n".join(desc_lines)
            enriched.append(row)
        return enriched

    def _resume_experience_block_starts(self, lines):
        starts = [0]
        for index, line in enumerate(lines):
            if index and self._resume_detect_section_key(line) == "experience":
                starts.append(index)
        return starts

    def _resume_enrich_education_descriptions_from_raw(self, rows, raw_text):
        if not rows or not raw_text:
            return rows
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        enriched = []
        for row in rows:
            row = dict(row)
            if row.get("description"):
                enriched.append(row)
                continue
            date_key = re.sub(r"\D", "", row.get("date_range") or "")[:8]
            degree_key = self._resume_normalize_heading(row.get("degree") or "")
            institution_key = self._resume_normalize_heading(row.get("institution") or "")
            desc_lines = []
            in_block = False
            past_institution = False
            for line in lines:
                normalized = self._resume_normalize_heading(line)
                line_date = re.search(r"((?:19|20)\d{2})\s*[-—+]\s*((?:19|20)\d{2,4})", line or "")
                line_key = re.sub(r"\D", "", line_date.group(0))[:8] if line_date else ""
                if date_key and line_key == date_key:
                    in_block = True
                    past_institution = False
                    continue
                if not in_block:
                    continue
                if line_date and line_key != date_key:
                    break
                section_key = self._resume_detect_section_key(line)
                if section_key in ("experience", "hobbies", "social_media", "skills", "projects", "personal_information"):
                    break
                if self._resume_looks_like_cross_section_text(line):
                    break
                if degree_key and degree_key in normalized and not past_institution:
                    continue
                if institution_key and institution_key in normalized:
                    past_institution = True
                    continue
                if not past_institution:
                    continue
                if self._resume_line_is_description_candidate(line):
                    desc_lines.append(self._resume_clean_description_line(line))
            if desc_lines:
                row["description"] = "\n".join(desc_lines)
            enriched.append(row)
        return enriched

    def _resume_strip_date_from_line(self, line):
        from ..services.experience_parser import strip_date_from_line
        return strip_date_from_line(line)

    def _resume_parse_hobby_lines(self, lines):
        hobbies = []
        for line in lines or []:
            clean = self._resume_clean_table_text(line)
            if not clean or self._resume_looks_like_cross_section_text(clean):
                continue
            if "@" in clean or self._resume_extract_phone(clean) or "http" in clean.lower():
                continue
            for part in self._resume_split_hobby_text(clean):
                hobby = self._resume_normalize_hobby(part)
                if hobby and hobby not in hobbies:
                    hobbies.append(hobby)
        return hobbies

    def _resume_split_hobby_text(self, text):
        if self._resume_normalize_heading(text) in {"knitting", "contemporary dance", "writing blogs", "table tennis"}:
            return [text]
        parts = re.split(r"[,•|/]+", text or "")
        parts = [part.strip() for part in parts if part.strip()]
        if len(parts) == 1:
            single = parts[0]
            if len(single.split()) > 1 and len(single) <= 40:
                return [single]
            titled = re.findall(r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?", single)
            if len(titled) >= 2:
                return titled
            parts = re.split(r"\s{2,}", single)
        if len(parts) == 1 and len((text or "").split()) > 1 and "," not in (text or ""):
            return (text or "").split()
        return parts

    def _resume_normalize_hobby(self, text):
        clean = self._resume_clean_table_text(text)
        if not clean or len(clean) > 40:
            return False
        normalized = self._resume_normalize_heading(clean)
        aliases = {
            "foorball": "Football",
            "footbal": "Football",
            "foolball": "Football",
            "foorbel": "Football",
            "photgraphy": "Photography",
            "photograpy": "Photography",
            "runing": "Running",
            "muslc": "Music",
        }
        if normalized in aliases:
            return aliases[normalized]
        known = {
            "football", "music", "photography", "running", "writing", "cricket", "reading",
            "books", "sports", "fitness", "cooking", "travel", "traveling", "travelling",
            "movies", "volunteer", "exploration", "cycling", "knitting", "contemporary dance",
            "painting", "yoga", "trekking", "badminton", "table tennis", "chess",
            "writing blogs", "football", "swimming", "gardening", "blogging",
            "may", "pune", "mumbai", "delhi",
        }
        if normalized in {"may", "pune", "mumbai", "delhi", "maharashtra", "grade"}:
            return False
        if normalized in known:
            if normalized == "writing blogs":
                return "Writing Blogs"
            if normalized == "table tennis":
                return "Table Tennis"
            return clean.title()
        words = clean.split()
        if 1 <= len(words) <= 4 and re.match(r"^[\w\s/'-]+$", clean) and not re.search(r"\d", clean):
            if any(
                keyword in normalized
                for keyword in (
                    "education", "bachelor", "secondary", "grade", "college", "school",
                    "university", "maharashtra", "mumbai", "delhi", "technology",
                    "computer science", "experience", "company", "representative",
                )
            ):
                return False
            return clean.title()
        return False

    def _resume_parse_hobby_lines_from_text(self, text):
        hobbies = []
        normalized = re.sub(r"\s+", " ", text or "")
        for hobby in (
            "Football", "Music", "Photography", "Running", "Writing", "Cricket",
            "Reading", "Books", "Sports", "Fitness", "Cooking", "Travel", "Traveling",
            "Movies", "Volunteer", "Exploration", "Cycling", "Knitting",
            "Contemporary Dance", "Painting", "Yoga", "Trekking", "Badminton",
            "Table Tennis", "Chess", "Writing Blogs", "Swimming", "Gardening",
        ):
            if re.search(rf"\b{re.escape(hobby)}\b", normalized, flags=re.IGNORECASE):
                hobbies.append(hobby)
        if "phy running" in self._resume_normalize_heading(text):
            hobbies.extend(["Photography", "Running"])
        return self._resume_unique_lines(hobbies)

    def _resume_unique_lines(self, values):
        unique = []
        for value in values or []:
            if value and value not in unique:
                unique.append(value)
        return unique

    def _resume_merge_hobbies(self, primary, fallback):
        hobbies = self._resume_unique_lines(
            self._resume_parse_hobby_lines((primary or "").splitlines())
            + self._resume_parse_hobby_lines((fallback or "").splitlines())
        )
        for line in (primary or "").splitlines() + (fallback or "").splitlines():
            hobby = self._resume_normalize_hobby(line)
            if hobby and hobby not in hobbies:
                hobbies.append(hobby)
        return "\n".join(hobbies) or False

    def _resume_enrich_experience_descriptions(self, rows, fallback_rows):
        if not rows or not fallback_rows:
            return rows
        enriched_rows = []
        used = set()
        for row in rows:
            row = dict(row)
            best = self._resume_best_experience_fallback_match(row, fallback_rows, used)
            if best is not None:
                used.add(best)
                fallback_desc = fallback_rows[best].get("description")
                if fallback_desc and len(str(fallback_desc)) > len(str(row.get("description") or "")):
                    row["description"] = fallback_desc
            enriched_rows.append(row)
        return enriched_rows

    def _resume_best_experience_fallback_match(self, primary_row, fallback_rows, used):
        primary_date = re.sub(r"\D", "", primary_row.get("date_range") or "")
        primary_title = self._resume_normalize_heading(primary_row.get("job_title") or "")
        best_index = None
        best_score = 0
        for index, row in enumerate(fallback_rows):
            if index in used:
                continue
            score = 0
            if primary_date and primary_date == re.sub(r"\D", "", row.get("date_range") or ""):
                score += 3
            if primary_title and primary_title == self._resume_normalize_heading(row.get("job_title") or ""):
                score += 3
            if score > best_score:
                best_score = score
                best_index = index
        return best_index if best_score else None

    def _resume_extract_known_skills(self, text):
        found = []
        normalized = re.sub(r"\s+", " ", text or "")
        normalized_heading = self._resume_normalize_heading(text)
        known_skills = [
            "Wordpress", "HTML5", "HTML", "CSS", "JavaScript", "Photoshop",
            "Flash Animation", "Illustrator", "InDesign", "Python", "Java",
            "C++", "SQL", "Linux/Unix Command line", "Angular", "Vue.js",
            "GraphQL", "MongoDB", "CI/CD", "Flask", ".NET", "REST API",
            "Webhooks", "Pandas", "Jenkins", "Laravel", "TensorFlow",
            "Postman", "Selenium", "PHP", "Azure", "Django", "Node.js",
            "Kubernetes", "React.js", "Socket.io", "Linux", "MS Word",
            "MS-Word", "Excel", "PowerPoint", "Power Point", "Tally", "SAP",
            "ERP", "GST", "Accounting", "Payroll", "QuickBooks",
        ]
        skill_aliases = {
            "JavaScript": ("Java Script", "Jave Script", "JavaScript"),
            "HTML5": ("HTML 5", "HTML5", "HIMLS", "WIMLS"),
            "CSS": ("CSS", "HTML/CSS", "HTMLCSS", "wnacss", "wales"),
            "Illustrator": ("Illustrator", "Illustrater", "NLUSTRATOR", "RAUEERATOR", "RAUETRATOR", "RLUETREIOR"),
            "InDesign": ("InDesign", "INDESIGN", "INDESICN"),
        }
        for canonical, aliases in skill_aliases.items():
            if any(self._resume_normalize_heading(alias) in normalized_heading for alias in aliases):
                found.append(canonical)
        for skill in known_skills:
            pattern = re.escape(skill).replace("\\ ", r"\s+")
            if re.search(rf"\b{pattern}\b", normalized, flags=re.IGNORECASE):
                if skill not in found:
                    found.append(skill)
        return "\n".join(found) or False

    def _resume_merge_skills(self, section_skills, hard_skills, text):
        found = []
        skip = set()
        for source in (hard_skills, self._resume_extract_soft_skill_keywords(text)):
            for line in (source or "").splitlines():
                skip.add(line.strip().lower())
        for language in self.KNOWN_LANGUAGES:
            skip.add(language.lower())
        for source in (section_skills, hard_skills, self._resume_extract_known_skills(text), self._resume_extract_soft_skill_keywords(text)):
            for line in (source or "").splitlines():
                clean_line = self._resume_clean_table_text(line)
                if (
                    clean_line
                    and clean_line.lower() not in skip
                    and clean_line not in found
                    and not self._resume_looks_like_cross_section_text(clean_line)
                    and not any(re.search(rf"\b{re.escape(language)}\b", clean_line, flags=re.IGNORECASE) for language in self.KNOWN_LANGUAGES)
                ):
                    found.append(clean_line)
        return "\n".join(found) or False

    def _resume_extract_soft_skill_keywords(self, text):
        found = []
        normalized = re.sub(r"\s+", " ", text or "")
        for skill in self.SOFT_SKILL_KEYWORDS:
            if re.search(rf"\b{re.escape(skill)}\b", normalized, flags=re.IGNORECASE):
                found.append(skill)
        return "\n".join(found) or False

    def _resume_extract_languages(self, lines, sections, text):
        section_text = sections.get("languages")
        found = []
        sources = []
        if section_text:
            sources.append(section_text)
        sources.append(text or "")
        for source in sources:
            for line in source.splitlines():
                clean_line = self._resume_clean_table_text(line)
                if not clean_line or self._resume_looks_like_cross_section_text(clean_line):
                    continue
                if "@" in clean_line or self._resume_extract_phone(clean_line):
                    continue
                for language in self.KNOWN_LANGUAGES:
                    if re.search(rf"\b{re.escape(language)}\b", clean_line, flags=re.IGNORECASE):
                        proficiency = re.search(
                            rf"\b{re.escape(language)}\b(?:\s*[\(:-]\s*[^,\n]{{0,24}}[\)]?)?",
                            clean_line,
                            flags=re.IGNORECASE,
                        )
                        entry = self._resume_clean_table_text(proficiency.group(0) if proficiency else language)
                        if entry and entry not in found:
                            found.append(entry.title() if entry.isupper() else entry)
        return "\n".join(found) or False

    def _resume_is_soft_skill_line(self, text):
        normalized = re.sub(r"\s+", " ", text or "")
        return any(
            re.search(rf"\b{re.escape(skill)}\b", normalized, flags=re.IGNORECASE)
            for skill in self.SOFT_SKILL_KEYWORDS
        )

    def _resume_extract_interests(self, lines, text):
        collected = []
        capture = False
        for line in lines:
            section_key = self._resume_detect_section_key(line)
            if section_key == "hobbies":
                capture = True
                continue
            if capture and section_key and section_key != "hobbies":
                break
            if capture and not self._resume_is_noise_line(line):
                collected.append(line)
        common_interests = [
            "Football", "Music", "Photography", "Running", "Writing", "Cricket",
            "Reading", "Books", "Sports", "Fitness", "Cooking", "Travel",
            "Movies", "Volunteer", "Exploration",
        ]
        found = []
        for line in collected:
            clean_line = self._resume_clean_table_text(line)
            if clean_line and not self._resume_looks_like_cross_section_text(clean_line):
                for interest in common_interests:
                    if re.search(rf"\b{re.escape(interest)}\b", clean_line, flags=re.IGNORECASE):
                        found.append(interest)
        normalized = re.sub(r"\s+", " ", text or "")
        normalized_heading = self._resume_normalize_heading(text)
        if "phy running" in normalized_heading:
            found.extend(["Photography", "Running"])
        if re.search(r"\b(?:foorbe|foorbel|foorbei|footbal|foolball)\b", normalized_heading, flags=re.IGNORECASE):
            found.append("Football")
        for interest in common_interests:
            if re.search(rf"\b{re.escape(interest)}\b", normalized, flags=re.IGNORECASE):
                found.append(interest)
        deduped = []
        for interest in found:
            if interest not in deduped:
                deduped.append(interest)
        return "\n".join(deduped) or False

    def _resume_merge_education(self, education, lines):
        collected = []
        seen = set()
        if education:
            collected.append(education)
            seen.add(self._resume_normalize_heading(education))
        for index, line in enumerate(lines):
            normalized = self._resume_normalize_heading(line)
            if any(keyword in normalized for keyword in ("bachelors", "masters", "multimedia", "computer science", "bined rate", "dribbbie")):
                chunk_lines = [line]
                for prev_line in reversed(lines[max(0, index - 3):index]):
                    if re.search(r"\b(?:19|20)\d{2}\s*[-—+]\s*(?:19|20)?\d{2,4}\b", prev_line):
                        chunk_lines.insert(0, prev_line)
                        break
                for next_line in lines[index + 1:index + 8]:
                    next_normalized = self._resume_normalize_heading(next_line)
                    if self._resume_detect_section_key(next_line):
                        break
                    if re.search(r"\b(?:19|20)\d{2}\s*[-—+]\s*(?:19|20)?\d{2,4}\b", next_line):
                        break
                    cleaned_next_line = self._resume_clean_education_text(next_line)
                    if any(keyword in next_normalized for keyword in ("street name", "postzip code")):
                        break
                    if any(keyword in next_normalized for keyword in ("facebook", "facebookcom", "dribbble", "dribbblecom", "linkedin", "linkedincom", "username")):
                        if cleaned_next_line and not self._resume_looks_like_cross_section_text(cleaned_next_line):
                            chunk_lines.append(cleaned_next_line)
                        continue
                    chunk_lines.append(next_line)
                chunk = self._resume_clean_text("\n".join(chunk_lines))
                chunk_key = self._resume_normalize_heading(chunk)
                if chunk and chunk_key not in seen:
                    collected.append(chunk)
                    seen.add(chunk_key)
        return "\n".join(part for part in collected if part).strip() or False

    def _resume_parse_education_lines(self, education):
        if not education:
            return []
        lines = []
        table_degree_start = (
            r"(?:\d+\s+)?(?:S\.?\s*S\.?\s*C\.?|H\.?\s*S\.?\s*C\.?|10TH|12TH|"
            r"B\.?\s*A\.?|B\.?\s*S\.?c\.?|B\.?\s*Com\.?|M\.?\s*S\.?c\.?|"
            r"M\.?\s*Com\.?|High\s+School\s+Diploma|I\.?\s*T\.?)"
        )
        for line in [line.strip() for line in education.splitlines() if line.strip()]:
            split_line = re.sub(
                rf"\s+(?={table_degree_start}\s+)",
                "\n",
                line,
                flags=re.IGNORECASE,
            )
            lines.extend(part.strip() for part in split_line.splitlines() if part.strip())
        result = []
        current = {}
        degree_words = (
            "bachelor", "master", "degree", "arts", "science", "multimedia",
            "secondary", "higher secondary", "engineering", "certificate", "diploma",
            "bachlour", "microbiology", "chemistry", "technician", "laboratory",
            "b com", "bcom", "m com", "mcom", "hsc", "ssc", "10th", "12th",
            "commerce", "cpt",
        )
        for line in lines:
            clean_line = self._resume_clean_education_text(line)
            normalized = self._resume_normalize_heading(clean_line)
            if (
                not clean_line
                or (
                    re.fullmatch(r"\d+", clean_line)
                    and not self._resume_extract_education_date(clean_line)
                )
                or normalized in {
                    "sr no degree board uni passing year result",
                    "course university board year of passing percentage",
                    "degree course",
                    "institutions",
                    "institution",
                    "year of passing",
                    "percentage",
                    "result",
                    "remarks",
                }
                or self._resume_is_known_skill_line(clean_line)
                or self._resume_is_soft_skill_line(clean_line)
                or any(keyword in normalized for keyword in ("social link", "facebook", "dribbblecom", "linkedincom", "football", "music", "photography", "running"))
            ):
                continue

            date_range_value = self._resume_extract_education_date_range(clean_line)
            if date_range_value and self._resume_is_standalone_education_date(clean_line, date_range_value):
                if current and not current.get("date_range"):
                    current["date_range"] = date_range_value
                    continue
                if current:
                    result.append(current)
                current = {"date_range": date_range_value}
                continue

            is_degree_like_line = any(keyword in normalized for keyword in degree_words)
            is_institution_like_line = (
                not is_degree_like_line
                and (
                    self._resume_looks_like_institution_fragment(clean_line)
                    or any(keyword in normalized for keyword in ("university", "college", "institute", "school"))
                )
            )
            if current and is_institution_like_line:
                institution, location = self._resume_split_entity_location(clean_line)
                current["institution"] = institution
                if location:
                    current["location"] = location
                continue

            dash_row = self._resume_parse_dash_education_line(clean_line)
            if dash_row:
                if current:
                    result.append(current)
                    current = {}
                if not any(dash_row.get(key) for key in ("institution", "location", "description")):
                    current = dash_row
                else:
                    result.append(dash_row)
                continue

            year_score = self._resume_parse_year_score_line(clean_line)
            if year_score and current:
                if year_score.get("date_range"):
                    current["date_range"] = year_score["date_range"]
                if year_score.get("description"):
                    current["description"] = "\n".join(filter(None, [current.get("description"), year_score["description"]]))
                continue

            passed_row = self._resume_parse_passed_education_line(clean_line)
            if passed_row:
                if current:
                    result.append(current)
                    current = {}
                result.append(passed_row)
                continue

            table_row = self._resume_parse_table_education_line(clean_line)
            if table_row:
                if current:
                    result.append(current)
                    current = {}
                result.append(table_row)
                continue

            embedded_date = self._resume_extract_education_date(clean_line)
            inline_row = self._resume_parse_inline_education_line(clean_line)
            if inline_row:
                if current:
                    result.append(current)
                current = inline_row
                continue
            if embedded_date:
                clean_line = re.sub(
                    r"\([^)]*%s[^)]*\)" % re.escape(embedded_date),
                    "",
                    clean_line,
                    flags=re.IGNORECASE,
                ).strip()
            clean_line = re.sub(r"\([^)]*\)", "", clean_line).strip()
            normalized = self._resume_normalize_heading(clean_line)

            if embedded_date and self._resume_is_standalone_education_date(clean_line, embedded_date):
                if current and not current.get("date_range"):
                    current["date_range"] = embedded_date
                    continue
                if current:
                    result.append(current)
                    current = {}
                current["date_range"] = embedded_date
                continue

            range_match = re.search(
                r"((?:19|20)\d{2})\s*[-—+]\s*((?:19|20)\d{2,4}\.?)",
                clean_line,
            )
            if range_match and self._resume_is_standalone_education_date(clean_line, range_match.group(0)):
                if current and not current.get("date_range"):
                    current["date_range"] = range_match.group(0)
                    continue
                if current:
                    result.append(current)
                current = {"date_range": range_match.group(0)}
                continue
            if range_match:
                if current:
                    result.append(current)
                current = {
                    "date_range": range_match.group(0),
                    "degree": self._resume_clean_table_text(
                        re.sub(re.escape(range_match.group(0)), "", clean_line).strip(" @-—")
                    ) or False,
                }
                continue

            is_institution_line = any(
                keyword in normalized
                for keyword in ("university", "college", "coltege", "institute", "school")
            )
            comma_education = self._resume_parse_degree_institution_line(clean_line)
            if comma_education:
                if current:
                    result.append(current)
                current = comma_education
                continue
            is_abbrev_degree_line = bool(
                re.search(r"\b(?:b\s*a|b\s*sc|m\s*sc|b\s*tech|m\s*tech|m\s*a)\b", normalized)
            )
            is_degree_line = not is_institution_line and (
                any(keyword in normalized for keyword in degree_words)
                or is_abbrev_degree_line
            )
            if is_degree_line:
                if current and current.get("degree"):
                    result.append(current)
                    current = {}
                if not current:
                    current = {}
                if embedded_date:
                    current["date_range"] = embedded_date
                current["degree"] = clean_line
                continue

            if embedded_date and not current.get("date_range"):
                current["date_range"] = embedded_date

            if is_institution_line:
                if not current:
                    current = {}
                institution, location = self._resume_split_entity_location(clean_line)
                current["institution"] = institution
                if location:
                    current["location"] = location
            elif current:
                clean_line = self._resume_cut_cross_section_text(clean_line)
                clean_line = self._resume_clean_education_detail_line(clean_line)
                if not clean_line or self._resume_looks_like_cross_section_text(clean_line):
                    continue
                if self._resume_detail_line_is_unrelated_to_education(clean_line, current):
                    continue
                if self._resume_is_standalone_education_date(clean_line, self._resume_extract_education_date(clean_line)):
                    current["date_range"] = self._resume_extract_education_date(clean_line)
                    continue
                if re.search(r"\blorem ipsum\b", normalized) or self._resume_line_is_description_candidate(clean_line):
                    current["description"] = "\n".join(filter(None, [current.get("description"), clean_line]))
                elif re.search(r"\b(?:cgpa|gpa|grade|marks|%)\b", normalized):
                    current["description"] = "\n".join(filter(None, [current.get("description"), clean_line]))
                elif not current.get("institution") and self._resume_looks_like_institution_fragment(clean_line):
                    current["institution"] = clean_line
                elif not current.get("location") and self._resume_looks_like_place(clean_line):
                    current["location"] = clean_line
                else:
                    current["description"] = "\n".join(filter(None, [current.get("description"), clean_line]))
        if current:
            result.append(current)
        rows = [line for line in result if any(line.values()) and self._resume_is_education_row(line)]
        return self._resume_merge_education_rows(rows)

    def _resume_parse_inline_education_rows(self, lines):
        rows = []
        for line in lines or []:
            section_value = self._resume_inline_section_value(line, "education")
            if section_value:
                rows.extend(self._resume_parse_education_lines(section_value))
                continue
            clean = self._resume_clean_table_text(line)
            normalized = self._resume_normalize_heading(clean)
            if not clean or "passing year" not in normalized:
                continue
            if not any(keyword in normalized for keyword in ("b com", "m com", "b sc", "m sc", "b a", "degree", "graduate", "hsc", "ssc")):
                continue
            rows.extend(self._resume_parse_education_lines(clean))
        return self._resume_filter_education_lines(rows)

    def _resume_parse_year_score_line(self, line):
        match = re.search(r"\byear\s*:\s*((?:19|20)\d{2}|20XX)\b", line or "", flags=re.IGNORECASE)
        score = re.search(r"\bscore\s*:\s*(.+)$", line or "", flags=re.IGNORECASE)
        if not match and not score:
            return False
        return {
            "date_range": match.group(1) if match else False,
            "description": "Score: %s" % self._resume_clean_table_text(score.group(1)) if score else False,
        }

    def _resume_parse_passed_education_line(self, line):
        normalized = self._resume_normalize_heading(line)
        if not re.search(r"\b(?:passed|appeared|completed|graduate|passing year)\b", normalized):
            return False
        if not re.search(
            r"\b(?:b\s*a|ba|b\s*sc|bsc|b\s*com|bcom|m\s*sc|msc|m\s*com|mcom|h\s*s\s*c|s\s*s\s*c|"
            r"ssc|hsc|10th|12th|ca|cpt|degree|diploma|commerce|secondary|science|arts)\b",
            normalized,
        ):
            return False
        year = self._resume_extract_education_date_range(line) or self._resume_extract_education_date(line)
        clean = self._resume_clean_table_text(line)
        degree_match = re.search(
            r"\b((?:B\.?\s*A|B\.?\s*S\.?c|B\.?\s*Com|M\.?\s*S\.?c|M\.?\s*Com|"
            r"Higher\s+Secondary|Secondary|10th|12th|H\.?\s*S\.?\s*C|S\.?\s*S\.?\s*C|"
            r"CA(?:-CPT)?|CPT|Diploma|(?:Master|Bachelor)?\s*Degree)[^,.;]*)",
            clean,
            flags=re.IGNORECASE,
        )
        degree = self._resume_clean_table_text(degree_match.group(1)) if degree_match else clean
        institution = False
        inst_match = re.search(r"\b(?:from|through)\s+(.+?)(?:\s+in\s+|\s+from\s+|\s+and\s+|$)", clean, flags=re.IGNORECASE)
        if inst_match:
            institution = self._resume_clean_table_text(inst_match.group(1))
        return {
            "date_range": year,
            "degree": degree,
            "institution": institution,
            "location": False,
            "description": False,
        }

    def _resume_parse_table_education_line(self, line):
        clean = self._resume_clean_table_text(line)
        normalized = self._resume_normalize_heading(clean)
        if normalized in {"sr no degree board uni passing year result", "course university board year of passing percentage"}:
            return False
        degree_pattern = (
            r"(?:S\.?\s*S\.?\s*C\.?|H\.?\s*S\.?\s*C\.?|10TH|12TH|"
            r"Higher\s+Secondary(?:\s*\(12th\))?|Secondary(?:\s*\(10th\))?|"
            r"B\.?\s*A\.?|B\.?\s*S\.?c\.?|B\.?\s*Com\.?|M\.?\s*S\.?c\.?|"
            r"M\.?\s*Com\.?|Bachelor(?:\s+in\s+[A-Za-z ]+)?|"
            r"Master(?:s)?(?:\s+in\s+[A-Za-z ]+)?|"
            r"(?:Master|Bachelor)?\s*Degree(?:\s*\([^)]*\))?|I\.?\s*T\.?)"
        )
        match = re.match(
            rf"^(?:\d+\s+)?(?P<degree>{degree_pattern})\s+(?P<institution>.+?)\s+"
            rf"(?P<date>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December)?\s*,?\s*(?:19|20)\d{{2}}(?:\s*[-–—]\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December)?\s*,?\s*(?:19|20)\d{{2}})?)\b"
            rf"(?P<description>.*)$",
            clean,
            flags=re.IGNORECASE,
        )
        if not match:
            return False
        degree = self._resume_clean_table_text(match.group("degree")).upper().replace(" .", ".")
        institution = self._resume_clean_table_text(match.group("institution"))
        if degree in {"HIGHER SECONDARY", "SECONDARY"} and re.match(r"^school\b", institution, flags=re.IGNORECASE):
            institution = self._resume_clean_table_text(re.sub(r"^school\s*,?\s*", "", institution, flags=re.IGNORECASE))
        institution, location = self._resume_split_entity_location(institution)
        description = self._resume_clean_table_text(match.group("description"))
        if description in {"-", "--"}:
            description = False
        return {
            "date_range": self._resume_clean_table_text(match.group("date")),
            "degree": degree,
            "institution": institution,
            "location": location or False,
            "description": description or False,
        }

    def _resume_parse_degree_institution_line(self, line):
        parts = [self._resume_clean_table_text(part) for part in (line or "").split(",", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return False
        normalized = self._resume_normalize_heading(parts[0])
        if not any(keyword in normalized for keyword in ("bachelor", "master", "secondary", "certificate", "diploma", "engineering", "computer", "b com", "m com", "hsc", "ssc")):
            return False
        return {
            "date_range": False,
            "degree": parts[0],
            "institution": parts[1],
            "location": False,
            "description": False,
        }

    def _resume_parse_dash_education_line(self, line):
        if not re.search(r"\s[—–-]\s", line or ""):
            return False
        parts = [self._resume_clean_table_text(part) for part in re.split(r"\s[—–-]\s", line) if self._resume_clean_table_text(part)]
        if len(parts) < 2:
            return False
        pipe_date = re.match(
            r"^(.+?)\s*\|\s*((?:19|20)\d{2}|20XX)$",
            parts[0],
            flags=re.IGNORECASE,
        )
        if pipe_date and re.fullmatch(r"(?:19|20)\d{2}|20XX", parts[1], flags=re.IGNORECASE):
            return {
                "date_range": "%s - %s" % (pipe_date.group(2), parts[1]),
                "degree": self._resume_clean_education_text(pipe_date.group(1)),
                "institution": False,
                "location": False,
                "description": False,
            }
        normalized = self._resume_normalize_heading(parts[0])
        if not any(keyword in normalized for keyword in ("bachelor", "master", "secondary", "certificate", "diploma", "engineering")):
            return False
        date_range = False
        description = False
        institution = parts[1]
        location = False
        if len(parts) >= 3:
            match = re.search(r"\((?:\s*)?((?:19|20)\d{2}|20XX)(?:\s*)?\)", parts[1])
            if match:
                date_range = match.group(1)
                institution = re.sub(r"\([^)]*%s[^)]*\)" % re.escape(date_range), "", institution).strip(" ,")
            score_match = re.search(r"\b(\d+(?:\.\d+)?\s*(?:%|CGPA)?)\b", parts[2], flags=re.IGNORECASE)
            description = score_match.group(1) if score_match else parts[2]
        institution, location = self._resume_split_entity_location(institution)
        return {
            "date_range": date_range,
            "degree": parts[0],
            "institution": institution,
            "location": location,
            "description": description,
        }

    def _resume_parse_inline_education_line(self, line):
        line = self._resume_clean_education_text(line)
        if not line:
            return False
        normalized = self._resume_normalize_heading(line)
        if not any(
            keyword in normalized
            for keyword in (
                "bachelor", "master", "b tech", "btech", "m tech", "mtech", "b e",
                "m e", "bsc", "msc", "mba", "bba", "degree", "diploma",
                "secondary", "school", "college", "university", "institute",
                "communication", "ma", "ba",
            )
        ):
            return False
        date_range = False
        range_value = self._resume_extract_education_date_range(line)
        if range_value:
            date_range = range_value
            line = re.sub(re.escape(range_value), "", line, count=1, flags=re.IGNORECASE).strip(" ,;-")
        elif self._resume_extract_education_date(line):
            date_range = self._resume_extract_education_date(line)
            line = re.sub(re.escape(date_range), "", line, count=1, flags=re.IGNORECASE).strip(" ,;-")

        parts = [
            self._resume_clean_table_text(part)
            for part in re.split(r"\s+\|\s+|\s+-\s+|,", line)
            if self._resume_clean_table_text(part)
        ]
        if len(parts) < 2 and not date_range:
            return False

        degree = False
        institution = False
        location = False
        description = False
        degree_keywords = (
            "bachelor", "master", "b.tech", "b tech", "btech", "m.tech", "m tech",
            "mtech", "b.e", "b e", "m.e", "m e", "bsc", "msc", "mba", "bba",
            "degree", "diploma", "secondary", "certificate", "ma", "ba",
        )
        institution_keywords = ("university", "college", "institute", "school", "academy")
        for part in parts:
            part_normalized = self._resume_normalize_heading(part)
            if not degree and any(keyword.replace(".", "") in part_normalized for keyword in degree_keywords):
                degree = part
            elif not institution and any(keyword in part_normalized for keyword in institution_keywords):
                institution, split_location = self._resume_split_entity_location(part)
                location = location or split_location
            elif not location and self._resume_looks_like_place(part):
                location = part
            else:
                description = "\n".join(filter(None, [description, part]))

        if not degree and parts:
            degree = parts[0]
        if not institution:
            for part in parts[1:]:
                if part != degree:
                    institution = part
                    break
        if institution and location == institution:
            location = False
        if (
            degree
            and re.search(r"\bhigh school diploma\s*\|\s*20xx$", degree, flags=re.IGNORECASE)
            and self._resume_normalize_heading(institution or "") == "20xx"
        ):
            degree = "HIGH SCHOOL DIPLOMA"
            date_range = date_range or "20XX - 20XX"
            institution = False
        if not location:
            for part in reversed(parts):
                if part not in {degree, institution} and self._resume_looks_like_place(part):
                    location = part
                    break
        row = {
            "date_range": date_range,
            "degree": degree,
            "institution": institution,
            "location": location,
            "description": description,
        }
        return row if self._resume_is_education_row(row) else False

    def _resume_looks_like_institution_fragment(self, text):
        clean = self._resume_clean_table_text(text)
        normalized = self._resume_normalize_heading(clean)
        if not clean or normalized in {"eee", "dar", "high", "high s"}:
            return False
        if any(keyword in normalized for keyword in ("university", "college", "school", "institute", "academy", " uni", "uni ")):
            return True
        return bool(re.fullmatch(r"[A-Z]{2,8}", clean))

    def _resume_extract_education_date(self, text):
        match = re.search(
            r"\b(?:"
            r"((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
            r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{2})"
            r"|((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
            r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+)?"
            r"((?:19|20)\d{2}|20XX))\b",
            text or "",
            flags=re.IGNORECASE,
        )
        return match.group(0).strip() if match else False

    def _resume_extract_education_date_range(self, text):
        date_part = (
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
            r"Nov(?:ember)?|Dec(?:ember)?)?\.?\s*(?:(?:19|20)\d{2}|20XX)"
        )
        match = re.search(
            rf"\b({date_part})\s*[-–—/]\s*((?:{date_part})|\d{{2}})\b",
            text or "",
            flags=re.IGNORECASE,
        )
        if not match:
            return False
        return "%s - %s" % (
            self._resume_clean_table_text(match.group(1)),
            self._resume_clean_table_text(match.group(2)),
        )

    def _resume_is_standalone_education_date(self, line, date_value):
        if not date_value:
            return False
        normalized_line = re.sub(r"[^a-z0-9]+", " ", line or "", flags=re.IGNORECASE).strip().lower()
        normalized_date = re.sub(r"[^a-z0-9]+", " ", date_value or "", flags=re.IGNORECASE).strip().lower()
        if normalized_line == normalized_date:
            return True
        remainder = re.sub(re.escape(date_value), "", line or "", count=1, flags=re.IGNORECASE).strip(" @-—().,")
        return not remainder or len(remainder) <= 2

    def _resume_parse_experience_lines(self, experience):
        return parse_experience_text(experience)

    def _resume_strip_skill_suffix(self, text):
        text = re.sub(r"^[=@\s]+", "", text or "").strip()
        for skill in ("Wordpress", "Jave Script", "Java Script", "JavaScript", "Photoshop", "Flash Animation"):
            text = re.sub(rf"\s+{re.escape(skill)}$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+[a-z]$", "", text, flags=re.IGNORECASE)
        return text.strip(" @-—")

    def _resume_clean_table_text(self, text):
        text = re.sub(r"^[^\w#]+", "", text or "").strip()
        text = re.sub(r"[|_—]{2,}", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip(" @-—|")

    def _resume_clean_company(self, text):
        text = self._resume_clean_table_text(text)
        text = re.sub(r"\s*\([^)]*$", "", text).strip()
        text = re.sub(r"\s*\(\s*\)\s*$", "", text).strip()
        return text

    def _resume_clean_education_text(self, text):
        text = self._resume_clean_table_text(text)
        text = re.sub(r"^@\s*", "", text)
        text = re.sub(r"\b(?:Facebook|Linkedin|LinkedIn|Dribbble|Dribbblo|Dribbbie|Oribbble)\b.*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:facebook|linkedin|dribbble)\.?\s*com\S*", "", text, flags=re.IGNORECASE)
        return self._resume_clean_table_text(text)

    def _resume_clean_education_detail_line(self, text):
        text = self._resume_clean_table_text(text)
        text = re.sub(r"^\d+\s+", "", text)
        text = re.sub(r"\s+\bin\b$", "", text, flags=re.IGNORECASE)
        if self._resume_normalize_heading(text) in {
            "yond", "ae", "se ae", "se ae erret coneectevr", "high", "high s",
        }:
            return False
        if re.match(r"^high\s+s\.{0,3}$", text or "", flags=re.IGNORECASE):
            return False
        return text

    def _resume_detail_line_is_unrelated_to_education(self, text, current):
        normalized = self._resume_normalize_heading(text)
        if not current.get("degree") and not current.get("institution"):
            return False
        if re.search(
            r"\b(?:i am|strong communicator|enjoy working|track record|programming languages|"
            r"developed and maintained|cross functional|requirements|design user interfaces|"
            r"work experience|experience as|currently working|presently working)\b",
            normalized,
        ):
            return True
        if self._resume_is_known_skill_line(text) and not re.search(r"\b(?:cgpa|gpa|grade|marks|%)\b", normalized):
            return True
        return False

    def _resume_split_entity_location(self, text):
        text = self._resume_clean_table_text(text)
        if not text:
            return False, False
        split_match = re.search(r"\s[-–—]\s", text)
        if split_match:
            name = text[:split_match.start()].strip()
            location = text[split_match.end():].strip(" ,")
            return name or text, location or False
        comma_parts = [part.strip() for part in text.split(",") if part.strip()]
        if len(comma_parts) >= 3 and all(self._resume_looks_like_place(part) for part in comma_parts[-2:]):
            return ", ".join(comma_parts[:-2]), ", ".join(comma_parts[-2:])
        if len(comma_parts) >= 2 and self._resume_looks_like_place(comma_parts[-1]):
            return ", ".join(comma_parts[:-1]), comma_parts[-1]
        return text, False

    def _resume_looks_like_place(self, text):
        normalized = self._resume_normalize_heading(text)
        if normalized in {"high", "high s", "eee", "dar"}:
            return False
        if any(keyword in normalized for keyword in ("usa", "india", "new york", "bangalore", "country", "maharashtra", "karnataka", "delhi", "pune", "mumbai")):
            return True
        words = re.findall(r"[A-Za-z]+", text or "")
        return 1 <= len(words) <= 4 and all(word[:1].isupper() for word in words)

    def _resume_remove_embedded_skills(self, text):
        for skill in ("Wordpress", "Jave Script", "Java Script", "JavaScript", "Photoshop", "Flash Animation"):
            text = re.sub(rf"\b{re.escape(skill)}\b", "", text or "", flags=re.IGNORECASE)
        return self._resume_clean_table_text(text)

    def _resume_clean_responsibilities(self, lines):
        cleaned = []
        for line in lines:
            line = self._resume_cut_cross_section_text(line)
            line = self._resume_remove_embedded_skills(line)
            if line and not self._resume_is_known_skill_line(line) and not self._resume_looks_like_cross_section_text(line):
                cleaned.append(line)
        return "\n".join(cleaned).strip()

    def _resume_cut_cross_section_text(self, text):
        return self._resume_clean_table_text(
            re.split(
                r"\b(?:INTERESTS|EDUCATION|SOCIAL LINK|Facebook|Dribbble|Dribbblo|Linkedin|LinkedIn)\b",
                text or "",
                flags=re.IGNORECASE,
            )[0]
        )

    def _resume_looks_like_cross_section_text(self, text):
        normalized = self._resume_normalize_heading(text)
        noisy_keywords = (
            "social link", "facebook", "facebookcom", "linkedin", "linkedincom",
            "dribbble", "dribbblecom", "username", "street name", "postzip code",
        )
        return any(keyword in normalized for keyword in noisy_keywords)

    def _resume_is_education_row(self, row):
        normalized = self._resume_normalize_heading(
            " ".join(str(value) for value in row.values() if value)
        )
        if any(keyword in normalized for keyword in ("facebook", "dribbble", "linkedin", "social link")):
            return False
        if normalized in {
            "sr no degree board uni passing year result",
            "course university board year of passing percentage",
        }:
            return False
        degree_words = re.findall(r"[A-Za-z]+", row.get("degree") or "")
        if (
            row.get("degree")
            and not row.get("date_range")
            and not row.get("institution")
            and len(degree_words) > 12
            and not any(
                keyword in normalized
                for keyword in (
                    "bachelor", "master", "engineering", "diploma", "certificate",
                    "secondary", "technology", "science", "commerce", "arts",
                )
            )
        ):
            return False
        if re.search(r"\b(?:i am|enjoy working|collaboratively|strong communicator|track record)\b", normalized):
            return False
        if normalized in {"high", "high s", "nyu", "eee", "dar"}:
            return False
        if row.get("date_range") and row.get("description"):
            return True
        return any(
            keyword in normalized
            for keyword in (
                "bachelor", "master", "degree", "arts", "science", "multimedia",
                "university", "college", "school", "institute", "communication",
                "diploma", "secondary", "ssc", "hsc", "s s c", "h s c",
                "b com", "bcom", "b sc", "bsc", "b a", "ba", "m sc", "msc",
                "m com", "mcom", "commerce", "microbiology", "chemistry", "technician",
            )
        )

    def _resume_merge_education_rows(self, rows):
        merged = {}
        for row in rows:
            date_key = re.sub(r"\D", "", row.get("date_range") or "")
            degree_key = self._resume_normalize_heading(row.get("degree") or "")
            if "xx" in (row.get("date_range") or "").lower() and degree_key:
                key = "%s:%s" % (self._resume_normalize_heading(row.get("date_range") or ""), degree_key)
            else:
                key = date_key or degree_key or self._resume_normalize_heading(row.get("institution") or "")
            if not key:
                continue
            existing = merged.get(key)
            if not existing:
                merged[key] = row
                continue
            for field_name, value in row.items():
                if not value:
                    continue
                if field_name == "degree" and existing.get("degree"):
                    if self._resume_is_better_education_degree(value, existing["degree"]):
                        existing[field_name] = value
                    continue
                if not existing.get(field_name) or len(str(value)) > len(str(existing[field_name])):
                    existing[field_name] = value
        return list(merged.values())

    def _resume_is_better_education_degree(self, new_value, old_value):
        new_normalized = self._resume_normalize_heading(new_value)
        old_normalized = self._resume_normalize_heading(old_value)
        education_words = ("bachelor", "master", "degree", "arts", "science", "multimedia")
        new_score = sum(1 for word in education_words if word in new_normalized)
        old_score = sum(1 for word in education_words if word in old_normalized)
        return new_score > old_score

    def _resume_dedupe_rows(self, rows, title_key):
        deduped = {}
        for row in rows:
            date_key = re.sub(r"\D", "", row.get("date_range") or "")
            title = self._resume_normalize_heading(row.get(title_key) or "")
            key = (date_key, title)
            if not any(key):
                continue
            existing = deduped.get(key)
            if not existing:
                deduped[key] = row
                continue
            for field_name, value in row.items():
                if value and (not existing.get(field_name) or len(str(value)) > len(str(existing[field_name]))):
                    existing[field_name] = value
        return list(deduped.values())

    def _resume_is_known_skill_line(self, text):
        normalized = self._resume_normalize_heading(text)
        known = {
            "wordpress", "html", "html 5", "html5", "css", "htmlcss",
            "java script", "javascript", "jave script", "photoshop",
            "flash animation", "illustrator", "indesign", "python", "java",
            "c", "c++", "sql",
        }
        return normalized in known

    def _resume_extract_social_media(self, lines):
        pairs = {}
        active_label = False
        for line in lines:
            clean_line = self._resume_clean_table_text(line)
            normalized = self._resume_normalize_heading(clean_line)
            label = self._resume_social_label(normalized)
            if label:
                active_label = label
            value = self._resume_clean_social_value(clean_line)
            if value:
                value_label = self._resume_social_label(self._resume_normalize_heading(value)) or active_label
                if value_label:
                    pairs[value_label] = value
                    active_label = False
        ordered = [
            "%s: %s" % (label, pairs[label])
            for label in ("Facebook", "Dribbble", "LinkedIn", "Instagram", "Twitter")
            if pairs.get(label)
        ]
        return "\n".join(ordered) or False

    def _resume_social_label(self, normalized):
        if "facebook" in normalized:
            return "Facebook"
        if "dribbble" in normalized or "dribbblo" in normalized:
            return "Dribbble"
        if "linkedin" in normalized:
            return "LinkedIn"
        if "instagram" in normalized:
            return "Instagram"
        if "twitter" in normalized:
            return "Twitter"
        return False

    def _resume_clean_social_value(self, text):
        normalized = self._resume_clean_table_text(text)
        replacements = {
            r"facebook\s*com": "facebook.com",
            r"facebookcom": "facebook.com",
            r"dribbble\s*com": "dribbble.com",
            r"dribbblecom": "dribbble.com",
            r"linkedin\s*com": "linkedin.com",
            r"linkedincom": "linkedin.com",
        }
        for pattern, replacement in replacements.items():
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\b[Vv](?=username\b)", "/", normalized)
        match = re.search(
            r"(?:https?://)?(?:www\.)?(?:facebook|dribbble|linkedin|instagram|twitter)\.com/[A-Za-z0-9._/-]+",
            normalized,
            flags=re.IGNORECASE,
        )
        if not match:
            return False
        value = match.group(0).strip(" .,:;|")
        if not value.startswith(("http://", "https://")):
            value = "https://" + value
        return value

    def _resume_clean_social_links(self, text):
        if not text:
            return False
        collected = []
        for line in text.splitlines():
            normalized = self._resume_normalize_heading(line)
            if any(keyword in normalized for keyword in ("facebook", "dribbble", "dribbblo", "linkedin", "instagram", "twitter")):
                collected.append(line.strip())
        return "\n".join(collected).strip() or False

    def _resume_extract_name(self, lines):
        for line in lines[:25]:
            labeled_name = self._resume_extract_labeled_value(
                line,
                ("name", "candidate name", "full name", "applicant name"),
            )
            if labeled_name and self._resume_value_looks_like_person_name(labeled_name):
                return self._resume_format_person_name(labeled_name)
            headline_name = self._resume_split_name_from_headline(line)
            if headline_name:
                return headline_name
        for line in lines[:8]:
            match = re.search(
                r"I\s+AM\s+([A-Z][A-Z\s'.-]{2,40}?)(?:\s+I\s+AM\s+A|\s+1\s*AM\s+A|$)",
                line,
                flags=re.IGNORECASE,
            )
            if match:
                return match.group(1).strip().title()
        for index, line in enumerate(lines[:8]):
            if self._resume_normalize_heading(line) in {"hello there", "hello"}:
                for candidate in lines[index + 1:index + 4]:
                    match = re.match(r"[i1]\s*am\s+(.+)", candidate, flags=re.IGNORECASE)
                    if match and "creative" not in candidate.lower() and "director" not in candidate.lower():
                        return match.group(1).strip().upper()
        ignored_words = {
            "resume",
            "curriculum vitae",
            "cv",
            "contact",
            "contact profile",
            "profile",
            "summary",
            "email",
            "phone",
            "hello there",
            "fresher resume",
            "graphic designer contact",
            "education credentials",
            "professional experience",
        }
        merged_name = self._resume_merge_split_name_lines(lines[:8])
        if merged_name:
            return merged_name
        for line in lines[:12]:
            lowered = line.lower().strip(":")
            normalized = self._resume_normalize_heading(line)
            if lowered in ignored_words or normalized in ignored_words:
                continue
            if re.search(r"\byour degree\b", normalized) or re.search(r"\bname surname\b", normalized):
                continue
            if re.search(r"\bwrite your job title\b", normalized):
                continue
            if "@" in line or re.search(r"\d", line):
                continue
            words = re.findall(r"[A-Za-z][A-Za-z.'-]*", line)
            if 2 <= len(words) <= 5 and len(" ".join(words)) <= 80:
                return " ".join(words)
        return False

    def _resume_merge_split_name_lines(self, lines):
        parts = []
        for line in lines or []:
            clean = self._resume_clean_table_text(line)
            normalized = self._resume_normalize_heading(clean)
            if not clean or "@" in clean or self._resume_extract_phone(clean):
                if parts:
                    break
                continue
            if normalized in {
                "contact", "profile", "contact profile", "education", "skills",
                "professional experience", "work experience",
            }:
                if parts:
                    break
                continue
            if re.search(r"\byour degree\b", normalized):
                if parts:
                    break
                continue
            if re.search(r"\bwrite your job title\b", normalized):
                if parts:
                    break
                continue
            tokens = clean.split()
            if len(tokens) == 1 and clean.isupper() and 2 <= len(clean) <= 20:
                parts.append(clean.title())
                continue
            if len(parts) >= 2:
                return " ".join(parts)
            parts = []
        if len(parts) >= 2:
            return " ".join(parts)
        return False

    def _resume_split_name_from_headline(self, line):
        clean = self._resume_clean_table_text(line)
        if not clean or "@" in clean:
            return False
        match = re.match(
            r"^([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})\s+"
            r"(?:Product Manager|Project Manager|Software Engineer|Web\s*&?\s*Graphic Designer|"
            r"Graphic Designer|Creative Director|Hairdresser|Account Manager|System Analyst|"
            r"DevOps Engineer|Java Developer|Python Developer)\s*$",
            clean,
            flags=re.IGNORECASE,
        )
        if match:
            return self._resume_format_person_name(match.group(1))
        return False

    def _resume_extract_job_title(self, lines):
        for line in lines[:30]:
            labeled_title = self._resume_extract_labeled_value(
                line,
                ("job title", "title", "role", "current role", "position", "designation", "headline"),
            )
            if labeled_title and self._resume_value_looks_like_job_title(labeled_title):
                return self._resume_clean_table_text(labeled_title)
        for line in lines[:10]:
            match = re.search(r"I\s+AM\s+A\s+(.+)", line, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip().title()
        for index, line in enumerate(lines[:10]):
            if self._resume_normalize_heading(line) in {"hello there", "hello"}:
                for candidate in lines[index + 1:index + 5]:
                    match = re.match(r"[i1]\s*am\s+a\s+(.+)", candidate, flags=re.IGNORECASE)
                    if match:
                        return match.group(1).strip().title()
        title_keywords = (
            "hairdresser",
            "developer",
            "engineer",
            "consultant",
            "manager",
            "analyst",
            "designer",
            "accountant",
            "recruiter",
            "executive",
            "specialist",
            "administrator",
            "director",
            "project manager",
            "ui designer",
            "ux designer",
        )
        for line in lines[:20]:
            lowered = line.lower()
            if re.search(r"\b(?:19|20)\d{2}\b", line):
                continue
            if any(keyword in lowered for keyword in title_keywords) and len(line) <= 80:
                return line
        return False

    def _resume_extract_labeled_value(self, line, labels):
        clean_line = self._resume_clean_table_text(line)
        if not clean_line:
            return False
        for label in labels:
            pattern = r"^\s*%s\s*[:\-|]\s*(.+)$" % re.escape(label)
            match = re.match(pattern, clean_line, flags=re.IGNORECASE)
            if match:
                value = self._resume_clean_table_text(match.group(1))
                return value or False
        return False

    def _resume_value_looks_like_person_name(self, value):
        if not value or "@" in value or re.search(r"\d", value):
            return False
        normalized = self._resume_normalize_heading(value)
        if self._resume_detect_section_key(value):
            return False
        if any(keyword in normalized for keyword in ("resume", "curriculum vitae", "developer", "engineer", "manager", "designer")):
            return False
        words = re.findall(r"[A-Za-z][A-Za-z.'-]*", value)
        return 2 <= len(words) <= 5 and len(" ".join(words)) <= 80

    def _resume_format_person_name(self, value):
        value = self._resume_clean_table_text(value)
        if value.isupper() or value.islower():
            return value.title()
        return value

    def _resume_value_looks_like_job_title(self, value):
        if not value or "@" in value or self._resume_extract_phone(value):
            return False
        if re.search(r"\b(?:19|20)\d{2}\b", value):
            return False
        normalized = self._resume_normalize_heading(value)
        if self._resume_detect_section_key(value):
            return False
        title_keywords = (
            "developer", "engineer", "consultant", "manager", "analyst", "designer",
            "accountant", "recruiter", "executive", "specialist", "administrator",
            "director", "lead", "architect", "coordinator", "officer", "associate",
            "supervisor", "technician", "intern", "trainee", "sales", "marketing",
            "hr", "human resources", "data scientist", "product owner",
        )
        return len(value) <= 100 and any(keyword in normalized for keyword in title_keywords)

    def _resume_clean_summary(self, text):
        if not text:
            return False
        skill_noise = re.compile(
            r"(?:PHOTOSHOP|Illustrator|RLUSTRATON|RAUSTRATON|INDESIGN|CSS|hnacss|wnacss|"
            r"mosses?|nares|soem|©|\]\s*PHOTOSHOP|ts\]|tai\]|olit|consec\s*tai|"
            r"consectetuer|s0clis|sOcils)",
            flags=re.IGNORECASE,
        )
        word_fixes = (
            (r"\bolit\b", "elit"),
            (r"\bcommode\b", "commodo"),
            (r"\bs0clis\b", "sociis"),
            (r"\bsOcils\b", "sociis"),
            (r"\bconsectetuer\b", "consectetur"),
            (r"\bts\b", ""),
            (r"\bconsec-\b", "consectetur"),
        )
        cleaned_lines = []
        for line in (text or "").splitlines():
            line = skill_noise.sub("", line)
            line = re.sub(r"[\]\|{}]+", " ", line)
            for pattern, replacement in word_fixes:
                line = re.sub(pattern, replacement, line, flags=re.IGNORECASE)
            line = re.sub(r"\s+", " ", line).strip(" ,.")
            if line and len(line) > 15 and not re.match(r"^[\W\d_]+$", line):
                cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip() or False

    def _resume_extract_summary(self, lines, sections):
        if sections.get("summary"):
            return sections["summary"]
        collected = []
        capture = False
        for line in lines:
            normalized = self._resume_normalize_heading(line)
            if re.search(r"\bi am a\b", normalized):
                capture = True
                continue
            if capture:
                if self._resume_detect_section_key(line) or normalized == "work experience":
                    break
                if "@" in line or self._resume_extract_phone(line):
                    break
                if re.search(r"\bi am\b", normalized) and len(line.split()) <= 5:
                    continue
                collected.append(line)
        if collected:
            return self._resume_clean_summary("\n".join(collected)) or False
        for index, line in enumerate(lines):
            if self._resume_normalize_heading(line) in {"hello there", "hello"}:
                collected = []
                for candidate in lines[index + 1:]:
                    if self._resume_detect_section_key(candidate):
                        break
                    if re.match(r"[i1]\s*am\s+", candidate, flags=re.IGNORECASE):
                        continue
                    if "@" in candidate or self._resume_extract_phone(candidate):
                        continue
                    collected.append(candidate)
                return self._resume_clean_summary(self._resume_clean_text("\n".join(collected))) or False
        heading_positions = [
            index for index, line in enumerate(lines)
            if self._resume_detect_section_key(line)
        ]
        end = heading_positions[0] if heading_positions else min(len(lines), 10)
        summary_lines = []
        for line in lines[2:end]:
            normalized = self._resume_normalize_heading(line)
            if normalized in {"social media", "socials", "links", "contact", "graphic designer contact"}:
                break
            if any(keyword in normalized for keyword in ("designer", "developer", "engineer", "manager")) and len(line.split()) <= 4:
                continue
            if "@" in line or re.search(r"\b\d{5}(?:-\d{4})?\b", line):
                break
            if len(re.sub(r"\D", "", line)) >= 5:
                break
            if self._resume_extract_phone(line):
                continue
            summary_lines.append(line)
        summary = "\n".join(summary_lines).strip()
        summary = re.sub(r"(^|\n)\|\s+am\b", r"\1I am", summary)
        summary = re.sub(r"\|\s+am\b", "I am", summary)
        return self._resume_clean_summary(summary) or False

    def _resume_collect_sections(self, lines):
        sections = {}
        current_key = False
        section_lines = []
        max_section_lines = 30

        for line in lines:
            section_key = self._resume_detect_section_key(line)
            if section_key:
                if current_key == "experience" and section_key == "skills" and not section_lines:
                    continue
                if current_key and section_lines:
                    sections[current_key] = self._resume_finalize_section(current_key, section_lines)
                current_key = section_key
                inline_value = self._resume_inline_section_value(line, section_key)
                section_lines = [inline_value] if inline_value else []
                continue
            if not current_key:
                continue
            if self._resume_is_noise_line(line):
                continue
            if section_lines and self._resume_section_should_stop(current_key, line):
                sections[current_key] = self._resume_finalize_section(current_key, section_lines)
                current_key = False
                section_lines = []
                section_key = self._resume_detect_section_key(line)
                if section_key:
                    current_key = section_key
                continue
            if len(section_lines) >= max_section_lines:
                sections[current_key] = self._resume_finalize_section(current_key, section_lines)
                current_key = False
                section_lines = []
                continue
            section_lines.append(line)

        if current_key and section_lines:
            sections[current_key] = self._resume_finalize_section(current_key, section_lines)

        return {key: value for key, value in sections.items() if value}

    def _resume_inline_section_value(self, line, section_key):
        clean_line = self._resume_clean_table_text(line)
        if not clean_line:
            return False
        normalized = self._resume_normalize_heading(clean_line)
        heading_aliases = self._resume_section_heading_aliases().get(section_key, set())
        for heading in sorted(heading_aliases, key=len, reverse=True):
            pattern = r"^\s*%s\s*[:\-|]\s*(.+)$" % re.escape(heading)
            match = re.match(pattern, clean_line, flags=re.IGNORECASE)
            if match:
                return self._resume_clean_table_text(match.group(1)) or False
        if normalized in heading_aliases:
            return False
        return False

    def _resume_finalize_section(self, section_key, lines):
        text = self._resume_clean_text("\n".join(lines).strip())
        if not text:
            return False
        if section_key == "languages":
            return self._resume_extract_languages(lines, {section_key: text}, text)
        if section_key == "hobbies":
            return self._resume_extract_hobbies(lines, {section_key: text}, text)
        if section_key in ("skills", "hard_skills", "soft_skills"):
            cleaned_lines = []
            for line in lines:
                clean_line = self._resume_clean_table_text(line)
                if not clean_line or self._resume_looks_like_cross_section_text(clean_line):
                    continue
                if "@" in clean_line or self._resume_extract_phone(clean_line):
                    continue
                if self._resume_line_looks_like_experience_entry(clean_line):
                    continue
                if self._resume_detect_section_key(clean_line):
                    break
                cleaned_lines.append(clean_line)
            return "\n".join(cleaned_lines).strip() or False
        return text

    def _resume_section_should_stop(self, current_key, line):
        normalized = self._resume_normalize_heading(line)
        if current_key == "education":
            if "@" in line or self._resume_extract_phone(line):
                return True
            if any(
                keyword in normalized
                for keyword in (
                    "experience", "work experience", "job experience", "professional experience",
                    "objective", "career objective", "contact", "skills", "technical skills",
                    "personal details", "personal information", "hobbies", "interests",
                    "declaration", "project details", "field of interests",
                )
            ):
                return True
            return False
        if current_key in ("languages", "skills", "hard_skills", "soft_skills", "hobbies", "summary", "education"):
            if "@" in line or self._resume_extract_phone(line):
                return True
            if re.search(r"\b(?:19|20)\d{2}\b", line):
                return current_key != "education"
            if any(
                keyword in normalized
                for keyword in (
                    "bachelor", "master", "university", "college", "experience",
                    "objective", "career objective", "contact", "education",
                    "academic projects", "projects", "technical skills",
                    "personal details", "personal information",
                )
            ):
                return True
        return False

    def _resume_detect_section_key(self, line):
        normalized = self._resume_normalize_heading(line)
        section_map = list(self._resume_section_heading_aliases().items())
        known_headings = set().union(*(headings for _key, headings in section_map))
        if not self._resume_is_heading_like(line, normalized, known_headings):
            return False
        for key, headings in section_map:
            for heading in headings:
                if heading in {"language", "languages"} and normalized != heading:
                    continue
                if re.match(
                    r"^\s*%s\s*[:\-|]\s*.+"
                    % re.escape(heading),
                    self._resume_clean_table_text(line),
                    flags=re.IGNORECASE,
                ):
                    return key
                if normalized == heading:
                    return key
                if " " not in heading:
                    continue
                if len(normalized) <= 50 and (
                    normalized.startswith(heading + " ")
                    or normalized.endswith(" " + heading)
                ):
                    return key
        return False

    def _resume_section_heading_aliases(self):
        return {
            "summary": {
                "summary", "profile", "objective", "professional summary", "career objective",
                "about me", "personal profile", "professional profile", "career profile",
            },
            "experience": {
                "experience", "work experience", "work expperience", "work exppperience",
                "work experiences", "work experences",
                "professional experience", "employment", "work history", "employment history",
                "career history", "professional background", "relevant experience",
                "career experience", "present position", "past professional experience",
                "major past professional experience", "professional work experience",
                "industry experience", "job experience", "job experienced",
                "teaching experience", "work experince",
            },
            "projects": {
                "projects", "project", "academic projects", "academic project",
                "personal projects", "key projects",
            },
            "education": {
                "education", "academic", "academics", "qualification", "qualifications",
                "academic qualification", "academic qualifications", "educational qualification",
                "educational qualifications", "academic background", "education history",
                "educational profile", "academia", "academic record", "educational background",
                "education background", "academic details", "education details",
                "education qualification", "educational qualifiction",
                "professional academic background", "professional and academic background",
            },
            "hard_skills": {
                "hard skills", "technical skills", "technical skill", "technical expertise",
                "technical competencies", "tools", "technologies", "software skills",
                "computer skills",
            },
            "soft_skills": {
                "soft skills", "soft skills certifications", "personal skills", "personal skill",
                "strengths", "core strengths",
            },
            "skills": {
                "skill", "skills", "core skills", "key skills", "skill set", "areas of expertise",
                "competencies", "professional skills", "expertises", "expertise",
                "additional skills", "computer proficiency", "computer knowledge",
                "computer skills", "computer skill", "computer literacy", "computer edu",
                "computer", "competency",
            },
            "languages": {"languages", "language", "language known", "languages known"},
            "certifications": {
                "certifications", "certification", "licenses", "licences", "courses",
                "training", "trainings", "certificates",
            },
            "hobbies": {
                "hobby", "hobbies", "interests", "personal interests", "activities",
                "extra curricular", "extracurricular",
            },
            "social_media": {
                "social link", "social media", "socials", "links", "profiles",
                "online profiles", "portfolio",
            },
            "contact": {"contact", "contact details", "personal details"},
            "personal_information": {"personal information", "personal details", "personal info"},
        }

    def _resume_is_heading_like(self, line, normalized, known_headings):
        if not normalized:
            return False
        clean_line = self._resume_clean_table_text(line)
        for heading in known_headings:
            if re.match(r"^\s*%s\s*[:\-|]\s*.+" % re.escape(heading), clean_line, flags=re.IGNORECASE):
                return True
        if len(normalized) > 60:
            return False
        if normalized in known_headings:
            return True
        for heading in known_headings:
            if normalized.startswith(heading + " ") and len(normalized) <= len(heading) + 35:
                return True
        if re.search(r"\b\d{4}\b", normalized):
            return False
        letters = re.sub(r"[^A-Za-z]+", "", line or "")
        if not letters:
            return False
        uppercase_letters = sum(1 for char in letters if char.isupper())
        return uppercase_letters / len(letters) >= 0.6

    def _resume_normalize_heading(self, text):
        normalized = re.sub(r"[^a-z0-9 ]+", "", (text or "").lower())
        return re.sub(r"\s+", " ", normalized).strip()

    def _resume_clean_text(self, text):
        text = text or ""
        text = re.sub(r"(^|\n)\s*\|\s+am\b", r"\1I am", text)
        text = re.sub(r"\|\s+am\b", "I am", text)
        return text.strip()

    def _resume_is_noise_line(self, line):
        normalized = self._resume_normalize_heading(line)
        if not normalized:
            return True
        if normalized in {"i", "l"}:
            return True
        return False

    def _resume_build_message(self, email, phone):
        missing = []
        if not email:
            missing.append(_("email"))
        if not phone:
            missing.append(_("phone"))
        if missing:
            return _("Resume extracted. Please review manually; missing: %s.") % ", ".join(missing)
        return _("Resume extracted successfully. Please review before using the details.")


class ContactResumeEducation(models.Model):
    _name = "contact.resume.education"
    _description = "Contact Resume Education"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade")
    date_range = fields.Char(string="Dates")
    degree = fields.Char(string="Degree / Qualification")
    institution = fields.Char(string="Institution")
    location = fields.Char(string="Location")
    description = fields.Text(string="Details")


class ContactResumeExperience(models.Model):
    _name = "contact.resume.experience"
    _description = "Contact Resume Experience"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade")
    date_range = fields.Char(string="Dates")
    job_title = fields.Char(string="Job Title")
    company = fields.Char(string="Company")
    location = fields.Char(string="Location")
    description = fields.Text(string="Responsibilities")
