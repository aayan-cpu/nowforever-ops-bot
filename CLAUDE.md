# CLAUDE.md — instructions for every Claude Code session in this repo

This repo uses **multi-terminal coordination**. Several Claude Code sessions
(Mac, the 24/7 Windows PC, etc.) work in parallel. GitHub is the single source
of truth — sessions coordinate only through committed state, never directly.

Full design: `docs/MULTI_AGENT_COORDINATION.md`. Board: `WORK.md`.

## First, know your role

There are two kinds of session:

- **MANAGER** (runs on the 24/7 PC, session-id `pc-mgr`): maintains `WORK.md`
  from the human's goals, reviews PRs, and is the **only** session that merges to
  `main`. The manager does **not** write feature code unless explicitly asked — it
  orchestrates.
- **WORKER** (Mac, second PC, etc.): claims one task at a time and implements it
  on a branch.

If you don't know which you are, **ask the human** at the start of the session.
Pick a unique session-id (e.g. `mac-A`, `pc2-B`).

## Worker protocol (follow exactly)

1. **Pull first.** `git pull --rebase` before reading `WORK.md` or starting work.
2. **Claim before coding.** Edit the task's row in `WORK.md` to
   `(CLAIMED:<session-id>)`, fill in `branch: feat/<short-name>`, commit, and
   **push**. If the push is rejected, someone claimed first — `git pull --rebase`
   and pick a different task. This is the anti-duplication lock (first push wins).
3. **One branch per task.** `feat/<short-name>`. **Never commit features to `main`.**
4. **When done**, set the row to `(REVIEW:<branch>)`, commit, push, and open a PR
   against `main`. Do **not** merge it yourself.
5. **Heartbeat (optional).** Append a timestamped line to `.agents/<session-id>.log`
   and push every ~10 min so the manager can see you're online.

## Manager protocol

- Maintain `WORK.md` from the human's stated goals.
- `git pull`, scan the board + `.agents/*.log`, report status to the human.
- Reassign stale claims (no heartbeat > 30 min on a CLAIMED task).
- Review `REVIEW:` PRs; merge to `main`; delete merged branches.
- Only write feature code when the human explicitly asks.

## Never

- Never let a worker merge to `main`.
- Never commit feature work straight to `main` (branch + PR always).
- Never start coding a task without first claiming it in `WORK.md` and pushing.

## Project quick-reference

- App: Python (FastAPI-lite, stdlib-heavy — avoids pydantic/pandas/uvicorn for
  Python 3.14 compatibility). Entry: `python -m app.server`.
- Persistence: SQLite (`OPS_DB_PATH`), Firestore planned.
- Deploy: Cloud Run, project `nfchatbot-498419`, region `us-central1`.
- Do **not** commit: `*.sqlite3`/`*.db`, `.env`, Vault exports (mbox/CSV),
  service-account JSON, or files with real employee PII.
