# Deployment Guide

This document covers everything needed to deploy the NowForever Ops Bot to Google Cloud Run.

---

## Prerequisites

- Google Cloud SDK (gcloud) installed
- Authenticated with `gcloud auth login` as `aayan@khawarsons.com`
- Google Cloud project `nfchatbot-498419` with billing enabled
- Source code at `~/Downloads/nowforever-chat-ops-v3`

---

## Step 1: Fix Storage IAM Permissions

Before deploying, grant the Compute Engine service account storage access. This is required because Cloud Run source-based deploys use Cloud Build, which needs to write to Cloud Storage staging buckets.

```zsh
gcloud projects add-iam-policy-binding nfchatbot-498419 \
  --member="serviceAccount:988358949449-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

You only need to run this once per project.

---

## Step 2: Deploy to Cloud Run

```zsh
cd ~/Downloads/nowforever-chat-ops-v3

gcloud run deploy nowforever-chat-ops \
  --source . \
  --project nfchatbot-498419 \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars HOST=0.0.0.0,OPS_DB_PATH=data/ops_bot.sqlite3
```

This command:
1. Uploads source code to Cloud Storage
2. Triggers a Cloud Build to containerize the app
3. Deploys the container to Cloud Run
4. Returns a public HTTPS URL

Estimated build and deploy time: 3–7 minutes.

---

## Step 3: Copy the Cloud Run URL

After a successful deploy, the terminal will print something like:

```
Service URL: https://nowforever-chat-ops-xxxxxxxxxx-uc.a.run.app
```

**Save this URL.** You will need it to configure the Google Chat API endpoint.

---

## Step 4: Verify the Deploy

Test that the service is running:

```zsh
curl https://YOUR-CLOUD-RUN-URL/alerts
```

You should get a JSON response with the current alert list.

---

## Environment Variables

| Variable | Value | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind to all interfaces (required for Cloud Run) |
| `OPS_DB_PATH` | `data/ops_bot.sqlite3` | Path to the SQLite database |

---

## Known Errors and Fixes

### Error: command not found: gcloud

```zsh
brew install google-cloud-sdk
```

### Error: no active account selected

```zsh
gcloud auth login
```

Then select `aayan@khawarsons.com` in the browser.

### Error: storage.objects.get denied

Run the IAM fix from Step 1 above.

### Error: Cloud Build quota exceeded

Wait a few minutes and retry. Cloud Build has a free quota of 120 build-minutes/day.

---

## Re-deploying After Code Changes

```zsh
cd ~/Downloads/nowforever-chat-ops-v3
gcloud run deploy nowforever-chat-ops \
  --source . \
  --project nfchatbot-498419 \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars HOST=0.0.0.0,OPS_DB_PATH=data/ops_bot.sqlite3
```

The service URL stays the same across re-deploys.

---

## Checking Logs

```zsh
gcloud run services logs read nowforever-chat-ops \
  --project nfchatbot-498419 \
  --region us-central1
```

Or view logs in the Google Cloud Console under Cloud Run > nowforever-chat-ops > Logs.

---

## Important Limitations

- **SQLite is ephemeral on Cloud Run.** The database resets on each new container instance. See the Known Limitations section in the main README for workarounds.
- **The service is publicly accessible.** No authentication is currently configured on the dashboard and API endpoints.
- **Single region only.** No redundancy or failover.

---

## Next Step After Deployment

Once deployed, proceed to [CHAT_API_SETUP.md](./CHAT_API_SETUP.md) to connect the bot to Google Chat.
