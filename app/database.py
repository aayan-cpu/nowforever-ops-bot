from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.getenv("OPS_DB_PATH", "data/ops_bot.sqlite3")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS rooms (
    room_id TEXT PRIMARY KEY,
    room_name TEXT NOT NULL,
    participants TEXT,
    first_seen TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_idx INTEGER,
    room_id TEXT,
    room_name TEXT,
    data_id TEXT,
    sender TEXT,
    timestamp_raw TEXT,
    message TEXT,
    attachments TEXT,
    attachment_count INTEGER DEFAULT 0,
    categories TEXT,
    priority TEXT,
    is_task INTEGER DEFAULT 0,
    extracted_amounts TEXT,
    extracted_gallons TEXT,
    extracted_prices TEXT,
    assigned_hint TEXT,
    fingerprint TEXT,
    confidence REAL DEFAULT 0,
    is_duplicate INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_name);
CREATE INDEX IF NOT EXISTS idx_messages_priority ON messages(priority);
CREATE INDEX IF NOT EXISTS idx_messages_categories ON messages(categories);
CREATE INDEX IF NOT EXISTS idx_messages_task ON messages(is_task);
CREATE INDEX IF NOT EXISTS idx_messages_fingerprint ON messages(fingerprint);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    room_name TEXT,
    sender TEXT,
    task_title TEXT,
    task_text TEXT,
    category TEXT,
    priority TEXT,
    assigned_hint TEXT,
    assignee TEXT,
    status TEXT DEFAULT 'open',
    source_fingerprint TEXT,
    confidence REAL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    closed_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_room ON tasks(room_name);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_fingerprint ON tasks(source_fingerprint);
"""

@contextmanager
def connect(path: str | None = None):
    db_path = path or DB_PATH
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        # migrations for users who run v2 over v1 DB
        existing = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        for col, ddl in {
            "fingerprint": "ALTER TABLE messages ADD COLUMN fingerprint TEXT",
            "confidence": "ALTER TABLE messages ADD COLUMN confidence REAL DEFAULT 0",
            "is_duplicate": "ALTER TABLE messages ADD COLUMN is_duplicate INTEGER DEFAULT 0",
        }.items():
            if col not in existing:
                conn.execute(ddl)
        existing_t = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        for col, ddl in {
            "task_title": "ALTER TABLE tasks ADD COLUMN task_title TEXT",
            "assignee": "ALTER TABLE tasks ADD COLUMN assignee TEXT",
            "source_fingerprint": "ALTER TABLE tasks ADD COLUMN source_fingerprint TEXT",
            "confidence": "ALTER TABLE tasks ADD COLUMN confidence REAL DEFAULT 0",
            "updated_at": "ALTER TABLE tasks ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP",
        }.items():
            if col not in existing_t:
                conn.execute(ddl)
