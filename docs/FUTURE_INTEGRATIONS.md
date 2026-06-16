# Future Integrations & Jarvis Roadmap

Captured so the bot can grow into a full operations "Jarvis." Each integration is
gated on a specific OAuth scope (added to the DWD client `111828330959106535963`)
or an external API key. Build per-feature, least-privilege.

## Calendar (planned — "soon")

**Scope:** `https://www.googleapis.com/auth/calendar` (DWD; impersonates a user to
read/write *their* calendar).

**Vision — the bot manages time for the operation, by chat:**
- **Schedule things for people:** "Book the AC tech at Galveston Tuesday 2pm and
  put it on the Galveston manager's calendar" → bot creates the event and invites
  the right person(s).
- **Deliveries & vendor visits** as calendar events (fuel deliveries, maintenance,
  inspections) — tied to the related task so closing one updates the other.
- **Reminders for staff:** "remind the Westheimer manager about the restroom repair
  tomorrow morning" → event + notification on their calendar.
- **Deadlines as events:** daily-report due times, compliance deadlines (e.g. THC),
  bank-deposit cutoffs.
- **Shift awareness (later, with directory groups):** see who's scheduled, flag
  coverage gaps, remind people of their shifts.
- **Proactive:** the morning briefing includes "today's scheduled items"; the bot
  pings before events.

**How:** brain gets a `schedule_event` tool (title, time, attendees, store). With
the calendar scope + DWD, it writes to the relevant person's calendar and confirms
in plain language. Owner/admin-gated for creating events on others' calendars.

---

## Other planned integrations (add the scope when we build it)

| Integration | Scope / key | What it unlocks |
|---|---|---|
| **Gmail (read)** | `gmail.readonly` (DWD) | Auto-pull Veeder-Root delivery reports & vendor invoices that arrive by email → auto-reconcile BOL/Veeder without photos. **High sensitivity.** |
| **Drive (read)** | `drive.readonly` (DWD) | Read reports/spreadsheets stored in Drive. **High sensitivity.** |
| **Sheets** | `spreadsheets` (DWD) | Read/write the sales & tracking sheets the team already uses. |
| **Directory groups** | `admin.directory.group.readonly` | Team/role membership → scoped roles, regional routing. |
| **Chat admin** | `chat.admin.spaces` + `chat.admin.memberships` | Manage spaces org-wide; auto-add the bot to every (incl. new) room. |
| **SMS** | Twilio account + key | Text critical alerts to people off Chat. |
| **POS / sales** | vendor API | Live sales data, anomaly detection, per-store performance. |
| **Veeder-Root** | vendor API or email | Auto tank readings for continuous reconciliation. |

## Current scopes (authorized)
- `chat.bot` (app auth — post / DM / proactive)
- `chat.messages.readonly` (DWD — read history)
- *(adding now)* `admin.directory.user.readonly` (DM anyone), `chat.spaces.readonly` (see all spaces)

## Principle
Least-privilege, staged. Owner-gated for anything that acts on others (DMs,
calendar events, directives). Deliberate broadcasts only (no accidental mass-DM),
with logging.
