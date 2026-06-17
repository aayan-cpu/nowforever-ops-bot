# Known Limitations

This document comprehensively covers all known technical constraints, risks, and limitations of the NowForever Ops Bot as of June 2026.

> **Audit note (2026-06-17):** several items below have since shipped and are
> marked **✅ Resolved** inline. The live bot persists to **Cloud Firestore**
> (`app/store.py`), not SQLite — SQLite (`app/database.py`) is now used only for
> the offline Vault ingest. Canonical site resolution lives in `app/sites.py`
> (there is no `app/room_mappings.py`).

---

## 1. Python 3.14 Compatibility

**Severity: High (development only)**

The development machine runs Python 3.14, which breaks several packages due to C extension compilation failures:

| Package | Issue |
|---|---|
| `pydantic-core` | C extension fails to build on Python 3.14 |
| `pandas` | NumPy C extension incompatibility |
| `uvicorn` | Event loop compatibility issues |
| `aiohttp` | Partially broken |

**Current workaround:** All code from v3 onward uses minimal dependencies — standard library HTTP handling and lightweight JSON processing only. No pydantic, pandas, or uvicorn.

**Impact on Cloud Run:** Cloud Run runs the container that was built by Cloud Build. The Dockerfile specifies Python 3.11 (or whatever is in the container base image), so Cloud Run itself is unaffected by the developer's Python 3.14 environment.

**Long-term fix:** Use `pyenv` to install Python 3.12 locally for development. Run `pyenv install 3.12.4` and set as local version with `pyenv local 3.12.4`.

---

## 2. SQLite Ephemeral Storage on Cloud Run

**✅ Resolved (Phase 3) — severity was High (production impact)**

This was a real risk *while* SQLite was the live store: Cloud Run is stateless,
so a `data/ops_bot.sqlite3` file in the container's writable layer was lost on
scale-out, redeploy, or container replacement.

**Resolution:** The live bot now persists to **Cloud Firestore** via REST in
`app/store.py` (serverless, durable across instances). SQLite (`app/database.py`)
is retained only for the **offline Google Vault ingest** on a developer machine —
it is never the source of truth at runtime, so its ephemerality no longer matters.
`OPS_DB_PATH` therefore only affects that offline ingest, not the deployed bot.

---

## 3. Historical Data Only — No Live Ingestion Yet

**✅ Resolved (Phase 2) — severity was High**

**Resolution:** The bot is live in Google Chat. `app/server.py` exposes the
`/chat/events` webhook and `app/chat_live.py` (`ingest_live_event`) classifies and
stores each incoming message in Firestore in real time. The Vault mbox export is
now only the historical backfill, not the sole data source.

---

## 4. No Dashboard Authentication

**✅ Resolved — severity was High (security risk)**

**Resolution:** The operational views (`/dashboard`, `/tasks`, `/alerts`, and the
`?format=json` data) are gated behind a shared token when `OPS_DASHBOARD_TOKEN`
is set (passed as `?token=` or the `X-Ops-Token` header; verified with an
`hmac.compare_digest` constant-time check in `app/server.py`). The gate is
fail-open only when the env var is unset, so existing deploys don't break before
the token is configured.

**Optional hardening (future):** Use Google Cloud IAP (Identity-Aware Proxy) to
gate the dashboard behind Google login instead of a shared token.

---

## 5. Webhook Token Not Verified

**Severity: High (security risk) — fix in progress**

Google Chat sends a bearer token in each webhook request for authenticity verification. The current `/chat/events` handler does not yet verify this token, meaning:
- Any HTTP client can POST to the endpoint and trigger bot responses
- The bot could be spoofed or spammed

**Fix (in progress):** Verify the `Authorization: Bearer <JWT>` (signed by
`chat@system.gserviceaccount.com`) the stdlib way — RS256 against Google's cached
x509 certs, checking `iss`/`aud`/`exp` — in a new `app/chat_auth.py` wired into
`app/server.py`. Gated behind `OPS_VERIFY_CHAT_TOKEN=1` (with `OPS_CHAT_AUDIENCE`)
so it can't dark the live bot before the audience is configured.

---

## 6. No Proactive Messaging

**✅ Resolved (Phase 4) — severity was Medium**

**Resolution:** `app/digests.py` defines scheduled jobs (`JOBS`) — morning digest,
midday urgent reminder, missing/overdue report detection + reminder, end-of-day
and weekly summaries, and SLA escalation — posted via `app/chat_media.post_to_space`.
Cloud Scheduler triggers them by hitting `/cron/<name>` on the bot (gated by
`OPS_CRON_TOKEN`).

---

## 7. Single Region Deployment

**Severity: Low (availability risk)**

The service is deployed to `us-central1` only. If that GCP region experiences an outage, the bot will be unavailable.

**Fix:** Add a secondary region (`us-east1`) and put a Global Load Balancer in front. Low priority given the bot is operational, not customer-facing.

