# CLAUDE.md — instructions for every Claude Code session in this repo

This repo uses **manager-funnel multi-terminal coordination**. Several Claude Code
sessions work in parallel, but there is **ONE official line into GitHub: the
MANAGER.** Workers report to the manager; the manager is the only session that
updates `main`. GitHub is the source of truth — sessions coordinate only through
committed state, never by talking directly.

Full design: `docs/MULTI_AGENT_COORDINATION.md`. Board: `WORK.md`.

## Roles

- **MANAGER** (the 24/7 PC, session-id `pc-mgr`, runs in its own clone
  `nf-ops-manager`): the **sole writer of `main`**. Owns `WORK.md`, assigns work,
  reviews every branch/PR, merges to `main`, updates the board, deletes merged
  branches. Does not write feature code unless the human asks.
- **WORKER** (any other terminal/machine, its own clone): implements ONE task at a
  time on its own branch and **reports to the manager** by pushing that branch and
  opening a PR. A worker **never** writes to `main`.

If the human hasn't said which you are, assume **WORKER** unless you're the manager
clone on the 24/7 PC.

## One clone per session (hard rule)

Two sessions must **never** share a folder — they'd share one git working tree and
corrupt each other. Each session gets its own clone:
`git clone <repo> nf-worker-<n>` and run there.

## Worker startup ritual (do this FIRST)

```bash
git pull --rebase
SESSION_ID=$(bash scripts/agent_register.sh | tail -n1)   # e.g. "macbook-air-4827"
echo "I am worker $SESSION_ID"
```

Your `.agents/<id>.log` heartbeat is the **only** thing you may push to `main` — it
is append-only presence, never conflicts. Re-run
`bash scripts/agent_register.sh heartbeat "$SESSION_ID"` every ~10 min. You may also
append free-text status lines to your own log to report to the manager, e.g.
`echo "$(date -u +%FT%TZ) status ($SESSION_ID): starting weekly-digest" >> .agents/$SESSION_ID.log && git add .agents && git commit -qm note && git push -q`.

## Worker protocol (follow exactly)

1. **Pull `main`** (read-only): `git pull --rebase`. Read `WORK.md`.
2. **Pick a task.** Prefer one the manager has marked `ASSIGNED:<your-id>`. If none
   is assigned to you, pick an unclaimed `TODO` whose `mainly:` files no active
   branch is already touching (`git fetch && git branch -r` shows active work).
3. **Branch — never touch `main` or `WORK.md`.** `git checkout -b feat/<task-slug>__<your-id>`.
   Pushing this branch IS your claim + report; the manager sees it via fetch.
   If your branch name collides with someone else's task, you picked a dup — switch.
4. **Implement + test** (`py -m unittest ...` / `py -m app.server`). Keep commits on
   your branch. Push the branch.
5. **Report done:** open a PR against `main` and append a
   `ready for review: feat/<...>` line to your `.agents/<id>.log`. **Do NOT merge.**
   The manager reviews, merges, and updates the board.
6. If blocked, append a `blocked: <reason>` line to your log and pick another task.

## Manager protocol (sole owner of `main` + `WORK.md`)

- Own `WORK.md` end to end: keep TODO/ASSIGNED/REVIEW/DONE accurate. Workers don't
  edit it — you do.
- `git fetch`, scan remote `feat/*` branches + `.agents/*.log` to see who's working
  on what; report status to the human.
- Assign work by setting `ASSIGNED:<worker-id>` on a task row when a worker is idle.
- Review each worker branch/PR; run its tests; merge to `main` (no-ff); move the row
  to DONE with attribution; delete the merged branch.
- Reassign stale work (no heartbeat > 30 min).
- Only write feature code when the human explicitly asks.

## Never

- A worker never pushes to `main` (only its own `.agents/<id>.log` heartbeat).
- A worker never edits `WORK.md` or merges — the manager owns both.
- Never run two sessions in the same folder.

## Project quick-reference

- App: Python, **stdlib `http.server`** (no FastAPI/uvicorn — Py 3.14 compat).
  Entry: `py -m app.server`. Health probe: `/healthz`.
- Persistence: **Firestore via REST** (`app/store.py`) is the live store; SQLite
  (`app/database.py`) is only the offline Vault ingest.
- AI brain: `app/brain.py` (Claude REST, model env `OPS_BRAIN_MODEL`); grounds on
  `reports.dashboard()` complete aggregates — never invent stores/numbers.
- Deploy: Cloud Run, project `nfchatbot-498419`, region `us-central1`.
- Do **not** commit: `*.sqlite3`/`*.db`, `.env`, Vault exports (mbox/CSV),
  service-account JSON, or files with real employee PII.
