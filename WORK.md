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

- [ ] (DONE-PARTIAL) Response-quality root cause FIXED (grounding on complete aggregates, commit 0f4255f). Remaining quality items split into the 4 tasks above. NEEDS DEPLOY to take effect.




- [ ] (PARKED) **SSCS integration** (TOP next priority) — see docs/FUTURE_INTEGRATIONS.md. Needs discovery first (how N&F updates the CDB: desktop keying vs POS poller/XML vs file import). Do NOT auto-assign; owner-led. mainly: docs/FUTURE_INTEGRATIONS.md + (future) app/sscs.py

- [ ] (PARKED) **Smart vendor ordering & demand forecasting** — captains order via bot; forecast-driven (best profit, least waste). After SSCS + POS. First target: fuel reordering. See docs/FUTURE_INTEGRATIONS.md. mainly: (future) app/ordering.py

## In progress

<!-- claimed rows move here -->

## Review

<!-- rows awaiting manager merge -->

## Done

- [x] (DONE) **Bot DMs/messages dashboard** — /dms (DMs grouped by person) + /messages (searchable), behind OPS_DASHBOARD_TOKEN; is_dm captured on ingest. [pc-mgr]
- [x] (DONE) **Broadcast reliability** — broadcast now targets rooms via Chat API spaces.list (reaches quiet rooms the bot is in, not just ones with recent messages), filters DM/test junk, lists which stores it reached; post_to_space gained retry/backoff for transient/429 failures. Fixes 'didn't reach Synott'. [pc-mgr]
- [x] (DONE) **Org understanding** — app/org.py: classifies each room (store/all-captains/marketing), maps room→store (via sites.py), builds a people roster (who's active where = home store), flags admins/managers; get_org brain tool + prompt so the bot answers who-works-where / who's-the-manager / what-rooms questions. [pc-mgr]
- [x] (DONE) **Broadcast to ALL store chats** — broadcast tool now posts an announcement into every store room the bot is in (scope=all_stores, default), not just all-captains; reports reached/failed. [pc-mgr]
- [x] (DONE) **Cold-DM creation** — bot can now START a DM with any org Workspace user via spaces.setup (no need for them to message first); dm_email uses ensure_dm_space (find-or-create). Needs live verification of Chat app DM perms; falls back gracefully. [pc-mgr]
- [x] (DONE) **Day-report CASH VENDOR / COMPANY GAS alerts** — OCR reads cash_vendor + company_gas; if either is non-zero (not allowed), DM admin2 (OPS_VENDOR_ALERT_EMAIL) + flag for review; 5 tests. [pc-mgr]
- [x] (DONE) **Cash-vs-deposit reconciliation** — day-report cash_amount (OCR) matched to bank deposits by store+date, flags shortfalls over threshold; new app/cash_reconcile.py + get_cash_reconcile brain tool + deposit capture + 13 tests. [pc-mgr]
- [x] (DONE) **Veeder-Root reading OCR** [worker 8341, merged by pc-mgr]
- [x] (DONE) **Message timestamps in ingestion** [worker 8686, merged by pc-mgr]
- [x] (DONE) **Multi-turn conversation memory** [worker 3575, merged by pc-mgr]
- [x] (DONE) **Dashboard reconcile + scorecard view** [worker 8341, merged by pc-mgr]
- [x] (DONE) **Proactive reconciliation alerts** — high-priority alert on BOL/Veeder mismatch over threshold [worker 3575, merged by pc-mgr]
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
