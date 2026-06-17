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
# Flag a tank whose water level (inches) reaches this — water in fuel is an
# urgent ops issue (contamination / phase separation).
WATER_ALERT_INCHES = float(os.getenv("OPS_TANK_WATER_INCHES", "2"))

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
        "cash_amount": {"type": ["number", "null"], "description": "CASH collected / to be deposited on a day report (the cash drawer / cash-to-bank figure, NOT total sales or card), else null. Used to reconcile against the bank deposit."},
        "amounts": {"type": "array", "items": {"type": "string"}, "description": "Dollar amounts seen."},
        "gallons": {"type": "array", "items": {"type": "string"}, "description": "Any gallon figures seen."},
        "prices": {"type": "array", "items": {"type": "string"}, "description": "Per-gallon prices seen."},
        # Per-product breakdown for BOL / fuel-delivery receipts (the OCR target).
        "products": {
            "type": "array",
            "description": "Per-grade fuel line items on a BOL / fuel-delivery receipt.",
            "items": {
                "type": "object",
                "properties": {
                    "product": {"type": ["string", "null"], "description": "Fuel grade as printed (Regular/Unleaded/Plus/Super/Premium/Diesel/DEF)."},
                    "gallons": {"type": ["number", "null"], "description": "Gallons for this grade, else null."},
                    "unit_price": {"type": ["number", "null"], "description": "Per-gallon price for this grade, else null."},
                },
                "required": ["product", "gallons", "unit_price"],
                "additionalProperties": False,
            },
        },
        # Per-tank breakdown for a Veeder-Root / tank-gauge reading (the OCR target).
        "tanks": {
            "type": "array",
            "description": "Per-tank rows on a Veeder-Root / ATG tank-gauge reading.",
            "items": {
                "type": "object",
                "properties": {
                    "tank": {"type": ["string", "null"], "description": "Tank label/number as printed (T1, Tank 2, ...)."},
                    "product": {"type": ["string", "null"], "description": "Fuel grade in the tank (Regular/Super/Diesel/...)."},
                    "volume_gallons": {"type": ["number", "null"], "description": "Current product VOLUME in gallons, else null."},
                    "ullage_gallons": {"type": ["number", "null"], "description": "Ullage (empty space) gallons, else null."},
                    "water_inches": {"type": ["number", "null"], "description": "Water level in inches, else null."},
                },
                "required": ["tank", "product", "volume_gallons", "ullage_gallons", "water_inches"],
                "additionalProperties": False,
            },
        },
        "site_hint": {"type": ["string", "null"], "description": "Site/store name or number if visible."},
        "model_flagged_issue": {"type": "boolean", "description": "Does the image show a problem worth a human review (missing/blank fields, math that doesn't add up, damage, error, outage, anomaly)?"},
    },
    "required": ["doc_type", "summary", "bol_gallons", "veeder_gallons",
                 "report_date", "shift", "total_sales", "inside_sales",
                 "fuel_gallons_sold", "fuel_sales", "cash_amount",
                 "amounts", "gallons", "prices", "products", "tanks", "site_hint", "model_flagged_issue"],
    "additionalProperties": False,
}

_PROMPT = (
    "You are an operations assistant for a chain of gas stations. Examine this "
    "image from a station chat and extract the structured fields.\n"
    "- Bill of Lading (BOL): read the TOTAL gallons delivered into bol_gallons.\n"
    "- Fuel-delivery receipt / BOL line items (doc_type='fuel_receipt' or 'bol'): "
    "for EACH fuel grade, add a `products` entry with the grade name, its gallons, "
    "and per-gallon price if shown (e.g. Regular 5,000 gal, Super 1,200 gal, Diesel 2,000 gal).\n"
    "- Veeder-Root / ATG tank-gauge reading (doc_type='veeder_root'): for EACH "
    "tank row add a `tanks` entry with its label, product, current VOLUME in "
    "gallons, ullage, and water level in inches. Put the total product volume "
    "across tanks into veeder_gallons.\n"
    "- Daily / shift / closing report (doc_type='day_report'): read report_date, shift, "
    "total_sales, inside_sales (store/merchandise sales $), fuel_sales ($), "
    "fuel_gallons_sold (total gallons dispensed), and cash_amount (the CASH "
    "collected / cash-to-deposit figure — the drawer/bank cash, not card or total). "
    "Capture key dollar amounts; set "
    "model_flagged_issue=true if required fields are blank/missing or totals don't add up.\n"
    "Always capture any dollar amounts, gallon figures, and per-gallon prices you see, "
    "and the store/site if visible. Be precise with numbers; if unsure, use null. "
    "Respond only with the structured data."
)


