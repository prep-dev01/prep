from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrApplicant(models.Model):
    _inherit = "hr.applicant"

    resume_file = fields.Binary(string="Resume", attachment=True)
    resume_filename = fields.Char(string="Resume Filename")
    resume_overwrite_existing = fields.Boolean(
        string="Overwrite Existing Applicant Fields",
        default=True,
        help="If checked, extracted name, email, phone and LinkedIn replace existing values.",
    )
    resume_extraction_message = fields.Text(string="Extraction Message", readonly=True)
    resume_parsed_skills = fields.Text(string="Parsed Skills", readonly=True)
    resume_extraction_state = fields.Selection(
        related="partner_id.resume_extraction_state",
        string="Extraction Status",
        readonly=True,
    )

    @api.onchange("resume_file", "resume_filename")
    def _onchange_resume_file(self):
        for applicant in self:
            if not applicant.resume_file:
                applicant.resume_extraction_message = False
                applicant.resume_parsed_skills = False
                continue
            if applicant.env["res.partner"]._resume_extract_on_upload_enabled():
                details, message = applicant._resume_parse_uploaded_file()
                applicant._resume_apply_details_to_applicant(details, message)
            else:
                applicant.resume_extraction_message = _(
                    "Resume uploaded. Save the applicant, then click Extract Resume to parse."
                )
                applicant.resume_parsed_skills = False

    def action_extract_resume(self):
        for applicant in self:
            applicant._extract_resume_to_applicant()
        return True

    def _resume_parse_uploaded_file(self):
        self.ensure_one()
        parser = self.env["res.partner"].new({
            "resume_file": self.resume_file,
            "resume_filename": self.resume_filename,
            "resume_overwrite_existing": True,
        })
        try:
            details, raw_text = parser._resume_build_details_from_file()
            message = details.get("message") or _("Resume parsed. Save or click Extract Resume to store on the contact.")
            return details, message
        except UserError as error:
            raise error
        except Exception as error:
            raise UserError(_("Could not extract this resume: %s") % error) from error

    def _extract_resume_to_applicant(self):
        self.ensure_one()
        if not self.resume_file:
            raise UserError(_("Please upload a resume first."))

        try:
            details, message = self._resume_parse_uploaded_file()
        except UserError as error:
            self.resume_extraction_message = str(error)
            return
        except Exception as error:
            self.resume_extraction_message = _("Could not extract this resume: %s") % error
            return

        partner = self._resume_get_or_create_partner(details)
        partner.write({
            "is_candidate": True,
            "resume_file": self.resume_file,
            "resume_filename": self.resume_filename,
            "resume_overwrite_existing": self.resume_overwrite_existing,
        })

        self.partner_id = partner.id
        self._resume_apply_details_from_partner(partner)

    def _resume_apply_details_from_partner(self, partner):
        self.ensure_one()
        overwrite = self.resume_overwrite_existing
        if partner.resume_candidate_name and (overwrite or not self.partner_name):
            self.partner_name = partner.resume_candidate_name
        if partner.resume_email and (overwrite or not self.email_from):
            self.email_from = partner.resume_email
        if partner.resume_phone and (overwrite or not self.partner_phone):
            self.partner_phone = partner.resume_phone
        if partner.resume_linkedin and (overwrite or not self.linkedin_profile):
            self.linkedin_profile = partner.resume_linkedin
        if partner.resume_skills:
            self.resume_parsed_skills = partner.resume_skills
        if partner.resume_summary and (overwrite or not self.applicant_notes):
            summary = partner.resume_summary
            if isinstance(summary, str) and "<" not in summary:
                summary = "<p>%s</p>" % summary.replace("\n", "<br/>")
            self.applicant_notes = summary
        self.resume_extraction_message = partner.resume_extraction_message

    def _resume_get_or_create_partner(self, details):
        self.ensure_one()
        partner = self.partner_id
        email = details.get("email")
        if not partner and email:
            partner = self.env["res.partner"].search([("email", "=ilike", email)], limit=1)
        if not partner:
            partner = self.env["res.partner"].create({
                "name": details.get("name") or self.partner_name or _("Applicant"),
                "email": email,
                "phone": details.get("phone"),
                "company_type": "person",
            })
        return partner

    def _resume_apply_details_to_applicant(self, details, message):
        self.ensure_one()
        overwrite = self.resume_overwrite_existing
        if details.get("name") and (overwrite or not self.partner_name):
            self.partner_name = details["name"]
        if details.get("email") and (overwrite or not self.email_from):
            self.email_from = details["email"]
        if details.get("phone") and (overwrite or not self.partner_phone):
            self.partner_phone = details["phone"]
        if details.get("linkedin") and (overwrite or not self.linkedin_profile):
            self.linkedin_profile = details["linkedin"]
        if details.get("skills"):
            self.resume_parsed_skills = details["skills"]
        if details.get("summary") and (overwrite or not self.applicant_notes):
            summary = details["summary"]
            if isinstance(summary, str) and "<" not in summary:
                summary = "<p>%s</p>" % summary.replace("\n", "<br/>")
            self.applicant_notes = summary
        self.resume_extraction_message = message
