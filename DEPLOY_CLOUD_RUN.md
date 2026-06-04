# Deploy NowForever Chat Ops v3 to Cloud Run

## What v3 adds

- `POST /chat/events` for Google Chat HTTP events
- `POST /google-chat/events` alias
- `GET/POST /chat/test` for local testing
- live message classification into the same SQLite database
- bot replies for summaries, tasks, alerts, site lookups, close/assign commands

## Local test first

```bash
cd ~/Downloads/nowforever-chat-ops-v3
python3 -m venv .venv
source .venv/bin/activate
python -m app.server
```

Open:

```text
http://127.0.0.1:8000/dashboard
http://127.0.0.1:8000/chat/test
```

## Deploy to Cloud Run

Install/use the Google Cloud CLI, then from this folder:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud run deploy nowforever-chat-ops-v3 \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars HOST=0.0.0.0,OPS_DB_PATH=data/ops_bot.sqlite3
```

When deploy finishes, Cloud Run prints a service URL like:

```text
https://nowforever-chat-ops-v3-xxxxx-uc.a.run.app
```

Your Google Chat endpoint will be:

```text
https://YOUR-CLOUD-RUN-URL/chat/events
```

## Configure Google Chat API

In Google Cloud Console:

1. Open Google Chat API.
2. Go to Configuration.
3. App name: `NowForever Ops Bot`
4. Functionality:
   - Receive 1:1 messages
   - Join spaces and group conversations
5. Connection settings:
   - HTTP endpoint URL: `https://YOUR-CLOUD-RUN-URL/chat/events`
6. Visibility:
   - limit to your Workspace/domain while testing
7. Save.

## Test in Google Chat

Add bot to one test room only first, ideally:

- All Captains Chat
- 4 Channelview

Try:

```text
@NowForever Ops Bot summary today
@NowForever Ops Bot alerts
@NowForever Ops Bot open tasks
@NowForever Ops Bot show 4 Channelview
@NowForever Ops Bot close task 170
@NowForever Ops Bot assign task 170 @Admin 4
```

## Safety

v3 replies only when:

- mentioned / command-ish
- or a high-priority issue is detected

This prevents it from spamming every site room.