_SUPPORTED = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_MAX_RAW = 3_500_000  # keep under Claude's ~5MB base64 limit; big phone photos exceed it


def _downscale_pil(b: bytes) -> bytes:
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(b)).convert("RGB")
    if max(img.size) > 1568:
        r = 1568 / max(img.size)
        img = img.resize((int(img.size[0] * r), int(img.size[1] * r)))
    out = io.BytesIO(); q = 85
    img.save(out, "JPEG", quality=q)
    while out.tell() > _MAX_RAW and q > 40:
        q -= 10; out = io.BytesIO(); img.save(out, "JPEG", quality=q)
    return out.getvalue()


def _downscale_sips(b: bytes) -> bytes:
    """macOS fallback (Pillow won't build on Python 3.14) for the local scanner."""
    import subprocess, tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as f:
        f.write(b); src = f.name
    dst = src + ".out.jpg"
    try:
        subprocess.run(["sips", "-Z", "1568", "-s", "format", "jpeg", src, "--out", dst],
                       capture_output=True, timeout=25, check=True)
        with open(dst, "rb") as g:
            return g.read()
    finally:
        for p in (src, dst):
            try: os.remove(p)
            except OSError: pass


def _maybe_downscale(b: bytes, media_type: str):
    """Resize/convert oversized or unsupported images so Claude accepts them."""
    if len(b) <= _MAX_RAW and media_type in _SUPPORTED:
        return b, media_type
    for fn in (_downscale_pil, _downscale_sips):
        try:
            return fn(b), "image/jpeg"
        except Exception:
            continue
    print("[vision] could not downscale; sending as-is", flush=True)
    return b, media_type


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

    image_bytes, media_type = _maybe_downscale(image_bytes, media_type)
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


# ----------------------------------------------------------- receipt OCR
# Canonical fuel grades. Maps the many ways a grade is printed on BOLs/receipts
# (and octane numbers) to one label, so per-product gallons aggregate correctly.
PRODUCT_ALIASES = {
    "regular": "Regular", "unleaded": "Regular", "unl": "Regular", "reg": "Regular",
    "regular unleaded": "Regular", "87": "Regular", "e87": "Regular",
    "plus": "Plus", "midgrade": "Plus", "mid-grade": "Plus", "mid": "Plus", "89": "Plus",
    "super": "Super", "premium": "Super", "prem": "Super", "supreme": "Super",
    "ultra": "Super", "91": "Super", "92": "Super", "93": "Super",
    "diesel": "Diesel", "dsl": "Diesel", "ulsd": "Diesel", "off-road diesel": "Diesel",
    "def": "DEF", "ethanol": "Ethanol", "e85": "Ethanol", "kerosene": "Kerosene",
}


