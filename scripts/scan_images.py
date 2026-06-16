"""Scan existing chat photos with AI vision: flag problems (bad/missing reports,
anomalies, BOL/Veeder issues), create review tasks, and extract the data.

Resumable + fault-tolerant: tracks scanned images in Firestore (`scanned_images`)
so re-runs skip what's done and just fill the rest. DMs the owner a summary of
issues found at the end.

  ANTHROPIC_API_KEY=... OPS_SA_KEY=/tmp/sa-key.json python scripts/scan_images.py [--since YYYY-MM-DD] [--limit N]
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

# Only worth vision-scanning an image if a nearby message marks it operational
# (reports, deliveries, equipment, money) — skip random receipts/selfies.
REPORT_RE = re.compile(
    r"\b(reports?|eod|end[- ]?of[- ]?day|closing|day\s*sheet|bol|veeder|gas|gallons?|"
    r"diesel|fuel|delivery|deliver|pump|tank|broke|broken|not working|down|power|"
    r"outage|ice|machine|printer|register|deposit|sales|invoice|sscs|price|meter|"
    r"reading|shift)\b", re.I)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.backfill_history as bf
from app import chat_media, vision, store, directory

SUBJECT = os.getenv("OPS_IMPERSONATE", "aayan@khawarsons.com")
READONLY = "https://www.googleapis.com/auth/chat.messages.readonly"


def _sid(resource_name: str) -> str:
    return "img_" + hashlib.sha1(resource_name.encode()).hexdigest()[:24]


def main():
    args = sys.argv[1:]
    since = None
    limit = None
    scan_all = "--all" in args  # scan every image, not just report-labeled ones
    if "--since" in args:
        since = args[args.index("--since") + 1]
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    if not vision.enabled():
        print("Vision disabled — set ANTHROPIC_API_KEY and OPS_VISION_ENABLED=true."); sys.exit(1)

    app_tok = bf.token("https://www.googleapis.com/auth/chat.bot")
    rooms = bf.list_rooms(app_tok)
    print(f"Scanning photos across {len(rooms)} rooms"
          + (f" since {since}" if since else "") + (f", limit {limit}" if limit else "") + "\n")

    scanned = found = errors = 0
    findings = []
    for s in rooms:
        name, sid = s.get("displayName") or s["name"], s["name"]
        user_tok = bf.token(READONLY, subject=SUBJECT)
        room_imgs = 0
        msgs = list(bf.list_messages(sid, user_tok, since=since))
        texts = [(m.get("text") or m.get("argumentText") or "") for m in msgs]
        for i, m in enumerate(msgs):
            ts = (m.get("createTime") or "")[:10]
            if since and ts and ts < since:
                continue
            imgs = chat_media.image_attachments(m)
            if not imgs:
                continue
            # Cost saver: only scan images a nearby message (prev/self/next) calls a report.
            if not scan_all and not REPORT_RE.search(" ".join(texts[max(0, i - 1):i + 2])):
                continue
            for img in imgs:
                if limit and scanned >= limit:
                    break
                rn = img["resource_name"]
                doc_id = _sid(rn)
                if store.get("scanned_images", doc_id):
                    continue
                try:
                    data = chat_media.download_attachment(rn)
                    if not data:
                        continue
                    res = vision.analyze_image(data, img.get("content_type", "image/jpeg"),
                                               context=f"Room: {name}")
                    scanned += 1
                    room_imgs += 1
                    store.create("scanned_images", {
                        "room_name": name, "data_id": m.get("name", ""),
                        "doc_type": res.get("doc_type"), "summary": res.get("summary"),
                        "needs_review": bool(res.get("needs_review")),
                        "scanned_at": datetime.now(timezone.utc).isoformat(),
                    }, doc_id=doc_id)
                    if res.get("doc_type") == "day_report":
                        store.create("day_reports", {
                            "room_name": name, "report_date": res.get("report_date"),
                            "shift": res.get("shift"), "total_sales": res.get("total_sales"),
                            "inside_sales": res.get("inside_sales"),
                            "fuel_sales": res.get("fuel_sales"),
                            "fuel_gallons_sold": res.get("fuel_gallons_sold"),
                            "summary": res.get("summary"), "data_id": m.get("name", ""),
                        }, doc_id=doc_id)
                    if res.get("bol_gallons") is not None or res.get("veeder_gallons") is not None:
                        store.create("fuel_events", {
                            "room_name": name, "report_date": res.get("report_date"),
                            "doc_type": res.get("doc_type"), "bol_gallons": res.get("bol_gallons"),
                            "veeder_gallons": res.get("veeder_gallons"),
                            "discrepancy_gallons": res.get("discrepancy_gallons"),
                            "summary": res.get("summary"), "data_id": m.get("name", ""),
                        }, doc_id=doc_id + "_fuel")
                    if res.get("needs_review"):
                        found += 1
                        tid = store.next_seq("tasks")
                        now = datetime.now(timezone.utc).isoformat()
                        store.create("tasks", {
                            "id": tid, "room_name": name, "sender": "image-scan",
                            "task_title": f"REVIEW (photo): {res.get('review_reason')}",
                            "task_text": res.get("summary", ""),
                            "category": res.get("review_category", "image_review"),
                            "priority": "high", "status": "open",
                            "confidence": res.get("confidence", 0.9),
                            "created_at": now, "updated_at": now,
                        }, doc_id=str(tid))
                        findings.append(f"• [{name}] {res.get('review_reason')} — {res.get('summary','')[:120]}")
                except Exception as e:
                    errors += 1
                    if errors <= 5:
                        print(f"  ! {name}: {str(e)[:90]}")
            if limit and scanned >= limit:
                break
        if room_imgs:
            print(f"  {room_imgs:>4} scanned  {name}")
        if limit and scanned >= limit:
            break

    print(f"\nDone. Scanned {scanned} photos, {found} flagged for review, {errors} errors.")
    # DM the owner a summary.
    if findings:
        msg = (f"\U0001F50D *Photo scan complete* — {found} issue(s) found in {scanned} photos:\n"
               + "\n".join(findings[:25])
               + (f"\n…and {len(findings)-25} more." if len(findings) > 25 else ""))
    else:
        msg = f"\U0001F50D *Photo scan complete* — scanned {scanned} photos, no issues flagged."
    try:
        directory.dm_email(SUBJECT, msg)
    except Exception as e:
        print("DM summary failed:", e)


if __name__ == "__main__":
    main()
