import glob
import io
import os
import re
import subprocess
import tempfile
import zipfile
from xml.etree import ElementTree as ET

from odoo.exceptions import UserError
from odoo.tools.translate import _

DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

SUPPORTED_RESUME_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".odt", ".rtf",
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif",
)

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif")
OFFICE_EXTENSIONS = (".doc", ".odt", ".rtf")


class ResumeDocumentExtractor:
    """Extract plain text from many resume file formats, with OCR fallback."""

    def __init__(self, env, ocr_callbacks=None):
        self.env = env
        self.ocr_callbacks = ocr_callbacks or {}

    def extract(self, file_content, filename):
        filename = (filename or "resume").lower()
        extension = self._detect_extension(file_content, filename)
        if extension == ".pdf":
            return self._extract_pdf(file_content)
        if extension == ".docx":
            return self._extract_docx(file_content)
        if extension in OFFICE_EXTENSIONS:
            return self._extract_via_libreoffice(file_content, filename)
        if extension in IMAGE_EXTENSIONS:
            return self._extract_image(file_content)
        supported = ", ".join(ext.upper().lstrip(".") for ext in SUPPORTED_RESUME_EXTENSIONS)
        raise UserError(
            _("Unsupported resume format. Upload one of: %s.") % supported
        )

    def _detect_extension(self, file_content, filename):
        extension = os.path.splitext(filename)[1].lower()
        if extension in SUPPORTED_RESUME_EXTENSIONS:
            return extension
        if file_content.startswith(b"%PDF"):
            return ".pdf"
        if file_content.startswith(b"\x89PNG"):
            return ".png"
        if file_content[:3] == b"\xff\xd8\xff":
            return ".jpg"
        if file_content.startswith(b"GIF8"):
            return ".gif"
        if file_content.startswith(b"RIFF") and b"WEBP" in file_content[:16]:
            return ".webp"
        if file_content.startswith(b"PK\x03\x04"):
            return ".docx"
        if file_content.startswith(b"{\\rtf"):
            return ".rtf"
        return extension

    def _extract_pdf(self, file_content):
        text = self._extract_pdf_text(file_content)
        if self._text_is_usable(text):
            return text
        ocr_text = self._extract_pdf_ocr(file_content)
        if self._text_is_usable(ocr_text):
            return ocr_text
        if text.strip():
            return text
        raise UserError(
            _("No readable text was found in this PDF. Try a clearer scan or another format.")
        )

    def _extract_pdf_text(self, file_content):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise UserError(_("Install the Python package 'pypdf' to read PDF resumes."))

        reader = PdfReader(io.BytesIO(file_content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()

    def _extract_pdf_ocr(self, file_content, max_pages=3):
        if not self._command_exists("pdftoppm"):
            return ""
        if not self.ocr_callbacks.get("image"):
            return ""

        texts = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = os.path.join(tmp_dir, "resume.pdf")
            with open(pdf_path, "wb") as pdf_file:
                pdf_file.write(file_content)
            prefix = os.path.join(tmp_dir, "page")
            result = subprocess.run(
                ["pdftoppm", "-png", "-r", "200", "-f", "1", "-l", str(max_pages), pdf_path, prefix],
                capture_output=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                return ""
            for image_path in sorted(glob.glob(prefix + "-*.png")):
                with open(image_path, "rb") as image_file:
                    page_text = self.ocr_callbacks["image"](image_file.read())
                if page_text.strip():
                    texts.append(page_text.strip())
        return "\n\n".join(texts).strip()

    def _extract_docx(self, file_content):
        try:
            text = self._extract_docx_xml(file_content)
            if self._text_is_usable(text):
                return text
        except (zipfile.BadZipFile, KeyError, ET.ParseError):
            pass
        return self._extract_via_libreoffice(file_content, "resume.docx")

    def _extract_docx_xml(self, file_content):
        with zipfile.ZipFile(io.BytesIO(file_content)) as archive:
            document_xml = archive.read("word/document.xml")
        root = ET.fromstring(document_xml)
        paragraphs = []
        for paragraph in root.findall(".//w:p", DOCX_NS):
            parts = [
                node.text
                for node in paragraph.findall(".//w:t", DOCX_NS)
                if node.text
            ]
            if parts:
                paragraphs.append("".join(parts))
        return "\n".join(paragraphs).strip()

    def _extract_via_libreoffice(self, file_content, filename):
        if not self._command_exists("libreoffice"):
            raise UserError(
                _("Install LibreOffice on the server to read %s resumes.")
                % os.path.splitext(filename)[1].upper().lstrip(".")
            )
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_name = os.path.basename(filename) or "resume"
            source_path = os.path.join(tmp_dir, source_name)
            with open(source_path, "wb") as source_file:
                source_file.write(file_content)
            result = subprocess.run(
                [
                    "libreoffice", "--headless", "--nologo", "--nofirststartwizard",
                    "--convert-to", "txt:Text", "--outdir", tmp_dir, source_path,
                ],
                capture_output=True,
                timeout=90,
                check=False,
            )
            if result.returncode != 0:
                stderr = (result.stderr or b"").decode(errors="ignore")[:300]
                raise UserError(_("Could not convert resume: %s") % (stderr or _("unknown error")))
            txt_files = glob.glob(os.path.join(tmp_dir, "*.txt"))
            if not txt_files:
                raise UserError(_("No text could be extracted from this document."))
            with open(txt_files[0], encoding="utf-8", errors="ignore") as txt_file:
                text = txt_file.read().strip()
            if not self._text_is_usable(text):
                raise UserError(_("The document was opened but no readable resume text was found."))
            return text

    def _extract_image(self, file_content):
        image_ocr = self.ocr_callbacks.get("image")
        if not image_ocr:
            raise UserError(_("Image OCR is not configured on this server."))
        text = image_ocr(file_content)
        if not text.strip():
            raise UserError(_("No readable text was found in this image resume."))
        return text

    def _text_is_usable(self, text):
        clean = re.sub(r"\s+", " ", text or "").strip()
        if len(clean) < 40:
            return False
        letters = sum(1 for char in clean if char.isalpha())
        return letters >= 25

    @staticmethod
    def _command_exists(command):
        from shutil import which
        return bool(which(command))

    @staticmethod
    def supported_formats_label():
        return ", ".join(ext.upper().lstrip(".") for ext in SUPPORTED_RESUME_EXTENSIONS)
