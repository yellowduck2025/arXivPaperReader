"""PDF text extraction with dual-engine fallback."""

from pathlib import Path

from .models import PaperMeta

# Lazy imports so missing optional engines don't crash the module
_fitz = None
_pdfplumber = None


def _get_fitz():
    global _fitz
    if _fitz is None:
        try:
            import fitz
            _fitz = fitz
        except ImportError:
            pass
    return _fitz


def _get_pdfplumber():
    global _pdfplumber
    if _pdfplumber is None:
        try:
            import pdfplumber
            _pdfplumber = pdfplumber
        except ImportError:
            pass
    return _pdfplumber


def extract_text_pymupdf(pdf_path: Path) -> str | None:
    """Extract text using PyMuPDF (fast, good for two-column layouts)."""
    fitz = _get_fitz()
    if fitz is None:
        return None
    try:
        doc = fitz.open(str(pdf_path))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text.strip() or None
    except Exception:
        return None


def extract_text_pdfplumber(pdf_path: Path) -> str | None:
    """Extract text using pdfplumber (fallback for complex layouts)."""
    plumber = _get_pdfplumber()
    if plumber is None:
        return None
    try:
        with plumber.open(str(pdf_path)) as pdf:
            parts: list[str] = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
        text = "\n".join(parts).strip()
        return text or None
    except Exception:
        return None


def parse_paper(
    meta: PaperMeta,
    pdf_dir: Path | None = None,
) -> tuple[str | None, str]:
    """Extract text from a paper's PDF.

    Tries PyMuPDF first, then pdfplumber, then falls back to the
    abstract.

    Args:
        meta: Paper metadata including ``arxiv_id`` and ``abstract``.
        pdf_dir: Directory containing downloaded PDFs.

    Returns:
        ``(full_text, source_text)`` where *full_text* is the extracted
        body text (or ``None``) and *source_text* is the best available
        text for analysis (full_text or abstract).
    """
    from .config import PDF_DIR as _default_pdf_dir

    pdf_dir = pdf_dir or _default_pdf_dir
    pdf_path = pdf_dir / f"{meta.arxiv_id}.pdf"

    if not pdf_path.exists():
        return None, meta.abstract

    full_text = extract_text_pymupdf(pdf_path)
    if full_text is None:
        full_text = extract_text_pdfplumber(pdf_path)

    source_text = full_text if full_text else meta.abstract
    return full_text, source_text
