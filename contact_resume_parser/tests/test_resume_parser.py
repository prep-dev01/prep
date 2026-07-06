import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_fake_odoo():
    if "odoo" in sys.modules:
        return

    odoo = types.ModuleType("odoo")
    odoo._ = lambda text, *args, **kwargs: text

    class _API:
        def onchange(self, *args, **kwargs):
            return lambda method: method

        def model_create_multi(self, method):
            return method

        def model(self, method):
            return method

    class _Fields:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    class _Model:
        pass

    exceptions = types.ModuleType("odoo.exceptions")
    exceptions.UserError = Exception

    tools = types.ModuleType("odoo.tools")
    translate = types.ModuleType("odoo.tools.translate")
    translate._ = odoo._

    odoo.api = _API()
    odoo.fields = _Fields()
    odoo.models = types.SimpleNamespace(Model=_Model, TransientModel=_Model)
    sys.modules["odoo"] = odoo
    sys.modules["odoo.exceptions"] = exceptions
    sys.modules["odoo.tools"] = tools
    sys.modules["odoo.tools.translate"] = translate


_install_fake_odoo()

from contact_resume_parser.models.res_partner import ResPartner


class ResumeParserTest(unittest.TestCase):
    def setUp(self):
        self.parser = ResPartner()

    def _parse(self, text):
        return self.parser._resume_parse_details(text)

    def test_label_based_contact_details_are_extracted(self):
        details = self._parse(
            """
            RESUME
            Candidate Name: PRIYA SHARMA
            Designation: Senior Python Developer
            Email: priya.sharma@gmail.com
            Phone: +91 98765 43210
            Address: Pune, Maharashtra, India

            Professional Summary
            Backend developer with 6 years of experience building APIs.

            Technical Expertise: Python, Django, SQL, Docker
            Languages Known: English, Hindi
            """
        )

        self.assertEqual(details["name"], "Priya Sharma")
        self.assertEqual(details["job_title"], "Senior Python Developer")
        self.assertEqual(details["email"], "priya.sharma@gmail.com")
        self.assertEqual(details["phone"], "+91 98765 43210")
        self.assertEqual(details["address"], "Pune, Maharashtra, India")
        self.assertIn("Python", details["hard_skills"])
        self.assertIn("English", details["languages"])

    def test_modern_section_aliases_and_inline_sections(self):
        details = self._parse(
            """
            AARAV MEHTA
            Product Manager
            aarav@example.com | +1 222 333 4444

            About Me: Product manager focused on SaaS onboarding and growth.
            Areas of Expertise: Product Strategy, SQL, Communication Skills

            Employment History
            Product Manager - BrightApps Inc
            Jan 2021 - Present
            Led onboarding improvements and managed roadmap planning.

            Academic Background
            MBA, Delhi University, Delhi, 2018 - 2020

            Personal Interests: Reading, Travel
            """
        )

        self.assertEqual(details["name"], "AARAV MEHTA")
        self.assertEqual(details["job_title"], "Product Manager")
        self.assertIn("Product manager focused", details["summary"])
        self.assertEqual(len(details["experience_lines"]), 1)
        self.assertEqual(details["experience_lines"][0]["company"], "BrightApps Inc")
        self.assertEqual(len(details["education_lines"]), 1)
        self.assertEqual(details["education_lines"][0]["degree"], "MBA")
        self.assertEqual(details["education_lines"][0]["institution"], "Delhi University")
        self.assertIn("Reading", details["hobbies"])

    def test_compact_education_rows_are_structured(self):
        rows = self.parser._resume_parse_education_lines(
            """
            B.Tech Computer Science, Gujarat Technological University, Ahmedabad, 2016-2020
            Higher Secondary School, DPS Surat, Surat, 2014-2016
            """
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["date_range"], "2016 - 2020")
        self.assertEqual(rows[0]["institution"], "Gujarat Technological University")
        self.assertEqual(rows[0]["location"], "Ahmedabad")
        self.assertEqual(rows[1]["institution"], "DPS Surat")

    def test_month_range_education_blocks_are_structured(self):
        rows = self.parser._resume_parse_education_lines(
            """
            Masters in Software Engineering
            Jan 2019 — Dec 2020
            XYX University, Bangalore
            Bachelor in Computer Science
            Jan 2015 — Dec 2018
            XYX University, Bangalore
            """
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["degree"], "Masters in Software Engineering")
        self.assertEqual(rows[0]["date_range"], "Jan 2019 - Dec 2020")
        self.assertEqual(rows[0]["institution"], "XYX University")
        self.assertEqual(rows[0]["location"], "Bangalore")
        self.assertEqual(rows[1]["degree"], "Bachelor in Computer Science")
        self.assertEqual(rows[1]["date_range"], "Jan 2015 - Dec 2018")

    def test_two_column_sales_resume_does_not_mix_sections(self):
        details = self._parse(
            """
            NAME SURNAME
            NAME SURNAME
            PROFILE
            Results-oriented account manager with over 5 years of experience in driving
            revenue growth and building lasting relationships. Proven track record of exceeding
            target sales strategies.
            CONTACT
            name.sn@mail.com
            +1 222 222 222
            New York
            SKILLS
            Sales & Negotiation
            Account Management
            Market Research
            PROFESSIONAL EXPERIENCE
            ACCOUNT MANAGER | XYZ Company
            Sept. 20XX - Jul. 20XX
            Successfully managed a portfolio of key account, resulting in a
            20% increase in revenue within the first year.
            SENIOR SALES REPRESENTATIVE | ABC CORPORATION
            Sept. 20XX - Jul. 20XX
            Consistently achieved and exceeded quarterly sales targets.
            Led negotiations for a major contract, generating a 25% increase
            in annual revenue.
            SALES ASSOCIATE | DEF SOLUTIONS
            Sept. 20XX - Jul. 20XX
            Initiated and nurtured relationships with potential clients.
            Provided product demonstrations and presentations to clients.
            EDUCATION
            MA COMMUNICATION | 20XX - 20XX
            NYU
            BA COMMUNICATION | 20XX - 20XX
            NYU
            HIGH SCHOOL DIPLOMA | 20XX - 20XX
            NYU
            INTERESTS
            Knitting
            Contemporary Dance
            """
        )

        self.assertEqual(details["email"], "name.sn@mail.com")
        self.assertEqual(details["phone"], "+1 222 222 222")
        self.assertEqual(details["address"], "New York")
        self.assertEqual(details["hard_skills"], "Sales & Negotiation\nAccount Management\nMarket Research")
        self.assertNotIn("Results-oriented", details["skills"] or "")
        self.assertNotIn("CONTACT", details["skills"] or "")
        self.assertEqual(len(details["experience_lines"]), 3)
        self.assertEqual(details["experience_lines"][0]["job_title"], "ACCOUNT MANAGER")
        self.assertEqual(details["experience_lines"][0]["company"], "XYZ Company")
        self.assertIn("Successfully managed", details["experience_lines"][0]["description"])
        self.assertNotIn("Results-oriented", details["experience_lines"][0]["description"])
        self.assertEqual(len(details["education_lines"]), 3)
        self.assertEqual(details["education_lines"][0]["degree"], "MA COMMUNICATION")
        self.assertEqual(details["education_lines"][0]["institution"], "NYU")
        self.assertEqual(details["education_lines"][1]["degree"], "BA COMMUNICATION")
        self.assertEqual(details["education_lines"][2]["degree"], "HIGH SCHOOL DIPLOMA")
        self.assertIn("Knitting", details["hobbies"])


if __name__ == "__main__":
    unittest.main()
