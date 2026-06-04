# nowforever-ops-bot 🛢️⛽

> **Jarvis-style AI operations bot for Now & Forever / Khawar & Sons gas stations**
> Monitors 22+ Google Chat rooms across Texas, classifies messages, creates tasks, and detects urgent issues in real time.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Company Info](#company-info)
- [Architecture](#architecture)
- [Features](#features)
- [Bot Commands](#bot-commands)
- [Room → Site Mappings](#room--site-mappings)
- [Data Snapshot](#data-snapshot)
- [High Priority Issues Detected](#high-priority-issues-detected)
- [Local Setup](#local-setup)
- [Google Cloud Deployment](#google-cloud-deployment)
- [Google Chat API Configuration](#google-chat-api-configuration)
- [Known Limitations](#known-limitations)
- [Roadmap](#roadmap)
- [Code Version History](#code-version-history)
- [Environment and Dependency Notes](#environment-and-dependency-notes)
- [Contributing](#contributing)

---

## Project Overview

This bot is a **"Jarvis"-style AI operations assistant** built for a family-run gas station company operating 22+ sites across Texas. It was born from a Google Vault export of 1,161+ messages across 21 Google Chat rooms.

The bot:
- Reads and classifies messages from Google Chat rooms
- Automatically creates and tracks operational tasks
- Detects urgent issues (no gas, power outages, equipment failures)
- Provides a local web dashboard for operations review
- Will eventually respond live inside Google Chat rooms

**Phase 2 goal:** Deploy to Google Cloud Run and configure the live Google Chat webhook so the bot can read and respond in real time.

---

## Company Info

| Field | Value |
|---|---|
| **Company Name** | Now & Forever / Khawar & Sons |
| **Business** | Gas stations (22+ sites) |
| **Region** | Texas, USA |
| **Google Cloud Project** | nfchatbot-498419 |
| **Service Account** | 908358949449-compute@developer.gserviceaccount.com |
| **Admin Email** | aayan@khawarsons.com |
| **Developer** | Aayan Farooqi ([@aayan-cpu](https://github.com/aayan-cpu)) |

---

## Architecture

```
Google Chat Rooms (22+)
        |
        v
Google Chat API (HTTP webhook)
        |
        v
Cloud Run Service (nowforever-chat-ops)
    +---+-------------------------------+
    |  app/server.py  (FastAPI)         |
    |  app/classifier.py                |
    |  app/task_manager.py              |
    |  app/alert_detector.py            |
    +---+-------------------------------+
        |
        v
   SQLite DB (ops_bot.sqlite3)
        |
        v
   Web Dashboard (http://host:8000/dashboard)
```

**Tech Stack:**
- Python 3.x (FastAPI, minimal deps — see Limitations)
- SQLite for task/message persistence
- Google Cloud Run (serverless deployment)
- Google Chat API (HTTP endpoint connection)
- Google Vault (historical data export source)

---

## Features

### Phase 1 (Complete)
- Parse Google Vault mbox exports to CSV
- Classify 1,161 messages across 21 rooms
- Identify 239 open tasks, 16 high-priority issues
- Local web dashboard at `/dashboard`
- Task list at `/tasks`
- Alerts view at `/alerts`

### Phase 2 (In Progress)
- Cloud Run deployment
- Google Chat API webhook integration
- Live bot responding in 2 test rooms

### Planned (Phases 3-5)
- Better NLP classifier with room/site context
- Daily digest messages sent to each room
- Missing report detection
- OCR for BOL/fuel delivery receipt scanning
- Veeder-Root vs BOL mismatch verification
- POS system integrations

---

## Bot Commands

Once the bot is live in a Google Chat room, tag it with:

```
@NowForever Ops Bot summary today
@NowForever Ops Bot alerts
@NowForever Ops Bot open tasks
@NowForever Ops Bot show 4 Channelview
@NowForever Ops Bot what stores need gas?
@NowForever Ops Bot close task 170
@NowForever Ops Bot assign task 170 @Admin 4
```

---

## Room to Site Mappings

| Space ID | Room Name |
|---|---|
| AAAAAyLVEg0 | 11 N&F Windchase |
| AAAAayKiMyg | 4 Channelview |
| AAAAhO6H0_Y | All Captains Chat |
| AAAA3s2JArA | 12 S Main Stafford |
| AAAAox_RoBo | 27 Fry |

Full mapping for all 22+ rooms is maintained in `app/room_mappings.py`.

---

## Data Snapshot

Parsed from Google Vault export (as of June 2026):

| Metric | Count |
|---|---|
| Total messages parsed | 1,161 |
| Attachments | 1,713 |
| Open tasks identified | 239 |
| High priority issues | 16 |
| Google Chat rooms covered | 21 |

---

## High Priority Issues Detected

These were flagged from the Vault data analysis:

| Site | Issue |
|---|---|
| **4 Channelview** | ATM power issue, Veeder/BOL mismatch (~2,500 gal), sewage smell |
| **12 S Main Stafford** | Urgent gas delivery needed, AC not working |
| **11 N&F Windchase** | NO GAS — regular & super shut off |
| **29 Westheimer** | 4-hour power outage |
| **18 Harwin & Gessener** | Machine #1 down, tickets not printing |
| **1 Coastal Mart** | Gas price/logo remote broken |
| **9 Bissonnet** | Ice machine down |
| **24 Galveston** | Gas delivery needed |

---

## Local Setup

### Prerequisites
- Python 3.x (see Limitations section for version notes)
- gcloud CLI installed
- Google Cloud project nfchatbot-498419 with billing enabled

### Run locally

```zsh
cd ~/Downloads/nowforever-chat-ops-v3
source .venv/bin/activate
python -m app.server
```

### Local endpoints

| URL | Description |
|---|---|
| http://127.0.0.1:8000/dashboard | Main ops dashboard |
| http://127.0.0.1:8000/tasks | All open tasks |
| http://127.0.0.1:8000/alerts | High-priority alerts |
| http://127.0.0.1:8000/chat/test | Webhook test endpoint |

---

## Google Cloud Deployment

### Project Info

| Field | Value |
|---|---|
| **Project ID** | nfchatbot-498419 |
| **Region** | us-central1 |
| **Service Name** | nowforever-chat-ops |
| **Service Account** | 908358949449-compute@developer.gserviceaccount.com |

### Deploy Command

```zsh
cd ~/Downloads/nowforever-chat-ops-v3

gcloud run deploy nowforever-chat-ops \
  --source . \
  --project nfchatbot-498419 \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars HOST=0.0.0.0,OPS_DB_PATH=data/ops_bot.sqlite3
```

### Known Deploy Errors and Fixes

| Error | Fix |
|---|---|
| command not found: gcloud | brew install google-cloud-sdk |
| no active account selected | gcloud auth login |
| storage.objects.get denied | Run the IAM fix below |

#### Fix storage permissions (run before deploy):

```zsh
gcloud projects add-iam-policy-binding nfchatbot-498419 \
  --member="serviceAccount:908358949449-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

#### Full fix + deploy (single command):

```zsh
gcloud projects add-iam-policy-binding nfchatbot-498419 \
  --member="serviceAccount:908358949449-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin" \
&& gcloud run deploy nowforever-chat-ops \
  --source . \
  --project nfchatbot-498419 \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars HOST=0.0.0.0,OPS_DB_PATH=data/ops_bot.sqlite3
```

---

## Google Chat API Configuration

After a successful Cloud Run deploy, configure the bot in Google Cloud Console:

1. Go to **Google Cloud Console > APIs & Services > Google Chat API > Configuration**
2. Fill in the following fields:

| Field | Value |
|---|---|
| **App name** | NowForever Ops Bot |
| **Description** | AI operations bot for Now & Forever gas station task tracking |
| **Connection type** | HTTP endpoint |
| **HTTP endpoint URL** | https://nowforever-chat-ops-908358949449.us-central1.run.app/chat/events |

3. Save the configuration.
4. Add the bot to test rooms:
   - **All Captains Chat** (Space ID: AAAAhO6H0_Y)
   - **4 Channelview** (Space ID: AAAAayKiMyg)

---

## Known Limitations

### Python 3.14 Compatibility

This project is developed on a MacBook Air running **Python 3.14**, which breaks several common packages due to C extension compilation failures:

| Package | Status on Python 3.14 |
|---|---|
| pydantic-core | Broken (C extension fails to compile) |
| pandas | Broken |
| uvicorn | Broken |
| fastapi (lite mode) | Works with workarounds |

**Mitigation:** All versions from `mvp-lite` onward (`v2`, `v3`) keep dependencies minimal and avoid pydantic, pandas, and uvicorn entirely.

> **Note for contributors:** If you are running Python 3.12 or earlier, you can use the full dependency set without restrictions.

### SQLite Persistence on Cloud Run

Cloud Run containers are **stateless and ephemeral**. The SQLite database stored at `data/ops_bot.sqlite3` will be wiped whenever a new container instance starts or a new deployment is made.

**Current workaround:** Point `OPS_DB_PATH` to a Cloud Storage FUSE mount or persistent volume.

**Long-term fix (Phase 3):** Migrate to Cloud Firestore or Cloud SQL.

### Historical Data Only (No Live Ingestion Yet)

The current version is seeded entirely from the **Google Vault historical export** (mbox format). The bot does not yet ingest live messages from Google Chat. This is the primary goal of Phase 2.

### No Dashboard Authentication

The `/dashboard`, `/tasks`, and `/alerts` endpoints are publicly accessible when deployed with `--allow-unauthenticated`. Do not expose sensitive operational data on these endpoints until proper authentication (e.g., IAP or token-based auth) is added.

### Google Chat Webhook Token Verification Not Implemented

Google Chat sends a bearer token in webhook requests that should be verified. The current `/chat/events` handler accepts all incoming requests without verification. This must be fixed before production use.

### Single Region, No Redundancy

The service is deployed to `us-central1` only. There is no failover, load balancing, or multi-region setup.

### No Alerting or Monitoring

There is no uptime monitoring, error alerting, or logging dashboard configured yet. Cloud Logging is available via GCP console, but no automated alerts are set up.

---

## Roadmap

### Phase 1 — Complete
Parse Google Vault export, build local dashboard, classify 1,161 messages across 21 rooms, identify 239 open tasks and 16 high-priority issues.

### Phase 2 — In Progress
Deploy to Google Cloud Run. Configure Google Chat API HTTP endpoint. Test live bot in All Captains Chat and 4 Channelview.

**Phase 2 checklist:**
- [x] gcloud installed
- [x] gcloud auth login completed
- [x] Fix storage IAM permissions
- [x] Cloud Run deploy succeeds → https://nowforever-chat-ops-908358949449.us-central1.run.app
- [x] Copy Cloud Run URL
- [ ] Google Chat API HTTP endpoint configured (manual step in Cloud Console)
- [ ] Bot added to All Captains Chat
- [ ] Bot added to 4 Channelview
- [ ] Test bot commands in a live room

### Phase 3 — Planned
Improved message classifier with room and site context awareness. Live message persistence using Firestore or Cloud SQL. Room-to-site mapping for all 22+ locations.

### Phase 4 — Planned
Auto-task creation from incoming messages. Daily digest messages sent to each room. Alerts when reports are missing or overdue.

### Phase 5 — Planned
OCR scanning for BOL (Bill of Lading) and fuel delivery receipts. Automated Veeder-Root vs BOL volume mismatch detection. POS system integrations for sales/inventory data.

---

## Code Version History

| Package | Status | Notes |
|---|---|---|
| gasstation-telegram-bot.zip | Done | Basic bot with SQLite |
| gasstation-ai-telegram-bot.zip | Done | Added OpenAI /ask command |
| vault_parser_and_parsed_sample.zip | Done | mbox to CSV parser |
| vault_full_review_outputs.zip | Done | All 21 rooms fully analyzed |
| nowforever-chat-ops-mvp.zip | Failed | Python 3.14 dep issues |
| nowforever-chat-ops-mvp-lite.zip | Done | No heavy deps |
| nowforever-chat-ops-v2.zip | Done | Local dashboard added |
| nowforever-chat-ops-v3.zip | Done | Google Chat live webhook |

---

## Environment and Dependency Notes

```
OS:       macOS (MacBook Air)
Shell:    zsh
Python:   3.14 (system) — use pyenv to install 3.12 if needed
Cloud:    Google Cloud SDK (gcloud)
DB:       SQLite (local), Firestore (planned)
```

### Minimal requirements for v3

```
# Intentionally no pydantic, no pandas, no uvicorn
# Uses Python standard library + lightweight HTTP handling
```

Always activate the virtual environment before running:

```zsh
source .venv/bin/activate
```

---

## Contributing

This is a private family business operations tool. If you are contributing as part of the Khawar & Sons team:

1. Clone the repo
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes and test locally
4. Open a Pull Request against `main`
5. Tag Aayan for review

**Do not commit:**
- SQLite database files (`*.sqlite3`, `*.db`)
- Any `.env` files containing API keys or credentials
- Google Vault export data (mbox files, CSV files with message content)
- Service account JSON key files
- Any file containing real employee names, phone numbers, or addresses

---

*Built with care for Now & Forever / Khawar & Sons — keeping 22+ Texas gas stations running smoothly.*
