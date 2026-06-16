"""AI image understanding via the Claude Messages REST API (no SDK).

Why REST: the `anthropic` SDK pulls pydantic-core/gRPC which don't build on the
dev machine's Python 3.14 (docs/LIMITATIONS.md #1), and the whole project is
deliberately dependency-free. We call POST /v1/messages directly with urllib.

Use case: gas-station photos in Chat — BOL (Bill of Lading) receipts, Veeder-Root
tank readings, price signs, equipment. Claude extracts structured values; Python
recomputes the BOL-vs-Veeder gallon discrepancy (we don't trust the model's
arithmetic) and flags mismatches for review.

Enable by setting ANTHROPIC_API_KEY (locally, or as a Cloud Run env/secret).
If unset, enabled() is False and callers skip vision cleanly.
"""
from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.request
import urllib.error

API_KEY_ENV = "ANTHROPIC_API_KEY"
MODEL = os.getenv("OPS_VISION_MODEL", "claude-opus-4-8")
ENDPOINT = "https://api.anthropic.com/v1/messages"
# Flag a BOL vs Veeder-Root delivery discrepancy above this many gallons.
DISCREPANCY_THRESHOLD = int(os.getenv("OPS_BOL_THRESHOLD", "500"))

_ctx = ssl.create_default_context()

# Structured-output schema (output_config.format). Opus 4.8 supports structured
# outputs; numeric constraints aren't allowed so we keep it to types + enums.
_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {
            "type": "string",
            "enum": ["bol", "veeder_root", "fuel_receipt", "price_sign",
                     "equipment", "other"],
        },
        "summary": {"type": "string", "description": "One-line description of the image."},
        "bol_gallons": {"type": ["number", "null"], "description": "Total gallons on a Bill of Lading, else null."},
        "veeder_gallons": {"type": ["number", "null"], "description": "Gallons from a Veeder-Root tank reading, else null."},
        "amounts": {"type": "array", "items": {"type": "string"}, "description": "Dollar amounts seen."},
        "gallons": {"type": "array", "items": {"type": "string"}, "description": "Any gallon figures seen."},
        "prices": {"type": "array", "items": {"type": "string"}, "description": "Per-gallon prices seen."},
        "site_hint": {"type": ["string", "null"], "description": "Site/store name or number if visible."},
        "model_flagged_issue": {"type": "boolean", "description": "Does the image itself show a problem (damage, error, outage)?"},
    },
    "required": ["doc_type", "summary", "bol_gallons", "veeder_gallons",
                 "amounts", "gallons", "prices", "site_hint", "model_flagged_issue"],
    "additionalProperties": False,
}

_PROMPT = (
    "You are an operations assistant for a chain of gas stations. Examine this "
    "image from a station chat and extract the structured fields. If it's a Bill "
    "of Lading (BOL), read the TOTAL gallons delivered into bol_gallons. If it's a "
    "Veeder-Root tank monitor reading, read the gallons into veeder_gallons. "
    "Capture any dollar amounts, gallon figures, and per-gallon prices you see. "
    "Be precise with numbers; if unsure, use null. Respond only with the structured data."
)


def enabled() -> bool:
    # Requires BOTH the API key AND an explicit opt-in, so enabling the chatbot
    # (which shares ANTHROPIC_API_KEY) does not silently turn on paid image analysis.
    return bool(os.getenv(API_KEY_ENV)) and \
        os.getenv("OPS_VISION_ENABLED", "false").lower() in {"1", "true", "yes"}


def analyze_image(image_bytes: bytes, media_type: str = "image/jpeg", context: str = "") -> dict:
    """Send one image to Claude and return extracted fields + a recomputed
    BOL/Veeder discrepancy. Raises RuntimeError on API failure."""
    if not enabled():
        raise RuntimeError("ANTHROPIC_API_KEY not set; vision is disabled")

    b64 = base64.standard_b64encode(image_bytes).decode()
    body = {
        "model": MODEL,
        "max_tokens": 1024,
        "output_config": {"format": {"type": "json_schema", "schema": _SCHEMA}},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": _PROMPT + (f"\n\nChat context: {context}" if context else "")},
            ],
        }],
    }
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), headers={
        "x-api-key": os.environ[API_KEY_ENV],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        resp = json.loads(urllib.request.urlopen(req, context=_ctx, timeout=60).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Claude vision {e.code}: {e.read().decode()[:300]}") from None

    text = next((b["text"] for b in resp.get("content", []) if b.get("type") == "text"), "")
    data = json.loads(text)
    return _reconcile(data)


def _reconcile(data: dict) -> dict:
    """Recompute the BOL vs Veeder discrepancy in Python (don't trust model math)."""
    bol = data.get("bol_gallons")
    veeder = data.get("veeder_gallons")
    discrepancy = None
    needs_review = bool(data.get("model_flagged_issue"))
    reason = "image flagged a problem" if needs_review else ""
    if isinstance(bol, (int, float)) and isinstance(veeder, (int, float)):
        discrepancy = round(abs(bol - veeder), 2)
        if discrepancy > DISCREPANCY_THRESHOLD:
            needs_review = True
            reason = f"BOL {bol} vs Veeder {veeder} differ by {discrepancy} gal (> {DISCREPANCY_THRESHOLD})"
    data["discrepancy_gallons"] = discrepancy
    data["needs_review"] = needs_review
    data["review_reason"] = reason
    return data
