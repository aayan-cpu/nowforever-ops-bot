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

- [ ] (ASSIGNED:desktop-ebh1kd9-8686) **Message timestamps in ingestion** — bot can't see message send-times, so it can't tell when shift/day reports were posted or flag late/missing-by-cutoff. Carry the Chat message timestamp through ingest → store → snapshot. mainly: app/ingest.py, app/chat_live.py, app/store.py  branch: —
- [ ] (DONE-PARTIAL) Response-quality root cause FIXED (grounding on complete aggregates, commit 0f4255f). Remaining quality items split into the 4 tasks above. NEEDS DEPLOY to take effect.


- [ ] (ASSIGNED:desktop-ebh1kd9-8341) **Dashboard surfaces reconcile + scorecard** — render fuel-reconcile mismatches and per-store scorecard in the HTML views. mainly: app/reports.py  branch: —
- [ ] (TODO) **Veeder-Root reading OCR** — parse tank-gauge reading photos (complements BOL OCR). mainly: app/vision.py  branch: —

- [ ] (TODO) **Proactive reconciliation alerts** — when BOL-vs-Veeder mismatch exceeds a threshold, raise a high-priority alert/DM (builds on app/reconcile.py). mainly: app/reconcile.py  branch: —
- [ ] (TODO) **Multi-turn conversation memory** — let the brain remember the last few turns per user so follow-ups ("and the other one?") resolve. mainly: app/brain.py  branch: —

## In progress

<!-- claimed rows move here -->

## Review

<!-- rows awaiting manager merge -->

## Done

- [x] (DONE) **Webhook bearer-token verification** — pure-stdlib RS256 JWT verify (strict PKCS#1 v1.5, iss/aud/exp, cert cache), gated by OPS_VERIFY_CHAT_TOKEN. Security blocker closed. [worker 3575, merged by pc-mgr]
- [x] (DONE) **Report cutoff + late flagging** — per-store expected report times, flag late [worker 3575, merged by pc-mgr]
- [x] (DONE) **Near-duplicate task dedupe** — collapse repeated messages into one task [worker 3575, merged by pc-mgr]
- [x] (DONE) **Brain API resilience** — retry/backoff+timeout for Claude REST call [worker 3575, merged by pc-mgr]
- [x] (DONE) **Docs audit** — fixed stale module/SQLite refs in docs/ [worker 8341, merged by pc-mgr]
- [x] (DONE) **POS integration scaffold** — app/pos.py interface + fake adapter + tests [worker 8686, merged by pc-mgr]
- [x] (DONE) **Scoped roles** — email→role map w/ permission+store scope (app/roles.py) [worker 8341, merged by pc-mgr]
- [x] (DONE) **Site-aware classifier** — room/site context for better category+priority [worker 8341, merged by pc-mgr]
- [x] (DONE) **CI workflow** — GitHub Actions runs the 210-test suite on push/PR [worker 3575, merged by pc-mgr]
- [x] (DONE) **OCR for BOL / fuel-delivery receipts** [worker 8341, merged by pc-mgr]
- [x] (DONE) **Missing/overdue report detection + reminders** [worker 3575, merged by pc-mgr]
- [x] (DONE) **Veeder-Root vs BOL reconciliation** — app/reconcile.py BOL-vs-gauge mismatch detection + tests [worker 8341, merged by pc-mgr]
- [x] (DONE) **Dead single-word commands** — bare keywords route to real handlers + tests [worker 8341, merged by pc-mgr]
- [x] (DONE) **Message-everyone / proactive DM** — message_user tool wired into brain.py via directory.py + tests [worker 8686, merged by pc-mgr]
- [x] (DONE) **Site-name normalization** — app/sites.py canonical resolver + wired into digests/reports + tests [worker 3575, merged by pc-mgr]
- [x] (DONE) **Weekly digest job** — JOBS entry in digests.py + /cron wiring + tests [worker 8686, merged by pc-mgr]
- [x] (DONE) **Test suite** — 77 unittest cases (classifier/reports/server) + fake-store harness [worker 8341, merged by pc-mgr]
- [x] (DONE) **Dashboard auth** — OPS_DASHBOARD_TOKEN gate (hmac) on dashboard/data views + tests [worker 8686, merged by pc-mgr]
- [x] (DONE) **Truncated task titles** — mention-stripping regex ate leading chars of titles ('@Admin 2,666' -> ',666'); fixed + 10 unit tests. [worker desktop-ebh1kd9-1774, merged by pc-mgr]
- [x] (DONE) **Live incident fix** — uptime flapping ("Ops Bot Down" alerts). Single-threaded HTTPServer let a 45s Claude call block the health probe; switched to ThreadingHTTPServer + added cheap `/healthz`. NEEDS DEPLOY + repoint uptime check to /healthz + `--min-instances=1`. [pc-mgr]
- [x] (DONE) Fix README architecture drift (fake modules, FastAPI→http.server, SQLite→Firestore, room mapping note). [pc-mgr]
- [x] (DONE) Firestore persistence — already implemented: live path uses `app/store.py` (Firestore REST); SQLite (`app/database.py`) remains only for the offline Vault ingest. No migration needed. [verified pc-mgr]
- [x] (DONE) Escalation (SLA) job + get_scorecard tool.
- [x] (DONE) Cloud Run deploy pipeline.
