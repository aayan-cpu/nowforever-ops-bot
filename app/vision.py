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
            "enum": ["bol", "veeder_root", "day_report", "fuel_receipt",
                     "price_sign", "equipment", "other"],
        },
        "summary": {"type": "string", "description": "One-line description of the image."},
        "bol_gallons": {"type": ["number", "null"], "description": "Total gallons on a Bill of Lading, else null."},
        "veeder_gallons": {"type": ["number", "null"], "description": "Gallons from a Veeder-Root tank reading, else null."},
        # Day / closing report fields
        "report_date": {"type": ["string", "null"], "description": "Date on a daily/shift/closing report, else null."},
        "shift": {"type": ["string", "null"], "description": "Shift label (day/night/1/2) on a report, else null."},
        "total_sales": {"type": ["number", "null"], "description": "Total sales $ on a day report, else null."},
        "inside_sales": {"type": ["number", "null"], "description": "Daily INSIDE/store sales $ (merchandise, non-fuel), else null."},
        "fuel_gallons_sold": {"type": ["number", "null"], "description": "Total fuel GALLONS sold/dispensed on a day report, else null."},
        "fuel_sales": {"type": ["number", "null"], "description": "Fuel sales $ on a day report, else null."},
        "amounts": {"type": "array", "items": {"type": "string"}, "description": "Dollar amounts seen."},
        "gallons": {"type": "array", "items": {"type": "string"}, "description": "Any gallon figures seen."},
        "prices": {"type": "array", "items": {"type": "string"}, "description": "Per-gallon prices seen."},
        "site_hint": {"type": ["string", "null"], "description": "Site/store name or number if visible."},
        "model_flagged_issue": {"type": "boolean", "description": "Does the image show a problem worth a human review (missing/blank fields, math that doesn't add up, damage, error, outage, anomaly)?"},
    },
    "required": ["doc_type", "summary", "bol_gallons", "veeder_gallons",
                 "report_date", "shift", "total_sales", "inside_sales",
                 "fuel_gallons_sold", "fuel_sales",
                 "amounts", "gallons", "prices", "site_hint", "model_flagged_issue"],
    "additionalProperties": False,
}

_PROMPT = (
    "You are an operations assistant for a chain of gas stations. Examine this "
    "image from a station chat and extract the structured fields.\n"
    "- Bill of Lading (BOL): read the TOTAL gallons delivered into bol_gallons.\n"
    "- Veeder-Root tank monitor reading: read the gallons into veeder_gallons.\n"
    "- Daily / shift / closing report (doc_type='day_report'): read report_date, shift, "
    "total_sales, inside_sales (store/merchandise sales $), fuel_sales ($), and "
    "fuel_gallons_sold (total gallons dispensed). Capture key dollar amounts; set "
    "model_flagged_issue=true if required fields are blank/missing or totals don't add up.\n"
    "Always capture any dollar amounts, gallon figures, and per-gallon prices you see, "
    "and the store/site if visible. Be precise with numbers; if unsure, use null. "
    "Respond only with the structured data."
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
    if needs_review:
        reason = ("day report needs review (missing/incorrect fields)"
                  if data.get("doc_type") == "day_report" else "image flagged a problem")
    else:
        reason = ""
    if isinstance(bol, (int, float)) and isinstance(veeder, (int, float)):
        discrepancy = round(abs(bol - veeder), 2)
        if discrepancy > DISCREPANCY_THRESHOLD:
            needs_review = True
            reason = f"BOL {bol} vs Veeder {veeder} differ by {discrepancy} gal (> {DISCREPANCY_THRESHOLD})"
    data["discrepancy_gallons"] = discrepancy
    data["needs_review"] = needs_review
    data["review_reason"] = reason
    # Category used when this becomes a review task.
    data["review_category"] = {
        "bol": "bol_veeder_review", "veeder_root": "bol_veeder_review",
        "day_report": "day_report_review",
    }.get(data.get("doc_type"), "image_review")
    return data
