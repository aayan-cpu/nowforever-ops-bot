# Google Chat API Setup Guide

This document covers configuring the NowForever Ops Bot as a Google Chat app after the Cloud Run service is deployed.

---

## Prerequisites

- Cloud Run service deployed and URL available (see [DEPLOYMENT.md](./DEPLOYMENT.md))
- Access to Google Cloud Console for project `nfchatbot-498419`
- Logged in as `aayan@khawarsons.com`

---

## Step 1: Enable the Google Chat API

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Select project **nfchatbot-498419**
3. Navigate to **APIs & Services > Library**
4. Search for "Google Chat API"
5. Click **Enable** (if not already enabled)

---

## Step 2: Configure the Chat App

1. Go to **APIs & Services > Google Chat API > Configuration**
2. Fill in the following fields:

| Field | Value |
|---|---|
| **App name** | NowForever Ops Bot |
| **Avatar URL** | (optional — use any icon URL) |
| **Description** | AI operations bot for Now & Forever gas station task tracking |
| **Enable interactivity** | On |
| **Functionality** | Check both: Receive 1:1 messages, Join spaces and group conversations |
| **Connection settings** | HTTP endpoint URL |
| **HTTP endpoint URL** | https://YOUR-CLOUD-RUN-URL/chat/events |
| **Slash commands** | (leave empty for now) |
| **App home** | (leave empty for now) |

3. Under **Visibility**, set to **Your domain** (khawarsons.com)
4. Click **Save**

---

## Step 3: Note the App ID

After saving, Google will display an **App ID** (a long number). Save this — you will need it to add the bot to rooms programmatically in Phase 3.

---

## Step 4: Add the Bot to Test Rooms

### Option A: Manual (via Google Chat)

1. Open Google Chat at [chat.google.com](https://chat.google.com)
2. Open the room **All Captains Chat**
3. Click the room name at the top > **Apps & integrations** > **Add apps**
4. Search for "NowForever Ops Bot"
5. Click **Add**
6. Repeat for **4 Channelview**

### Option B: Via Admin Console

1. Go to [admin.google.com](https://admin.google.com)
2. Navigate to **Apps > Google Workspace > Google Chat**
3. Add the bot to specific rooms from there

---

## Step 5: Test the Bot

In either test room, type:

```
@NowForever Ops Bot alerts
```

The bot should respond with the current high-priority alert list.

If there is no response, check:
1. Cloud Run logs for incoming webhook requests
2. That the HTTP endpoint URL in the Chat API config exactly matches your Cloud Run URL
3. That the Cloud Run service is running (`gcloud run services describe nowforever-chat-ops`)

---

## Webhook Event Payload

Google Chat sends POST requests to your endpoint with JSON payloads. The main event types are:

| Type | Description |
|---|---|
| `MESSAGE` | A user sent a message in a room the bot is in |
| `ADDED_TO_SPACE` | Bot was added to a room |
| `REMOVED_FROM_SPACE` | Bot was removed from a room |
| `CARD_CLICKED` | A user clicked an interactive card element |

Example MESSAGE payload:

```json
{
  "type": "MESSAGE",
  "eventTime": "2026-06-04T12:00:00Z",
  "space": {
    "name": "spaces/AAAAayKiMyg",
    "displayName": "4 Channelview"
  },
  "message": {
    "name": "spaces/AAAAayKiMyg/messages/abc123",
    "sender": { "displayName": "Captain Ahmed" },
    "text": "@NowForever Ops Bot alerts"
  }
}
```

---

## Current Bot Command Handlers

| Command | Handler | Response |
|---|---|---|
| `summary today` | summarize_today() | Count of messages and tasks for today |
| `alerts` | get_alerts() | List of active high-priority issues |
| `open tasks` | get_open_tasks() | All unresolved tasks |
| `show [site]` | get_site_tasks(site) | Tasks for a specific site |
| `what stores need gas?` | get_gas_needed() | Sites with gas delivery issues |
| `close task [id]` | close_task(id) | Mark a task as resolved |
| `assign task [id] @[name]` | assign_task(id, name) | Assign a task to someone |

---

## Known Issues

### Webhook Token Not Verified

Google Chat includes a bearer token in each webhook request for verification. The current implementation does not verify this token. Before going to production, add token verification to `app/server.py`:

```python
# In your /chat/events handler:
auth_header = request.headers.get("Authorization")
if auth_header != f"Bearer {EXPECTED_TOKEN}":
    return {"error": "unauthorized"}, 401
```

The expected token is shown in the Google Chat API > Configuration page.

### Bot Cannot Initiate Messages

The current implementation only responds to incoming messages. Proactive messaging (e.g., sending daily digests) requires calling the Google Chat REST API with proper OAuth credentials. This is planned for Phase 4.

---

## Rooms to Configure (Phase 2 Target)

| Space ID | Room Name | Priority |
|---|---|---|
| AAAAhO6H0_Y | All Captains Chat | High — test first |
| AAAAayKiMyg | 4 Channelview | High — test second |
| AAAAAyLVEg0 | 11 N&F Windchase | Phase 3 |
| AAAA3s2JArA | 12 S Main Stafford | Phase 3 |
| AAAAox_RoBo | 27 Fry | Phase 3 |
