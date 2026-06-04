from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app.classifier import classify_message, category_string, clean_text, normalize_sender
from app.database import connect, init_db


def norm(v):
    if v is None:
        return ""
    return str(v)


def safe_int(v, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def pick_primary_category(categories: list[str]) -> str:
    # Do not let attachment_report dominate task category.
    priority_order = [
        "fuel_delivery_issue", "equipment_maintenance", "sales_issue", "admin_request_task",
        "deposit_cash_bank", "fuel_price_competition", "delivery_order", "daily_shift_report", "attachment_report", "general"
    ]
    for c in priority_order:
        if c in categories:
            return c
    return categories[0] if categories else "general"


def ingest_csv(csv_path: str, db_path: str = "data/ops_bot.sqlite3") -> dict:
    """Ingest parsed Vault messages into SQLite using only Python stdlib."""
    init_db(db_path)
    inserted = 0
    tasks = 0
    duplicates = 0
    rooms = {}
    seen_fingerprints = set()
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        with connect(db_path) as conn:
            conn.execute("DELETE FROM tasks")
            conn.execute("DELETE FROM messages")
            for row in reader:
                message = clean_text(norm(row.get("message")))
                attachment_count = safe_int(row.get("attachment_count"), 0)
                room_id = norm(row.get("room_id"))
                room_name = norm(row.get("room_name"))
                rooms[room_id] = room_name
                c = classify_message(message, attachment_count, room_name)
                is_dup = c.fingerprint in seen_fingerprints
                seen_fingerprints.add(c.fingerprint)
                if is_dup:
                    duplicates += 1
                sender = normalize_sender(norm(row.get("sender")))
                cur = conn.execute(
                    """
                    INSERT INTO messages (
                        source_idx, room_id, room_name, data_id, sender, timestamp_raw, message,
                        attachments, attachment_count, categories, priority, is_task,
                        extracted_amounts, extracted_gallons, extracted_prices, assigned_hint,
                        fingerprint, confidence, is_duplicate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        safe_int(row.get("idx"), 0), room_id, room_name, norm(row.get("data_id")), sender,
                        norm(row.get("timestamp")), message, norm(row.get("attachments")), attachment_count,
                        category_string(c.categories), c.priority, 1 if c.is_task else 0,
                        json.dumps(c.extracted_amounts), json.dumps(c.extracted_gallons), json.dumps(c.extracted_prices), c.assigned_hint,
                        c.fingerprint, c.confidence, 1 if is_dup else 0,
                    ),
                )
                inserted += 1
                if (c.is_task or c.priority == "high") and not is_dup:
                    category = pick_primary_category(c.categories)
                    conn.execute(
                        """
                        INSERT INTO tasks (message_id, room_name, sender, task_title, task_text, category, priority, assigned_hint, assignee, source_fingerprint, confidence)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (cur.lastrowid, room_name, sender, c.task_title, message[:4000], category, c.priority, c.assigned_hint, c.assigned_hint, c.fingerprint, c.confidence),
                    )
                    tasks += 1
    return {"messages_inserted": inserted, "tasks_created": tasks, "rooms_seen": len(set(rooms.values())), "duplicates_skipped_for_tasks": duplicates}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest parsed Vault messages into SQLite.")
    parser.add_argument("--csv", default="data/sample_vault_messages.csv")
    parser.add_argument("--db", default="data/ops_bot.sqlite3")
    args = parser.parse_args()
    print(json.dumps(ingest_csv(args.csv, args.db), indent=2))
