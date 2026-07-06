from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    resume_parser_ai_provider = fields.Selection(
        [
            ("auto", "Auto (HuggingFace → Ollama → OpenAI)"),
            ("huggingface", "HuggingFace NER (Custom trained)"),
            ("ollama", "Ollama (Free, Local LLM)"),
            ("openai", "OpenAI (Paid API)"),
            ("none", "Regex Only (No AI)"),
        ],
        string="Resume Parser AI",
        default="auto",
        config_parameter="contact_resume_parser.ai_provider",
    )
    resume_parser_ollama_url = fields.Char(
        string="Ollama URL",
        default="http://127.0.0.1:11434",
        config_parameter="contact_resume_parser.ollama_url",
    )
    resume_parser_ollama_model = fields.Char(
        string="Ollama Model",
        config_parameter="contact_resume_parser.ollama_model",
        help="Leave empty to auto-detect the first installed Ollama model.",
    )
    resume_parser_huggingface_model = fields.Char(
        string="HuggingFace Model",
        config_parameter="contact_resume_parser.huggingface_model",
        help="Your trained NER model on HuggingFace Hub, e.g. yourname/resume-ner-odoo",
    )
    resume_parser_openai_api_key = fields.Char(
        string="OpenAI API Key",
        config_parameter="contact_resume_parser.openai_api_key",
    )
    resume_parser_openai_model = fields.Char(
        string="OpenAI Model",
        config_parameter="contact_resume_parser.openai_model",
    )
    resume_parser_extract_on_upload = fields.Boolean(
        string="Extract on Upload",
        default=False,
        config_parameter="contact_resume_parser.extract_on_upload",
        help="When disabled, the file uploads instantly and parsing runs only when you click Extract Resume.",
    )
