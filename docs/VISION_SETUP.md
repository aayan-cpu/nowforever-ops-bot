# AI Image Reading (Photos in Chat)

The bot can read photos posted in station chats — Bills of Lading (BOL), Veeder-Root
tank readings, fuel receipts, price signs — and extract structured data with AI.
It uses **Claude vision** (Anthropic Messages API).

## Important: the API key is a SEPARATE Anthropic account

The photo feature is powered by an **Anthropic (Claude) API key**. This key:

- Belongs to a **separate Anthropic account** with its own billing — **not** tied to
  any Claude Code / coding-assistant session used to build this bot.
- Is the **only** thing that makes the bot depend on an outside paid service. Every
  other feature (chat replies, tasks, dashboard, alerts, classification) is pure Python
  and has **no** AI dependency.
- Lives in the `ANTHROPIC_API_KEY` environment variable / Cloud Run secret. If it is
  **not set**, image reading is silently disabled and the rest of the bot is unaffected.

Create the key at <https://console.anthropic.com> (Settings → API Keys) on the account
that will own the billing for photo analysis.

## Cost

Roughly **1–3¢ per image** on `claude-opus-4-8`. At ~8 images/day that's about
**$2–7/month**. Model is configurable via `OPS_VISION_MODEL`.

## Enable it (Cloud Run)

Store the key as a secret and point the service at it:

```bash
# 1. Put the key in Secret Manager
printf '%s' 'sk-ant-...' | gcloud secrets create anthropic-api-key \
  --data-file=- --project nfchatbot-498419
gcloud secrets add-iam-policy-binding anthropic-api-key \
  --member="serviceAccount:908358949449-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" --project nfchatbot-498419

# 2. Wire it into the service as ANTHROPIC_API_KEY
gcloud run services update nowforever-chat-ops --region us-central1 \
  --project nfchatbot-498419 \
  --update-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest
```

## How it works

- `app/vision.py` — calls the Claude Messages REST API (no SDK; the `anthropic`
  package needs deps that don't build on the dev machine's Python 3.14). Returns
  structured fields (doc type, gallons, dollar amounts, prices) and **recomputes the
  BOL-vs-Veeder gallon discrepancy in Python** (we don't trust model arithmetic).
  A difference above `OPS_BOL_THRESHOLD` (default 500 gal) flags the message for review.
- `app/chat_media.py` — downloads the image bytes from Chat. In Cloud Run it mints a
  `chat.bot` token by impersonating `chat-bot-poster` via IAM `generateAccessToken`
  (the runtime SA has `roles/iam.serviceAccountTokenCreator` on it) — **no private key
  is stored in the container**. Locally it falls back to signing with `OPS_SA_KEY`.
- `app/chat_live.py` (`analyze_images`) — runs on every ingested message that has image
  attachments; best-effort (never breaks ingest). A flagged image becomes a high-priority
  `bol_veeder_review` task, and the AI summary is appended to the bot's reply.

## Test locally

```bash
ANTHROPIC_API_KEY=sk-ant-... python scripts/test_vision.py path/to/bol.jpg
```

## Tunables

| Env var | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Claude key (separate account). Shared with the chatbot brain. |
| `OPS_VISION_ENABLED` | `false` | Must be `true` to turn image analysis on. Without it, images stay off even when the key is set (so enabling the chatbot doesn't auto-bill for images). |
| `OPS_VISION_MODEL` | `claude-opus-4-8` | Vision model. |
| `OPS_BOL_THRESHOLD` | `500` | Gallons of BOL-vs-Veeder difference that flags a review. |
