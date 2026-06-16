# Multi-Terminal / Multi-Agent Development Coordination (the "90%" plan)

Goal: let several Claude Code sessions (across the Mac, a 24/7 Windows PC, etc.)
work on this repo **in parallel without stepping on each other**, with one
session acting as the human-steered "manager." This is the pragmatic version —
GitHub as the shared brain, humans in the loop — *not* an always-on autonomous
agent fleet (which burns API budget idle and drifts).

> Status: **design only.** Not built yet. Set this up when we want parallel dev.

## The model

```
                 ┌─────────────────────────────┐
                 │  MANAGER session (the PC)    │
                 │  - breaks work into tasks    │
                 │  - writes them to WORK.md    │
                 │  - reviews & merges branches │
                 └──────────────┬──────────────┘
                                │  (via GitHub)
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
   Worker A (Mac)          Worker B (PC #2)         Worker C (...)
   claims a task           claims a task            claims a task
   on its own branch       on its own branch        on its own branch
```

GitHub is the single source of truth. No session needs to "see" another directly;
they coordinate through committed state.

## The coordination board — `WORK.md`

A tracked file at the repo root. Each task is a checkbox row with an owner and
status. Agents **must** read it before starting and claim a task by committing a
change to it (atomic via git — first push wins; the loser pulls and re-picks).

```markdown
# WORK BOARD
<!-- status: TODO | CLAIMED:<who> | REVIEW:<branch> | DONE -->

- [ ] (TODO)            Add weekly digest job
- [ ] (CLAIMED:mac-A)   Site-name normalization        branch: feat/site-names
- [ ] (REVIEW:feat/ocr) Tesseract fallback for images  branch: feat/ocr-fallback
- [x] (DONE)            Firestore persistence
```

GitHub Issues can replace `WORK.md` later (richer, assignable, has presence via
comments) — same protocol.

## Rules every session follows

1. **Pull first.** `git pull --rebase` before reading the board or starting work.
2. **Claim before coding.** Edit the task row to `CLAIMED:<session-id>` + a branch
   name, commit, and **push**. If the push rejects (someone claimed first), pull
   and pick another task. This is the anti-duplication lock.
3. **One branch per task.** `feat/<short-name>`. Never commit straight to `main`.
4. **Mark `REVIEW:<branch>`** and open a PR when done.
5. **Only the manager merges to `main`** (keeps integration coherent).
6. **Heartbeat (optional presence):** a worker appends a timestamped line to
   `.agents/<session-id>.log` and pushes every ~10 min. The manager reads these
   to see who's "online" and whether a CLAIMED task has gone stale (no heartbeat
   > 30 min ⇒ reclaim).

## Manager-session playbook

- Maintain `WORK.md` from the human's goals ("I want X, Y, Z").
- `git pull`, scan the board + `.agents/*.log`, report status to the human.
- Reassign stale claims; review and merge `REVIEW` PRs; delete merged branches.
- Never write feature code itself unless asked — it orchestrates.

## What this deliberately does NOT do

- No always-on autonomous agents (cost + reliability). Workers run when a human
  opens a terminal and points them at the board.
- No live inter-process messaging; all coordination is through git commits.
- No self-merging to `main` by workers.

## To set up (later)

1. Add `WORK.md` (template above) and a `.agents/` dir to the repo.
2. Add a `CLAUDE.md` section telling every session to follow these rules.
3. Open the manager session on the PC; open worker sessions as needed.
