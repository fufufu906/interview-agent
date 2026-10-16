"""Extract text from user-provided documents without persisting upload copies."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


class DocumentExtractionError(ValueError):
    """Report unsupported or unreadable user documents."""


def extract_document_text(filename: str, content: bytes) -> str:
    """Extract searchable text from the document types supported in v1."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(content)
    if suffix in {".txt", ".md", ".markdown", ".rst", ".json", ".csv", ".yaml", ".yml"}:
        return _decode_text(content)
    raise DocumentExtractionError(f"unsupported_file_type:{suffix or 'none'}")


def _extract_pdf(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                pages.append(f"[PDF page {page_number}]\n{page_text}")
    except Exception as exc:  # pypdf exposes several parser-specific exceptions
        raise DocumentExtractionError("invalid_pdf") from exc
    if not pages:
        raise DocumentExtractionError("pdf_has_no_extractable_text")
    return "\n\n".join(pages)


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = content.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
        if text:
            return text
    raise DocumentExtractionError("text_file_is_empty_or_has_unknown_encoding")