---

## 8. No Uptime Monitoring or Alerting

**Severity: Low (partially resolved)**

A cheap `/healthz` probe was added and the server switched to
`ThreadingHTTPServer` so a slow Claude call can no longer block the health check
(this had caused "Ops Bot Down" uptime flapping). A Cloud Monitoring uptime check
points at `/healthz`. Still missing:
- Error-rate monitoring and latency tracking
- A paging/escalation policy beyond email

**Fix:** Configure an alerting policy to email `aayan@khawarsons.com` if `/healthz`
is down for more than 5 minutes, plus error-rate/latency dashboards.

---

## 9. Message Classifier Is Basic

**Severity: Medium**

The current message classifier uses keyword matching to categorize messages (gas delivery, equipment failure, power issue, etc.). It has known failure modes:
- Sarcasm or negation: "no issues today" might match "issues"
- Mixed-topic messages may be mis-categorized
- Non-English messages (some stations have Spanish-speaking staff) are not handled
- Short messages like "ok" or "👍" generate low-quality task entries

**Fix (Phase 3):** Replace keyword matching with a proper NLP classifier. Options: fine-tuned BERT, OpenAI embeddings + cosine similarity, or a simple training set with scikit-learn (if Python version allows).

---

## 10. Room-to-Site Mapping

**Severity: Low (largely resolved)**

The live bot no longer depends on a hand-maintained Space-ID → name table: each
Google Chat event already carries the room's `displayName` (e.g. "4 Channelview"),
which `app/chat_live.extract_chat_event` records directly. **There is no
`app/room_mappings.py`** — the planned static dict was superseded by this live
display name plus `app/sites.py`, which canonicalizes any reference ("11",
"Windchase", "11 N&F Windchase" → one site). `docs/ROOM_MAPPINGS.md` is kept as a
reference of confirmed Space IDs.

Remaining gap: messages from a space with no `displayName` fall back to the raw
Space ID; `app/sites.py` still buckets them consistently but without a friendly
name until the display name is seen.

---

## 11. Attachment / Image Processing

**Severity: Low (largely resolved)**

`app/vision.py` analyzes image attachments via the Claude vision API (structured
output), and `app/chat_live.analyze_images` auto-reads *operational* photos
(reports, BOLs, deliveries, equipment, money) on ingest, storing day-report and
fuel figures. Enabled by `ANTHROPIC_API_KEY` + `OPS_VISION_ENABLED=1`.

Remaining gap (Phase 5): broaden receipt OCR (gallons/product extraction) and
equipment serial / price-sign reading robustness.

---

## 12. Veeder-Root / BOL Mismatch Not Automated

**✅ Resolved (Phase 5) — severity was Medium (business risk)**

The 4 Channelview site had a ~2,500 gallon discrepancy between the Veeder-Root tank reading and the BOL delivery receipt, originally caught manually during the Vault data review.

**Resolution:** `app/reconcile.py` reconciles `fuel_events`: it pairs BOL and
Veeder-Root readings per site and delivery date (and flags single records that
carry both) above `OPS_BOL_THRESHOLD` gallons (default 500). `app/vision.py` also
recomputes the discrepancy when one image shows both figures.

---

## 13. No Multi-Tenancy or Role-Based Access

**Severity: Low (current scale)**

All 22+ sites share a single bot, single database, and single dashboard. There is no per-site access control. A captain from Site 4 could theoretically view tasks from Site 24.

**Fix (Phase 3/4):** Add a user role system and per-site filtered views.

---

## Summary

| # | Limitation | Severity | Status |
|---|---|---|---|
| 1 | Python 3.14 compatibility | High (dev only) | Workaround: stdlib-only deps; use pyenv 3.12 locally |
| 2 | SQLite ephemeral on Cloud Run | — | ✅ Resolved — Firestore (`app/store.py`) is the live store |
| 3 | No live message ingestion | — | ✅ Resolved — `/chat/events` webhook + `chat_live` |
| 4 | No dashboard authentication | — | ✅ Resolved — `OPS_DASHBOARD_TOKEN` gate |
| 5 | Webhook token not verified | High | In progress — `app/chat_auth.py` (gated) |
| 6 | No proactive messaging | — | ✅ Resolved — `digests.JOBS` + Cloud Scheduler `/cron` |
| 7 | Single region | Low | Open |
| 8 | No monitoring | Low | Partial — `/healthz` + uptime check; no error-rate alerts |
| 9 | Basic classifier | Medium | Open |
| 10 | Room-to-site mapping | Low | Largely resolved — live `displayName` + `app/sites.py` |
| 11 | Attachment processing | Low | Largely resolved — `app/vision.py`; broaden OCR (Phase 5) |
| 12 | BOL/Veeder mismatch manual | — | ✅ Resolved — `app/reconcile.py` |
| 13 | No multi-tenancy / roles | Low | Open — scoped roles planned (see ROLES.md) |
