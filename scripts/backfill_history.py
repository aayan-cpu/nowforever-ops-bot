"""Backfill historical Google Chat messages into Firestore.

Reads message history from every room the bot is in (via domain-wide delegation,
impersonating an admin user who is a member of the rooms) and classifies + stores
each one, so the dashboard/tasks/alerts reflect existing history, not just new
messages.

Prereqs:
- /tmp/sa-key.json  (chat-bot-poster service account key)
- The SA's client id authorized for domain-wide delegation with scope
  https://www.googleapis.com/auth/chat.messages.readonly  (admin.google.com)

Usage:
  python scripts/backfill_history.py            # all rooms
  python scripts/backfill_history.py dry         # count only, no writes
"""
import base64, json, os, ssl, sys, time
import urllib.request, urllib.parse, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.classifier import classify_message, category_string, clean_text, normalize_sender
from app.ingest import pick_primary_category
from app import store

KEY_PATH = os.getenv("OPS_SA_KEY", "/tmp/sa-key.json")
SUBJECT = os.getenv("OPS_IMPERSONATE", "aayan@khawarsons.com")
SKIP_SPACES = {"spaces/AAQAZpHdsz8"}  # Jersey Review - bot removed
_ctx = ssl.create_default_context()


def _b64(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def token(scope: str, subject: str | None = None) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    sa = json.load(open(KEY_PATH))
    now = int(time.time())
    claims = {"iss": sa["client_email"], "scope": scope,
              "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600}
    if subject:
        claims["sub"] = subject  # domain-wide delegation: act as this user
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps(claims).encode())
    pk = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = pk.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": f"{header}.{payload}.{_b64(sig)}"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
    return json.loads(urllib.request.urlopen(req, context=_ctx).read())["access_token"]


def api(path: str, tok: str) -> dict:
    for attempt in range(4):
        req = urllib.request.Request(f"https://chat.googleapis.com/v1/{path}",
                                     headers={"Authorization": f"Bearer {tok}"})
        try:
            return json.loads(urllib.request.urlopen(req, context=_ctx, timeout=20).read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(1.5 * (attempt + 1)); continue
            return {"_error": e.code, "_body": e.read().decode()[:300]}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1)); continue
            return {"_error": "network", "_body": str(e)}


def list_rooms(app_tok: str) -> list[dict]:
    rooms, page = [], ""
    while True:
        res = api(f"spaces?pageSize=200{('&pageToken=' + page) if page else ''}", app_tok)
        if "_error" in res:
            print("space list error:", res); break
        rooms += [s for s in res.get("spaces", [])
                  if (s.get("spaceType") or s.get("type")) in ("SPACE", "GROUP_CHAT", "ROOM")
                  and s["name"] not in SKIP_SPACES]
        page = res.get("nextPageToken", "")
        if not page:
            break
    return rooms


def list_messages(space: str, user_tok: str):
    page = ""
    while True:
        res = api(f"{space}/messages?pageSize=100{('&pageToken=' + page) if page else ''}", user_tok)
        if "_error" in res:
            print(f"  ! {space} message read error: {res}"); return
        for m in res.get("messages", []):
            yield m
        page = res.get("nextPageToken", "")
        if not page:
            return


def store_message(m: dict, room_name: str, room_id: str, seen: set) -> bool:
    data_id = m.get("name") or ""
    if data_id in seen:
        return False
    text = clean_text(m.get("text") or m.get("argumentText") or "")
    attachments = m.get("attachment") or m.get("attachments") or []
    if not text and not attachments:
        return False
    sender = normalize_sender((m.get("sender") or {}).get("displayName")
                              or (m.get("sender") or {}).get("name") or "unknown")
    c = classify_message(text, len(attachments), room_name)
    if c.fingerprint in seen:
        return False
    seen.add(data_id); seen.add(c.fingerprint)
    created = m.get("createTime") or ""
    doc = store.create("messages", {
        "seq": store.next_seq("messages"),
        "room_id": room_id, "room_name": room_name, "data_id": data_id, "sender": sender,
        "timestamp_raw": created, "message": text,
        "attachments": " | ".join(str(a.get("contentName", "attachment")) for a in attachments if isinstance(a, dict)),
        "attachment_count": len(attachments), "categories": category_string(c.categories),
        "priority": c.priority, "is_task": bool(c.is_task),
        "extracted_amounts": json.dumps(c.extracted_amounts),
        "extracted_gallons": json.dumps(c.extracted_gallons),
        "extracted_prices": json.dumps(c.extracted_prices),
        "assigned_hint": c.assigned_hint, "fingerprint": c.fingerprint,
        "confidence": c.confidence, "is_duplicate": False, "created_at": created,
    })
    if c.is_task or c.priority == "high":
        tid = store.next_seq("tasks")
        store.create("tasks", {
            "id": tid, "message_id": doc["id"], "room_name": room_name, "sender": sender,
            "task_title": c.task_title, "task_text": text[:4000],
            "category": pick_primary_category(c.categories), "priority": c.priority,
            "assigned_hint": c.assigned_hint, "assignee": c.assigned_hint, "status": "open",
            "source_fingerprint": c.fingerprint, "confidence": c.confidence,
            "created_at": created, "updated_at": created,
        }, doc_id=str(tid))
    return True


def main():
    dry = len(sys.argv) > 1 and sys.argv[1] == "dry"
    app_tok = token("https://www.googleapis.com/auth/chat.bot")
    user_tok = token("https://www.googleapis.com/auth/chat.messages.readonly", subject=SUBJECT)
    rooms = list_rooms(app_tok)
    # Idempotency: preload data_ids + fingerprints already in Firestore so a
    # re-run resumes/skips instead of duplicating.
    seen: set = set()
    if not dry:
        existing = store.list_all("messages")
        for e in existing:
            if e.get("data_id"):
                seen.add(e["data_id"])
            if e.get("fingerprint"):
                seen.add(e["fingerprint"])
        print(f"(resuming — {len(existing)} message(s) already in Firestore will be skipped)")
    print(f"{len(rooms)} room(s) to backfill (impersonating {SUBJECT}){' [DRY RUN]' if dry else ''}\n")
    grand = 0
    for s in rooms:
        name, sid = s.get("displayName") or s["name"], s["name"]
        count = 0
        for m in list_messages(sid, user_tok):
            if dry:
                count += 1
            elif store_message(m, name, sid, seen):
                count += 1
        grand += count
        print(f"  {count:>5}  {name}")
    print(f"\nTotal messages {'found' if dry else 'stored'}: {grand}")


if __name__ == "__main__":
    main()
