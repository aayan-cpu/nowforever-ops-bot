from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from app.reports import (
    dashboard, high_priority, open_tasks, room_summary, task_action,
    render_dashboard_html, render_tasks_html, render_alerts_html, render_room_html
)
from app.chat_live import handle_google_chat_event, ingest_live_event, google_chat_response
from app import digests

# Kept for backward compat with callers/tests; data now lives in Firestore (app/store.py).
DB_PATH = os.getenv("OPS_DB_PATH", "data/ops_bot.sqlite3")


def send_json(handler: BaseHTTPRequestHandler, data, status: int = 200):
    body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_html(handler: BaseHTTPRequestHandler, html: str, status: int = 200):
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class OpsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        want_json = qs.get("format", [""])[0] == "json" or path.startswith("/api/")
        try:
            if path == "/" or path == "/dashboard":
                return send_json(self, dashboard(DB_PATH)) if want_json else send_html(self, render_dashboard_html(DB_PATH))
            if path == "/tasks":
                room = qs.get("room", [None])[0]
                limit = int(qs.get("limit", [150])[0])
                return send_json(self, open_tasks(DB_PATH, room, limit)) if want_json else send_html(self, render_tasks_html(DB_PATH, room))
            if path == "/alerts":
                limit = int(qs.get("limit", [100])[0])
                return send_json(self, high_priority(DB_PATH, limit)) if want_json else send_html(self, render_alerts_html(DB_PATH))
            if path.startswith("/rooms/"):
                room_name = unquote(path.split("/rooms/", 1)[1])
                return send_json(self, room_summary(DB_PATH, room_name)) if want_json else send_html(self, render_room_html(DB_PATH, room_name))
            if path == "/api/dashboard":
                return send_json(self, dashboard(DB_PATH))
            if path == "/chat/test":
                sample = {
                    "type": "MESSAGE",
                    "space": {"name": "spaces/test", "displayName": "4 Channelview"},
                    "user": {"displayName": "Local Test"},
                    "message": {"name": "spaces/test/messages/local", "text": "NEED GAS @ Admin 4"},
                }
                res = ingest_live_event(sample, DB_PATH)
                return send_json(self, {"ok": True, "test_event_result": res, "open": ["/dashboard", "/tasks", "/alerts"]})
            return send_json(self, {"error": "not found", "try": ["/dashboard", "/tasks", "/alerts", "/chat/test", "/rooms/4%20Channelview"]}, 404)
        except Exception as e:
            return send_json(self, {"error": str(e)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        parts = path.strip("/").split("/")
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw_body = self.rfile.read(length).decode("utf-8") if length else ""

            # Live Google Chat HTTP endpoint. Configure Google Chat API to this URL:
            # https://YOUR-SERVICE-URL/chat/events
            if path in {"/chat/events", "/google-chat/events"}:
                try:
                    event = json.loads(raw_body or "{}")
                except json.JSONDecodeError:
                    event = {"type": "MESSAGE", "text": raw_body}
                response = handle_google_chat_event(event, DB_PATH)
                return send_json(self, response)

            # Scheduled briefings/reminders, triggered by Cloud Scheduler.
            # Protected by a shared token header so only the scheduler can fire them.
            if len(parts) >= 2 and parts[0] == "cron":
                if self.headers.get("X-Cron-Token", "") != os.getenv("OPS_CRON_TOKEN", ""):
                    return send_json(self, {"error": "unauthorized"}, 401)
                fn = digests.JOBS.get(parts[1])
                if not fn:
                    return send_json(self, {"error": "unknown job", "jobs": list(digests.JOBS)}, 404)
                return send_json(self, fn())

            # Local/test ingestion endpoint. Useful before wiring Google Chat.
            if path == "/chat/test":
                event = json.loads(raw_body or "{}") if raw_body else {
                    "type": "MESSAGE",
                    "space": {"name": "spaces/test", "displayName": "4 Channelview"},
                    "user": {"displayName": "Local Test"},
                    "message": {"name": "spaces/test/messages/local", "text": "NEED GAS @ Admin 4"},
                }
                res = ingest_live_event(event, DB_PATH)
                return send_json(self, res)

            form = parse_qs(raw_body)
            if len(parts) == 3 and parts[0] == "tasks":
                task_id = int(parts[1])
                action = parts[2]
                assignee = form.get("assignee", [None])[0]
                task_action(DB_PATH, task_id, action, assignee)
                self.send_response(303)
                self.send_header("Location", "/tasks")
                self.end_headers()
                return
            return send_json(self, {"error": "not found"}, 404)
        except Exception as e:
            return send_json(self, {"error": str(e)}, 500)

    def log_message(self, format, *args):
        print("[server]", format % args)


def run(host: str | None = None, port: int | None = None):
    host = host or os.getenv("HOST", "127.0.0.1")
    port = port or int(os.getenv("PORT", "8000"))
    print(f"Now & Forever Chat Ops v3 running at http://{host}:{port}")
    print("Dashboard: /dashboard  Tasks: /tasks  Alerts: /alerts")
    print("Google Chat endpoint: /chat/events")
    HTTPServer((host, port), OpsHandler).serve_forever()


if __name__ == "__main__":
    run()
