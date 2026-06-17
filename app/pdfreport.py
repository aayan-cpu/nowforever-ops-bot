"""Read day reports submitted as PDFs in Google Chat.

A PDF carries real embedded text, so it parses far more reliably than a phone
photo of a paper report (image OCR). Flow: extract the PDF's text, then let Claude
pull the structured day-report fields from that text (reusing the vision schema) —
text -> structured is dramatically more accurate than image -> structured.

Pure-Python (pypdf); no system deps.
"""
from __future__ import annotations

import io


def extract_text(pdf_bytes: bytes, max_chars: int = 20000) -> str:
    """Best-effort text extraction from a PDF. Returns '' if it can't be read
    (e.g. a scanned/image-only PDF with no text layer)."""
    if not pdf_bytes:
        return ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(parts).strip()
        return text[:max_chars]
    except Exception as e:
        print(f"[pdf] extract failed: {e}", flush=True)
        return ""


def has_text(pdf_bytes: bytes) -> bool:
    return len(extract_text(pdf_bytes)) >= 20
