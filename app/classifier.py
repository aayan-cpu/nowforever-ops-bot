from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from typing import Iterable

from app import sites

# v2 rule classifier: lightweight, explainable, no external packages.
# Goal: catch ops issues reliably before adding AI/Google Chat live mode.

CATEGORY_KEYWORDS = {
    "daily_shift_report": [
        r"\bday report\b", r"\bdaily report\b", r"\bshift\s*\d+\b", r"\bclosing report\b", r"\bstore close", r"\btuesday report\b", r"\bmonday report\b", r"\bsaturday report\b"
    ],
    "fuel_price_competition": [
        r"\bgas price\b", r"\bfuel price\b", r"\bcompetitor", r"\bcompetition\b", r"\bgasbuddy\b", r"\bgas buddy\b", r"\bfuel prices?\b",
        r"\bregular\b.*\bplus\b.*\bsuper\b", r"\bdiesel\b", r"\bprice\b.*\bregular\b"
    ],
    "fuel_delivery_issue": [
        r"\bbol\b", r"\bveeder\b", r"\bverses report\b", r"\bdelivery\b.*\bgas\b", r"\bgas delivery\b", r"\bgallons?\b",
        r"\bneed gas\b", r"\burgent gas\b", r"\bshort\b.*\bgallon", r"\bless\b.*\bgallon", r"\bturned off\b.*\b(regular|super|gas|fuel)\b",
        r"\bregular\s+n\s+super\b", r"\bwe need gas\b"
    ],
    "deposit_cash_bank": [
        r"\bdeposit\b", r"\bbank\b", r"\bcash\b", r"\bcheck\b", r"\batm\b", r"\bmoney order\b", r"\breceipt\b"
    ],
    "equipment_maintenance": [
        r"\bnot working\b", r"\bstill not working\b", r"\bbroken\b", r"\brepair\b", r"\btechnician\b", r"\belectrician\b", r"\bac\b", r"\ba\.c\b",
        r"\bpower\b", r"\bscreen\b", r"\bprinter\b", r"\btickets?\b.*\bnot printing\b", r"\bpump\b", r"\bmachine\b", r"\bremote\b", r"\bswitch\s*board\b",
        r"\bsewage\b", r"\bsmells?\b", r"\brestroom\b", r"\bice storage\b", r"\blogo\b.*\bremote\b"
    ],
    "delivery_order": [r"\bdoordash\b", r"\border\b", r"\bshipment\b", r"\bdelivery received\b"],
    "sales_issue": [r"\bsales?\s+(are\s+)?low\b", r"\blow sales\b", r"\bnot having power\b"],
    "admin_request_task": [
        r"\bplease\b", r"\bpls\b", r"\bkindly\b", r"\basap\b", r"\blook into\b", r"\bget that checked\b",
        r"\bcan (we|you|u)\b", r"\bcould you\b", r"\bneed (to|someone|a |you)\b", r"\bhas to be\b",
        r"@\s*admin", r"@\s*Admin", r"@\s*MOIN", r"@\s*Annus"
    ],
}

# Messages reporting something is now OK. These should NOT be high priority or
# create action tasks — they're status updates, not problems. Guards against the
# classic "AC is working now" / "power back on" false-positive alerts.
RESOLVED_RE = re.compile(
    r"\b(fixed|resolved|sorted|repaired|"
    r"back (on|up|online|to normal|in service)|"
    r"working (now|again|fine|properly)|up and running|"
    r"all (good|set|clear)|no (issue|issues|problem|problems|longer)|taken care of|"
    r"is (working|running|fine|ok|okay)|are working|good to go)\b",
    re.I,
)
# Signals that keep a message urgent even if a "resolved" word also appears
# (e.g. "fixed the sign but pump still not working").
STILL_URGENT_RE = re.compile(r"\b(still not|still down|urgent|asap|emergency)\b", re.I)

HIGH_PRIORITY_PATTERNS = [
    r"\basap\b", r"\burgent\b", r"\bneed gas\b", r"\bwe need gas\b", r"\bturned off\b.*\b(regular|super|gas|fuel)",
    r"\bregular\s+n\s+super\b", r"\belectrician\b", r"\bstill not working\b", r"\bnot working\b", r"\bpower\b.*\b(stopped|out|burned|not)", r"\bnot having power\b",
    r"\bswitch\s*board\b.*\bburn", r"\bless\b.*\bgallon", r"\bshort\b.*\bgallon", r"\b2500\b", r"\bsewage\b",
    r"\ba\.c\b.*not working", r"\bac\b.*not working", r"\bgas delivery required\b"
]
MEDIUM_PRIORITY_PATTERNS = [r"\bplease\b", r"\bpls\b", r"\bsend\b", r"\bupdate\b", r"\bcheck\b", r"\bpost\b", r"\blook into\b", r"\brequired\b"]

