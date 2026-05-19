import re
import os
import unicodedata
import warnings

# ===== PDF ONLY =====
try:
    import pdfplumber
    PDF_PROCESSING_AVAILABLE = True
except ImportError:
    PDF_PROCESSING_AVAILABLE = False
    warnings.warn("pdfplumber not installed")


# ===== CLEANING =====
def clean_cv_text(text: str) -> str:
    if not text:
        return ""
    
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[•●■▪◆◦\*]+", ", ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()

    return text


# ===== MAIN EXTRACTION (PDF ONLY) =====
def smart_extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()

    if ext == '.pdf' and PDF_PROCESSING_AVAILABLE:
        try:
            text = ""
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"

            return clean_cv_text(text)

        except Exception as e:
            print(f"Error extract PDF: {e}")
            return ""

    return ""