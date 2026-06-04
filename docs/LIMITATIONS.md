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

## 2. SQLite Ephemeral Storage on Cloud Run

**Severity: High (production impact)**

Cloud Run is a stateless serverless platform. Containers are spun up and torn down automatically. The SQLite database stored at `data/ops_bot.sqlite3` is part of the container's writable layer and will be lost when:
- A new container instance starts (scale-out)
- A new deployment is made
- The container is replaced due to a health check failure

**Current workaround:** The `OPS_DB_PATH` environment variable can be set to a path on a mounted Cloud Storage FUSE volume. This requires additional setup.

**Long-term fix (Phase 3):** Migrate to a managed database:
- **Cloud Firestore** (recommended) — serverless, scales automatically, no ops overhead
- **Cloud SQL (PostgreSQL)** — if relational schema is needed
- **Cloud Spanner** — overkill for this use case

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

Messages from unmapped rooms are stored with the Space ID as the site name, making them harder to query.

**Fix (Phase 3):** Complete the `ROOM_MAPPINGS` dictionary in `app/room_mappings.py` for all 22+ rooms. See [ROOM_MAPPINGS.md](./ROOM_MAPPINGS.md) for the full list.

---

## 11. No Attachment / Image Processing

**Severity: Medium**

The Vault export contained 1,713 attachments (photos of BOLs, equipment issues, fuel receipts). The current system ignores all attachments.

**Fix (Phase 5):** Add OCR processing using Google Cloud Vision API or Tesseract to extract:
- BOL (Bill of Lading) delivery quantities for Veeder-Root comparison
- Equipment serial numbers from photos
- Price sign readings

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
| 2 | SQLite ephemeral on Cloud Run | High | Phase 3 (Firestore) |
| 3 | No live message ingestion | High | Phase 2 |
| 4 | No dashboard authentication | High | Phase 2/3 |
| 5 | Webhook token not verified | High | Phase 2 |
| 6 | No proactive messaging | Medium | Phase 4 |
| 7 | Single region | Low | Phase 4 |
| 8 | No monitoring | Medium | Phase 3 |
| 9 | Basic classifier | Medium | Phase 3 |
| 10 | Incomplete room mapping | Medium | Phase 3 |
| 11 | No attachment processing | Medium | Phase 5 |
| 12 | BOL/Veeder mismatch manual | Medium | Phase 5 |
| 13 | No multi-tenancy | Low | Phase 3/4 |
