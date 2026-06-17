# Known Limitations

This document comprehensively covers all known technical constraints, risks, and limitations of the NowForever Ops Bot as of June 2026.

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

## 2. SQLite Ephemeral Storage on Cloud Run — RESOLVED

**Severity: Resolved (was High)**

This is fixed: live persistence is **Cloud Firestore via the REST API**
(`app/store.py`). Firestore is the source of truth for messages and tasks in the
deployed bot, so the stateless-container problem below no longer affects live data.

SQLite (`app/database.py`, default `data/ops_bot.sqlite3`) is now used **only** for
the offline Google Vault ingest on a developer machine — it is never the live store.
Its ephemerality on Cloud Run is therefore moot; `OPS_DB_PATH` only points the
offline ingest at a local file and has no effect on live persistence.

Historical note — the original concern: Cloud Run containers are stateless, so a
container-local SQLite file is lost on scale-out, redeploy, or health-check
replacement. That is exactly why the live path moved to Firestore.

---

## 3. Historical Data Only — No Live Ingestion Yet

**Severity: High (Phase 2 target)**

The current system is seeded from a **Google Vault mbox export** of historical messages. It does not receive or process live messages from Google Chat rooms.

**Impact:** The dashboard and alerts are based on messages up to the date of the Vault export. New operational issues happening in rooms are not captured.

**Fix in progress:** Phase 2 deploys the Cloud Run webhook endpoint and configures Google Chat API to forward messages in real time.

---

## 4. No Dashboard Authentication

**Severity: High (security risk)**

The following endpoints are publicly accessible when deployed with `--allow-unauthenticated`:
- `/dashboard`
- `/tasks`
- `/alerts`
- `/chat/test`

Any person with the Cloud Run URL can view all operational data including site issues, task statuses, and message summaries.

**Short-term fix:** Add a simple API key header check:
```python
API_KEY = os.environ.get("API_KEY", "")
if request.headers.get("X-API-Key") != API_KEY:
    return Response("Unauthorized", status=401)
```

**Long-term fix:** Use Google Cloud IAP (Identity-Aware Proxy) to gate the dashboard behind Google login.

---

## 5. Webhook Token Not Verified

**Severity: High (security risk)**

Google Chat sends a bearer token in each webhook request for authenticity verification. The current `/chat/events` handler does not verify this token, meaning:
- Any HTTP client can POST to the endpoint and trigger bot responses
- The bot could be spoofed or spammed

**Fix:** Add token verification to `app/server.py`. The expected token is shown in the Google Chat API Configuration page.

---

## 6. No Proactive Messaging

**Severity: Medium**

The bot can only respond to messages it receives via the webhook. It cannot:
- Send daily digest messages to rooms
- Alert captains when a task is overdue
- Notify rooms when a missing report is detected

These require calling the Google Chat REST API with OAuth 2.0 credentials, not just the webhook.

**Fix (Phase 4):** Set up a Cloud Scheduler job to trigger a Cloud Run endpoint daily, which then calls the Chat API to send digests.

---

## 7. Single Region Deployment

**Severity: Low (availability risk)**

The service is deployed to `us-central1` only. If that GCP region experiences an outage, the bot will be unavailable.

**Fix:** Add a secondary region (`us-east1`) and put a Global Load Balancer in front. Low priority given the bot is operational, not customer-facing.

---

## 8. No Uptime Monitoring or Alerting

**Severity: Medium**

There is no:
- Uptime check on the Cloud Run service
- PagerDuty / alerting if the service goes down
- Error rate monitoring
- Latency tracking

**Fix:** Set up a Google Cloud Monitoring uptime check on the `/alerts` endpoint. Configure an alerting policy to send email to `aayan@khawarsons.com` if the service is down for more than 5 minutes.

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

## 10. Room-to-Site Mapping Is Incomplete

**Severity: Medium**

Only 5 of the 22+ rooms are mapped in the current code:

| Space ID | Room Name |
|---|---|
| AAAAAyLVEg0 | 11 N&F Windchase |
| AAAAayKiMyg | 4 Channelview |
| AAAAhO6H0_Y | All Captains Chat |
| AAAA3s2JArA | 12 S Main Stafford |
| AAAAox_RoBo | 27 Fry |

The live bot reads each room's display name directly from the Chat event
(`space.displayName`), so most rooms surface a real name without any hand-kept
mapping. Events that arrive without a display name still fall back to the Space ID.

**Fix (Phase 3):** Confirm the remaining Space IDs (see [ROOM_MAPPINGS.md](./ROOM_MAPPINGS.md))
and seed any new number/location aliases into `app/sites.py`, the canonical site
resolver. There is no `app/room_mappings.py`.

---

## 11. Attachment / Image Processing — IMPLEMENTED

**Severity: Resolved (was Medium)**

Live image understanding is implemented in `app/vision.py` (Claude Messages REST
API, no SDK), invoked from `app/chat_live.py:analyze_images` for operational
photos. It extracts BOL gallons, Veeder-Root readings, day-report figures, and
per-grade fuel line items, and recomputes the BOL-vs-Veeder discrepancy in Python.
Gated by `OPS_VISION_ENABLED` + `ANTHROPIC_API_KEY` so it stays off until opted in.

Remaining (Phase 5): equipment serial-number extraction and price-sign reading are
not yet specialized.

---

## 12. Veeder-Root / BOL Mismatch Not Automated

**Severity: Medium (business risk)**

The 4 Channelview site has a ~2,500 gallon discrepancy between the Veeder-Root tank reading and the BOL delivery receipt. This was caught manually during the Vault data review.

**Fix (Phase 5):** Build an automated reconciliation module that:
1. Parses BOL PDFs/images with OCR
2. Fetches Veeder-Root readings (via email reports or direct API if available)
3. Flags discrepancies above a configurable threshold (e.g., 500 gallons)

---

## 13. No Multi-Tenancy or Role-Based Access

**Severity: Low (current scale)**

All 22+ sites share a single bot, single database, and single dashboard. There is no per-site access control. A captain from Site 4 could theoretically view tasks from Site 24.

**Fix (Phase 3/4):** Add a user role system and per-site filtered views.

---

## Summary

| # | Limitation | Severity | Phase to Fix |
|---|---|---|---|
| 1 | Python 3.14 compatibility | High | Use pyenv locally |
| 2 | SQLite ephemeral on Cloud Run | Resolved | Firestore live (`app/store.py`) |
| 3 | No live message ingestion | High | Phase 2 |
| 4 | No dashboard authentication | High | Phase 2/3 |
| 5 | Webhook token not verified | High | Phase 2 |
| 6 | No proactive messaging | Medium | Phase 4 |
| 7 | Single region | Low | Phase 4 |
| 8 | No monitoring | Medium | Phase 3 |
| 9 | Basic classifier | Medium | Phase 3 |
| 10 | Incomplete room mapping | Medium | Phase 3 (`app/sites.py`) |
| 11 | Attachment processing | Resolved | `app/vision.py` |
| 12 | BOL/Veeder mismatch manual | Medium | Phase 5 |
| 13 | No multi-tenancy | Low | Phase 3/4 |
