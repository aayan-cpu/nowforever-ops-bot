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

- [ ] (TODO) Fix doc/code mismatch — README references `app/room_mappings.py`, `app/task_manager.py`, `app/alert_detector.py` which don't exist. Update docs to match real modules (`brain.py`, `classifier.py`, `store.py`, ...).  branch: —
- [ ] (TODO) Verify Google Chat webhook bearer token in `/chat/events` (currently accepts all requests — security hole).  branch: —
- [ ] (TODO) Add dashboard auth for `/dashboard`, `/tasks`, `/alerts` (token-based or IAP).  branch: —
- [ ] (TODO) Migrate persistence off ephemeral SQLite → Firestore or Cloud SQL (data wiped on Cloud Run restart).  branch: —
- [ ] (TODO) Weekly digest job (per-room summary).  branch: —
- [ ] (TODO) Site-name normalization across rooms.  branch: —
- [ ] (TODO) Missing/overdue report detection + reminders.  branch: —

## In progress

<!-- claimed rows move here -->

## Review

<!-- rows awaiting manager merge -->

## Done

- [x] (DONE) Escalation (SLA) job + get_scorecard tool.
- [x] (DONE) Cloud Run deploy pipeline.