def _to_number(v):
    """Coerce '5,000', '5000.0', 5000 -> float; junk/None -> None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower()
    s = s.replace(",", "").replace("$", "").replace("gal", "").replace("gallons", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def normalize_product(name) -> str | None:
    """Map a printed grade name to a canonical label, else a Title-cased
    fallback, else None for empty input."""
    if not name:
        return None
    key = " ".join(str(name).lower().split())
    if key in PRODUCT_ALIASES:
        return PRODUCT_ALIASES[key]
    # token scan: 'no-lead regular 87' -> Regular
    for tok in key.replace("-", " ").split():
        if tok in PRODUCT_ALIASES:
            return PRODUCT_ALIASES[tok]
    return " ".join(w.capitalize() for w in key.split()) or None


def parse_products(raw_products) -> list[dict]:
    """Normalize the model's `products` line items: canonical grade name, numeric
    gallons/unit_price. Drops entries with neither a product nor gallons."""
    out: list[dict] = []
    for item in raw_products or []:
        if not isinstance(item, dict):
            continue
        product = normalize_product(item.get("product"))
        gallons = _to_number(item.get("gallons"))
        unit_price = _to_number(item.get("unit_price"))
        if product is None and gallons is None:
            continue
        out.append({"product": product, "gallons": gallons, "unit_price": unit_price})
    return out


def receipt_totals(products: list[dict]) -> dict:
    """Aggregate parsed products into total gallons and a per-grade breakdown."""
    by_product: dict[str, float] = {}
    total = 0.0
    any_gallons = False
    for p in products:
        g = p.get("gallons")
        if g is None:
            continue
        any_gallons = True
        total += g
        if p.get("product"):
            by_product[p["product"]] = round(by_product.get(p["product"], 0.0) + g, 2)
    return {"total_gallons": round(total, 2) if any_gallons else None,
            "by_product": by_product}


def extract_receipt(data: dict) -> dict:
    """Attach normalized products + totals to a vision result. For BOL/receipt
    docs, backfill bol_gallons from the summed line items when the model didn't
    give a single total."""
    products = parse_products(data.get("products"))
    data["products"] = products
    totals = receipt_totals(products)
    data["receipt_total_gallons"] = totals["total_gallons"]
    data["products_by_grade"] = totals["by_product"]
    if (data.get("doc_type") in {"bol", "fuel_receipt"}
            and not isinstance(data.get("bol_gallons"), (int, float))
            and totals["total_gallons"] is not None):
        data["bol_gallons"] = totals["total_gallons"]
    return data


def parse_tanks(raw_tanks) -> list[dict]:
    """Normalize the model's `tanks` rows: canonical product, numeric volume /
    ullage / water. Drops rows with neither a tank label nor a volume."""
    out: list[dict] = []
    for item in raw_tanks or []:
        if not isinstance(item, dict):
            continue
        tank = (str(item.get("tank")).strip() if item.get("tank") else None)
        product = normalize_product(item.get("product"))
        volume = _to_number(item.get("volume_gallons"))
        if not tank and volume is None:
            continue
        out.append({
            "tank": tank,
            "product": product,
            "volume_gallons": volume,
            "ullage_gallons": _to_number(item.get("ullage_gallons")),
            "water_inches": _to_number(item.get("water_inches")),
        })
    return out


def veeder_totals(tanks: list[dict], water_alert_inches: float | None = None) -> dict:
    """Aggregate parsed tanks: total product volume, per-grade volume, and the
    deepest water reading + whether it crosses the alert threshold."""
    thr = WATER_ALERT_INCHES if water_alert_inches is None else water_alert_inches
    by_product: dict[str, float] = {}
    total = 0.0
    any_volume = False
    max_water = None
    for t in tanks:
        v = t.get("volume_gallons")
        if v is not None:
            any_volume = True
            total += v
            if t.get("product"):
                by_product[t["product"]] = round(by_product.get(t["product"], 0.0) + v, 2)
        w = t.get("water_inches")
        if w is not None and (max_water is None or w > max_water):
            max_water = w
    return {"total_gallons": round(total, 2) if any_volume else None,
            "by_product": by_product,
            "max_water_inches": max_water,
            "high_water": max_water is not None and max_water >= thr}


def extract_veeder(data: dict) -> dict:
    """Attach normalized tanks + totals to a vision result. For a veeder_root
    doc, backfill veeder_gallons from the summed tank volumes when the model
    didn't give a single total, and flag high water for review."""
    tanks = parse_tanks(data.get("tanks"))
    data["tanks"] = tanks
    totals = veeder_totals(tanks)
    data["veeder_total_gallons"] = totals["total_gallons"]
    data["tanks_by_grade"] = totals["by_product"]
    data["max_water_inches"] = totals["max_water_inches"]
    data["high_water"] = totals["high_water"]
    if (data.get("doc_type") == "veeder_root"
            and not isinstance(data.get("veeder_gallons"), (int, float))
            and totals["total_gallons"] is not None):
        data["veeder_gallons"] = totals["total_gallons"]
    if totals["high_water"]:
        data["model_flagged_issue"] = True
    return data


def _reconcile(data: dict) -> dict:
    """Recompute the BOL vs Veeder discrepancy in Python (don't trust model math)."""
    extract_receipt(data)
    extract_veeder(data)
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
    # High water in a tank is its own urgent flag (unless a discrepancy already
    # gave a more specific reason).
    if data.get("high_water") and (not reason or reason == "image flagged a problem"):
        needs_review = True
        reason = f"water in tank: {data.get('max_water_inches')} in (>= {WATER_ALERT_INCHES} in)"
    data["discrepancy_gallons"] = discrepancy
    data["needs_review"] = needs_review
    data["review_reason"] = reason
    # Category used when this becomes a review task.
    data["review_category"] = {
        "bol": "bol_veeder_review", "veeder_root": "bol_veeder_review",
        "day_report": "day_report_review",
    }.get(data.get("doc_type"), "image_review")
    return data