TASK_VERBS = re.compile(r"\b(please|pls|send|update|check|post|look into|fix|call|need|required|turn on|turn off|verify|confirm|send someone|technician|electrician)\b", re.I)
MENTION_RE = re.compile(r"@\s*([A-Za-z0-9._ -]+)")
MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
GALLON_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*gallons?\b", re.I)
PRICE_RE = re.compile(r"(?<!\d)\d\.\d{2,3}(?!\d)")

# messages that should not create tasks even with attachments
NO_TASK_PATTERNS = [
    r"^noted\b", r"^thanks?\b", r"^ok\b", r"^yes\b", r"^done\b", r"^received\b", r"^updated\b", r"^gas delivery received\b"
]

@dataclass
class ClassifiedMessage:
    categories: list[str]
    priority: str
    is_task: bool
    extracted_amounts: list[str]
    extracted_gallons: list[str]
    extracted_prices: list[str]
    assigned_hint: str | None
    task_title: str
    fingerprint: str
    confidence: float
    # Canonical site this message is about, resolved from the room — or, for
    # company-wide rooms, from an explicit "store/site <n>" reference in the
    # text. None when no station can be attributed (DMs, broadcasts).
    site: str | None = None
    site_key: str = ""


# Explicit in-text site reference, e.g. "store 11", "site #4", "# 27". Bare
# numbers are deliberately NOT treated as sites — in this domain they're almost
# always quantities/prices ("2,666 gallons", "$11").
_SITE_IN_TEXT = re.compile(r"\b(?:site|store|location)\s*#?\s*(\d{1,3})\b", re.I)


def resolve_site(text: str, room_name: str = "") -> dict | None:
    """Best-effort canonical site for a message.

    The room it was posted in is the strongest signal, so a station room wins
    outright. For a company-wide room / DM (where `sites.resolve` returns None),
    fall back to an explicit "store/site <n>" reference in the message text.
    Returns the `sites.resolve` record (``{number, name, key}``) or None.
    """
    room_site = sites.resolve(room_name)
    if room_site:
        return room_site
    m = _SITE_IN_TEXT.search(text or "")
    if m:
        return sites.resolve(m.group(1))
    return None


def clean_text(text: str) -> str:
    body = (text or "").replace("\r", "\n")
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"[ \t]+", " ", body)
    return body.strip()


def normalize_sender(sender: str) -> str:
    s = (sender or "").strip()
    # Vault update/edit transcript lines sometimes surface as sender="Updated on".
    # Keep it visible but mark it as synthetic so it can be filtered/de-duped.
    if s.lower() in {"updated on", "edited on"}:
        return "[vault-update-record]"
    return s


def make_fingerprint(room_name: str, message: str) -> str:
    norm = re.sub(r"\s+", " ", (message or "").lower()).strip()
    norm = norm.replace("verses report", "veeder report")
    norm = re.sub(r"[^a-z0-9$.,@:/ -]", "", norm)
    seed = f"{(room_name or '').lower()}|{norm[:500]}"
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]


def extract_assignees(body: str) -> str | None:
    text = body or ""
    mentions: list[str] = []
    # Known company mention styles seen in the Vault export. This avoids greedy
    # captures like "@Admin 4 Ice storage...".
    known = re.findall(r"@\s*(admin\s*\d+|admin\d+|moin|annus\s+nadeem|ar\s+r)", text, flags=re.I)
    for k in known:
        pretty = re.sub(r"\s+", " ", k.strip())
        pretty = re.sub(r"admin\s*(\d+)", r"Admin \1", pretty, flags=re.I)
        if pretty.lower() == "moin": pretty = "MOIN"
        if pretty.lower() == "annus nadeem": pretty = "Annus Nadeem"
        if pretty.lower() == "ar r": pretty = "AR R"
        mentions.append("@" + pretty)
    # Also catch normal one-token @mentions/emails if present.
    for m in re.findall(r"@\s*([A-Za-z0-9._-]+@[A-Za-z0-9._-]+|[A-Za-z0-9._-]+)", text):
        cleaned = m.strip(" .,:;\n\t")
        if cleaned.lower() not in {"admin", "updated", "on"} and not re.fullmatch(r"admin\d+", cleaned, flags=re.I):
            mentions.append("@" + cleaned)
    seen = set(); out = []
    for x in mentions:
        key = x.lower()
        if key not in seen:
            seen.add(key); out.append(x)
    return ", ".join(out) if out else None


