from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ingest import ingest_csv
from app.reports import dashboard, open_tasks, high_priority, room_summary, render_text_report, task_action


def main():
    parser = argparse.ArgumentParser(prog="ops", description="Now & Forever Chat Ops v2 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest parsed Vault CSV into SQLite")
    p_ingest.add_argument("--csv", default="data/sample_vault_messages.csv")
    p_ingest.add_argument("--db", default="data/ops_bot.sqlite3")

    p_dash = sub.add_parser("dashboard", help="Show parsed ops dashboard")
    p_dash.add_argument("--db", default="data/ops_bot.sqlite3")

    p_tasks = sub.add_parser("tasks", help="Show open tasks")
    p_tasks.add_argument("--db", default="data/ops_bot.sqlite3")
    p_tasks.add_argument("--room")
    p_tasks.add_argument("--limit", type=int, default=25)

    p_alerts = sub.add_parser("alerts", help="Show high-priority alerts")
    p_alerts.add_argument("--db", default="data/ops_bot.sqlite3")
    p_alerts.add_argument("--limit", type=int, default=25)

    p_room = sub.add_parser("room", help="Show one room summary")
    p_room.add_argument("name")
    p_room.add_argument("--db", default="data/ops_bot.sqlite3")

    p_report = sub.add_parser("report", help="Write markdown ops report")
    p_report.add_argument("--db", default="data/ops_bot.sqlite3")
    p_report.add_argument("--out", default="outputs/ops_dashboard.md")

    p_close = sub.add_parser("close", help="Close a task by ID")
    p_close.add_argument("task_id", type=int)
    p_close.add_argument("--db", default="data/ops_bot.sqlite3")

    p_assign = sub.add_parser("assign", help="Assign a task by ID")
    p_assign.add_argument("task_id", type=int)
    p_assign.add_argument("assignee")
    p_assign.add_argument("--db", default="data/ops_bot.sqlite3")

    args = parser.parse_args()
    if args.cmd == "ingest":
        print(json.dumps(ingest_csv(args.csv, args.db), indent=2))
    elif args.cmd == "dashboard":
        print(json.dumps(dashboard(args.db), indent=2))
    elif args.cmd == "tasks":
        print(json.dumps(open_tasks(args.db, args.room, args.limit), indent=2))
    elif args.cmd == "alerts":
        print(json.dumps(high_priority(args.db, args.limit), indent=2))
    elif args.cmd == "room":
        print(json.dumps(room_summary(args.db, args.name), indent=2))
    elif args.cmd == "report":
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_text_report(args.db), encoding="utf-8")
        print(f"Wrote {out}")
    elif args.cmd == "close":
        print(json.dumps(task_action(args.db, args.task_id, "close"), indent=2))
    elif args.cmd == "assign":
        print(json.dumps(task_action(args.db, args.task_id, "assign", args.assignee), indent=2))

if __name__ == "__main__":
    main()
