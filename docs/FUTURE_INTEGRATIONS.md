# Future Integrations & Jarvis Roadmap

Captured so the bot can grow into a full operations "Jarvis." Each integration is
gated on a specific OAuth scope (added to the DWD client `111828330959106535963`)
or an external API key. Build per-feature, least-privilege.

## ⭐ SSCS integration (TOP PRIORITY — investigate first, build later)

**What it is:** SSCS Inc.'s **Computerized Daily Book (CDB)** — the back-office
bookkeeping system that holds each store's daily sales / fuel / cash numbers. A
classic petroleum/c-store back office (sscsinc.com), in use since the 1980s.

**Why it matters:** staff have to **check and update SSCS constantly**, and they're
chronically behind — this is one of the biggest recurring toils in the chats
("SSCS not updated since the 3rd", "XML Gateway down → can't update SSCS",
people tagged to "update SSCS ASAP"). Taking this off people is high-value.

**The blocker — access model is UNKNOWN / mixed (per owner, 2026-06-17).** SSCS is
NOT a modern cloud API; traditionally it's a **desktop app + a POS "poller"**
(the XML gateway that feeds sales data from the POS). Before any build we must find
out **how Now & Forever actually updates it.** Open questions to resolve:
1. Is it the CDB **desktop app** (staff key numbers in), a **POS poller/XML gateway**
   auto-feed, a **file import** (CSV/XML), or a mix — and does it vary by store?
2. When a clerk "updates SSCS," what exactly do they type, and from what source
   (the day-report photos? POS totals?)?
3. Does CDB expose **any** programmatic path — file import, poller API, or DB? (Ask
   SSCS support / check the CDB install.)
4. What machine does it run on, and what credentials would a bot need?

**Candidate approaches, by feasibility (decide after Q1–Q4):**
- **Tier 1 — "prep the numbers" (buildable now, no SSCS access):** bot reads the
  day-report photos it already OCRs, extracts each store's figures, and hands a
  clean **SSCS-ready summary** + flags which stores are behind. Turns "hunt for the
  numbers and key them in" into "paste these." Big toil reduction, zero SSCS access.
- **Tier 2 — file import:** if CDB accepts a CSV/XML import, bot generates & submits it.
- **Tier 3 — poller/XML gateway:** integrate with the existing feed (also lets the
  bot *detect* when the gateway is down — a known recurring outage).
- **Tier 4 — screen scanning / UI automation (owner floated "scanning"):** OCR/vision
  reads the SSCS screen, or RPA drives the desktop app. Fragile; last resort.

**Status:** parked — owner wants to pursue this next; needs the discovery above first.

## ⭐ Smart vendor ordering & demand forecasting (high-value — after SSCS)

**Vision (owner, 2026-06-17):** let store captains order inventory from vendors
*through the bot*, with the bot recommending **what and how much to order** using
logic + forecasting — optimizing for **best operation, best profit, least waste**
(no stockouts, no overstock/spoilage). This is the clearest "takes real work off
people" agent feature.

**Core capability = per-store demand forecasting,** then turn the forecast into a
concrete order. Factors: sales velocity per item/category, day-of-week & seasonality,
promotions, shelf-life/spoilage (perishables), vendor lead times, and par (min/max)
levels. Goal metrics to optimize: minimize lost sales (stockouts) + minimize waste
(overstock) + best margin (order timing, quantity, vendor pricing).

**Dependencies (mostly the same as SSCS/POS work):**
- **Sales + inventory data** — needs POS integration (already planned) for velocity
  and current stock; SSCS/CDB may also hold purchase/inventory history.
- **Vendor ordering channels** — how each vendor takes orders (API, email/EDI, portal).
- **Par levels & budgets** per store, set with the captains.

**Tiers (build trust one step at a time):**
1. **Recommend** — bot suggests an order (items + quantities) per vendor; captain
   reviews/adjusts and places it. Needs sales/inventory data only.
2. **Draft & send** — on captain approval, bot submits the order to the vendor.
3. **Auto-reorder within guardrails** — bot reorders automatically inside par levels
   + budget caps, captain notified. Highest trust.

**First concrete instance = fuel reordering.** We already have tank-level signals
(Veeder-Root) + BOL/Veeder reconciliation, and "need gas" is the most repeated
request in the chats — predictable fuel reordering is the natural first target.

**Status:** parked — capture now, build after SSCS discovery + POS integration.

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
