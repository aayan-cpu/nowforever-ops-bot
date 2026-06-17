# WORK BOARD

<!--
  Shared task board for multi-terminal development. GitHub is the source of truth.
  PROTOCOL (full details in docs/MULTI_AGENT_COORDINATION.md and CLAUDE.md):
    1. `git pull --rebase` before touching this file.
    2. Claim a task: change its status to (CLAIMED:<session-id>) + add a branch,
       commit, and PUSH. If the push is rejected, someone claimed first —
       pull and pick another task.
    3. One branch per task: feat/<short-name>. Never commit features to main.
    4. When done: set status to (REVIEW:<branch>) and open a PR.
    5. Only the MANAGER session merges to main.

  Status legend:  TODO | CLAIMED:<who> | REVIEW:<branch> | DONE
  session-id examples: pc-mgr (manager), mac-A, pc2-B
-->

## Manager
- Active manager session: **pc-mgr** (DESKTOP-EBH1KD9)

## Backlog

> Each task is independent. The file each mainly touches is noted so two workers
> don't fight over the same file — prefer claiming tasks that touch different files.

- [ ] (TODO) **Message-everyone / proactive DM (owner ask)** — bot said "I can't message Abdul Moiz directly." `app/directory.py` already has the foundation (resolve org users + DM anyone via Admin SDK domain-wide delegation). Wire a `message_user` / `broadcast` tool into `app/brain.py` so it can DM/assign to any named person, not just admins who've DM'd it. NOTE: needs GCP domain-wide-delegation creds to test live. mainly: app/brain.py + app/directory.py  branch: —
- [ ] (TODO) **Message timestamps in ingestion** — bot can't see message send-times, so it can't tell when shift/day reports were posted or flag late/missing-by-cutoff. Carry the Chat message timestamp through ingest → store → snapshot. mainly: app/ingest.py, app/chat_live.py, app/store.py  branch: —
- [ ] (TODO) **Dead single-word commands** — early logs show "alerts"/"reports"/"report" replying just "Got it." instead of acting. Audit the command router in `app/chat_live.py` so bare keywords hit the real handlers (or fall through to the brain), never a blank ack. mainly: app/chat_live.py  branch: —
- [ ] (REVIEW:feat/task-title-truncation) **Truncated task titles** — logs show mangled titles ("#170 ,666 gallons", "#156 't the customers"): leading characters are being stripped. Fix task_title extraction in ingestion/classifier. mainly: app/classifier.py / app/ingest.py  branch: feat/task-title-truncation
- [ ] (DONE-PARTIAL) Response-quality root cause FIXED (grounding on complete aggregates, commit 0f4255f). Remaining quality items split into the 4 tasks above. NEEDS DEPLOY to take effect.
- [ ] (TODO) **Webhook bearer-token verification** for `/chat/events` (security hole: accepts any request). NOTE FROM MANAGER: Google Chat sends `Authorization: Bearer <JWT>` signed by `chat@system.gserviceaccount.com`, audience = the project number. `cryptography` is NOT installed (breaks on Py 3.14) — do RS256 verification the stdlib way, mirroring the JWT *signing* pattern already in `app/chat_media.py:_sa_key_token`. Verify sig (Google x509 certs, cached), `iss`, `aud` (new env `OPS_CHAT_AUDIENCE`), `exp`. Gate behind env `OPS_VERIFY_CHAT_TOKEN=1` so it can't dark the live bot before the audience is configured. New module `app/chat_auth.py`; wire into `app/server.py` do_POST `/chat/events`. mainly: app/chat_auth.py (new), app/server.py  branch: —
- [ ] (TODO) **Dashboard auth** for `/dashboard`, `/tasks`, `/alerts` — token-based (e.g. `?token=` / `X-Ops-Token` vs new `OPS_DASHBOARD_TOKEN`), gated so it stays open when the env var is unset. mainly: app/server.py  branch: —
- [ ] (TODO) **Weekly digest job** (per-room summary) — add a `JOBS` entry in `app/digests.py` (follow the existing daily-summary job), wired to `/cron/<name>`. mainly: app/digests.py  branch: —
- [ ] (TODO) **Site-name normalization** — one canonical resolver (e.g. "11", "Windchase", "11 N&F Windchase" → same site). mainly: new app/sites.py + callers  branch: —
- [ ] (TODO) **Missing/overdue report detection + reminders** — flag sites that haven't reported, DM/post a reminder. mainly: app/digests.py + app/reports.py  branch: —
- [ ] (TODO) **Test suite + smoke tests** — no `tests/` exists yet. Add pytest-free stdlib `unittest` tests for classifier, reports, server routes, and the new chat_auth. Highest-leverage for letting workers self-verify. mainly: tests/ (new)  branch: —
- [ ] (TODO) **OCR for BOL / fuel-delivery receipts** (Phase 5) — `app/vision.py` exists; extract gallons/product from receipt images. mainly: app/vision.py  branch: —
- [ ] (TODO) **Veeder-Root vs BOL mismatch detection** (Phase 5) — compare delivered (BOL) vs tank gauge, flag discrepancies like the ~2,500 gal Channelview case. mainly: new app/reconcile.py  branch: —
- [ ] (TODO) **Scoped roles** (docs/ROLES.md "Planned") — `roles` map (email→role) with permission + store scope below admin. mainly: new app/roles.py + brain/command handlers  branch: —
- [ ] (TODO) **Audit remaining docs for stale module refs** — README is fixed; sweep `docs/*.md` for references to nonexistent modules / outdated SQLite-as-live claims. mainly: docs/  branch: —

## In progress

<!-- claimed rows move here -->

## Review

<!-- rows awaiting manager merge -->

## Done

- [x] (DONE) **Live incident fix** — uptime flapping ("Ops Bot Down" alerts). Single-threaded HTTPServer let a 45s Claude call block the health probe; switched to ThreadingHTTPServer + added cheap `/healthz`. NEEDS DEPLOY + repoint uptime check to /healthz + `--min-instances=1`. [pc-mgr]
- [x] (DONE) Fix README architecture drift (fake modules, FastAPI→http.server, SQLite→Firestore, room mapping note). [pc-mgr]
- [x] (DONE) Firestore persistence — already implemented: live path uses `app/store.py` (Firestore REST); SQLite (`app/database.py`) remains only for the offline Vault ingest. No migration needed. [verified pc-mgr]
- [x] (DONE) Escalation (SLA) job + get_scorecard tool.
- [x] (DONE) Cloud Run deploy pipeline.
