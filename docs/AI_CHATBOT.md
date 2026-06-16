# Conversational AI Brain

Makes the bot an actual assistant, not a fixed-command machine. When a user
DMs or @mentions it in plain English, the bot pulls a live ops snapshot from
Firestore (open tasks, high-priority alerts, that store's recent activity) and
lets **Claude** answer naturally — e.g. "what needs attention today?", "did
site 18's printer get fixed?", "which stores still need gas?".

## How replies are routed (`app/chat_live.py`)

1. **Exact commands stay deterministic** (free, instant, reliable):
   `summary`, `tasks`, `alerts`, `show <room>`, `close task <id>`, `assign task <id> <name>`.
2. **Anything else**, when the bot is addressed, goes to the **Claude brain**
   (`app/brain.py`) for a natural-language answer.
3. If no API key is set, it falls back to the old keyword acknowledgement — so
   the bot still works, just not conversationally.

## The key (paid, separate Anthropic account)

Uses the **same `ANTHROPIC_API_KEY`** as the image feature — one key powers both.
It's a **separate Anthropic account** with its own billing (not any coding
session). Create it at <https://console.anthropic.com>.

- Model: `claude-opus-4-8` (best). Swap to cheaper Sonnet via `OPS_BRAIN_MODEL=claude-sonnet-4-6`.
- The system persona is sent as a cached block to keep cost down.
- Est. cost at this volume (only runs when addressed): **~$10–30/month** on Opus,
  roughly 3–5× less on Sonnet.

## Enable (Cloud Run)

```bash
printf '%s' 'sk-ant-...' | gcloud secrets create anthropic-api-key \
  --data-file=- --project nfchatbot-498419
gcloud secrets add-iam-policy-binding anthropic-api-key \
  --member="serviceAccount:908358949449-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" --project nfchatbot-498419

gcloud run services update nowforever-chat-ops --region us-central1 \
  --project nfchatbot-498419 \
  --update-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest
```

## Tunables

| Env var | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Claude key (separate account). Unset ⇒ keyword-only fallback. |
| `OPS_BRAIN_MODEL` | `claude-opus-4-8` | Chatbot model. |

## Possible next step

Right now the brain answers questions (read-only) and points users to
`close task`/`assign task` for actions. A follow-up could give it tool-use so it
can close/assign tasks directly from natural language ("close the printer issue
at site 18").
