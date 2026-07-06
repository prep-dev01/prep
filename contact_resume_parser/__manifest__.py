{
    "name": "Contact Resume Parser",
    "version": "19.0.1.14.0",
    "summary": "Extract candidate details from resumes on contacts and job applicants",
    "category": "Human Resources/Recruitment",
    "author": "PREP DESK LLP",
    "license": "LGPL-3",
    "depends": ["contacts", "base_setup", "hr_recruitment"],
    "data": [
        "data/ir_config_parameter.xml",
        "security/ir.model.access.csv",
        "views/res_partner_views.xml",
        "views/hr_applicant_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "contact_resume_parser/static/src/scss/resume_parser.scss",
        ],
    },
    "installable": True,
    "application": True,
}
