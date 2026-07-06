import logging

_logger = logging.getLogger(__name__)

CORRUPT_COMPANIES = {
    "wordpress",
    "jove script",
    "java script",
    "photoshop",
    "flash animation",
    "html5",
    "css",
}


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env["ir.config_parameter"].sudo().set_param("contact_resume_parser.extract_on_upload", "True")

    partners = env["res.partner"].search([("resume_file", "!=", False)])
    for partner in partners:
        corrupted = False
        for line in partner.resume_experience_line_ids:
            company = (line.company or "").strip().lower()
            if company in CORRUPT_COMPANIES:
                corrupted = True
                break
            if "+" in (line.date_range or ""):
                corrupted = True
                break
        if not corrupted:
            continue
        try:
            partner._extract_resume_to_partner()
            _logger.info("Re-extracted corrupted resume for partner %s (%s)", partner.id, partner.name)
        except Exception as error:
            _logger.warning(
                "Could not re-extract resume for partner %s (%s): %s",
                partner.id,
                partner.name,
                error,
            )