# Mention forms to strip out of a task title. ORDER MATTERS: known multi-word /
# numbered company aliases first (e.g. "@Admin 4"), then any single
# whitespace-free @token. The old single regex "@\s*[A-Za-z0-9._ -]+" included a
# SPACE in its class, so it ate past the mention into the next words until it hit
# a char not in the class (comma, apostrophe) — turning "@Admin 2,666 gallons"
# into ",666 gallons" and "@Admin didn't ..." into "'t ...". These patterns never
# cross a space except for the explicit known aliases. The (?![\d,]) guard stops
# "@Admin 2,666" being misread as admin #2 (it falls through to the generic rule,
# which strips only "@Admin" and keeps the "2,666" quantity).
_TITLE_MENTION_RES = (
    re.compile(r"@\s*(?:admin\s*\d+(?![\d,])|admin\d+|moin|annus\s+nadeem|ar\s+r)", re.I),
    re.compile(r"@\s*[A-Za-z0-9._-]+"),
)


def title_from_message(body: str) -> str:
    one = re.sub(r"\s+", " ", body or "").strip()
    for rgx in _TITLE_MENTION_RES:
        one = rgx.sub("", one)
    # collapse the gap a removed mention may leave, then drop any dangling leading
    # punctuation (e.g. "@john, fix pump" -> ", fix pump" -> "fix pump").
    one = re.sub(r"\s{2,}", " ", one)
    one = re.sub(r"^[\s,;:.\-]+", "", one).strip()
    if not one:
        return "Attachment/report needs review"
    return one[:120] + ("..." if len(one) > 120 else "")


def classify_message(text: str, attachment_count: int = 0, room_name: str = "") -> ClassifiedMessage:
    body = clean_text(text)
    low = body.lower()
    cats: list[str] = []

    # v2: attachment_report only means "has files"; it should not by itself imply a daily report.
    if attachment_count:
        cats.append("attachment_report")

    for cat, patterns in CATEGORY_KEYWORDS.items():
        if any(re.search(p, low, flags=re.I | re.S) for p in patterns):
            cats.append(cat)

    if not cats:
        cats.append("general")

    if any(re.search(p, low, flags=re.I | re.S) for p in HIGH_PRIORITY_PATTERNS):
        priority = "high"
    elif any(re.search(p, low, flags=re.I | re.S) for p in MEDIUM_PRIORITY_PATTERNS):
        priority = "medium"
    else:
        priority = "normal"

    # A "resolved" message (e.g. "AC is working now", "power back on") is a status
    # update, not a live problem — downgrade it unless it's still flagged urgent.
    resolved = bool(RESOLVED_RE.search(body)) and not STILL_URGENT_RE.search(body)
    if resolved:
        priority = "normal"
        if "status_update" not in cats:
            cats.append("status_update")

    no_task = any(re.search(p, low, flags=re.I) for p in NO_TASK_PATTERNS) or resolved
    operational_category = any(c in cats for c in ["admin_request_task", "equipment_maintenance", "fuel_delivery_issue", "sales_issue"])
    is_task = (bool(TASK_VERBS.search(body)) or priority == "high" or operational_category) and not no_task

    # Site context: which station is this message about? Knowing the site lets
    # downstream attribution credit the right store even for messages posted in
    # the company-wide room, and a confidently-resolved site is a small signal
    # the classification is grounded in a real operational location.
    site_rec = resolve_site(body, room_name)
    site = site_rec["name"] if site_rec else None
    site_key = site_rec["key"] if site_rec else ""

    confidence = 0.55
    if priority == "high": confidence += 0.20
    if operational_category: confidence += 0.15
    if extract_assignees(body): confidence += 0.05
    if attachment_count: confidence += 0.02
    if site_rec: confidence += 0.03
    confidence = min(confidence, 0.98)

    return ClassifiedMessage(
        categories=sorted(set(cats)),
        priority=priority,
        is_task=is_task,
        extracted_amounts=MONEY_RE.findall(body),
        extracted_gallons=GALLON_RE.findall(body),
        extracted_prices=PRICE_RE.findall(body),
        assigned_hint=extract_assignees(body),
        task_title=title_from_message(body),
        fingerprint=make_fingerprint(room_name, body),
        confidence=round(confidence, 2),
        site=site,
        site_key=site_key,
    )


def category_string(cats: Iterable[str]) -> str:
    return ";".join(cats)
