# Roles & Access

## Current model

| Role | Who | Powers |
|---|---|---|
| **Owner** | `OPS_OWNER_EMAIL` (aayan@khawarsons.com) | Everything. Always an admin. **No env/role change can place anyone above the owner.** |
| **Admin** | `OPS_ADMIN_EMAILS` (owner + admin1 + admin2@khawarsons.com) | Full: run commands, close/assign tasks, AI actions, receive the daily summary, set their own preferences. |
| **Everyone else** | any khawarsons.com user with bot access | Read-only conversational AI + can set their own preferences. No task mutations. |

Editable without a code change:

```bash
gcloud run services update nowforever-chat-ops --region us-central1 \
  --project nfchatbot-498419 \
  --update-env-vars "OPS_ADMIN_EMAILS=aayan@khawarsons.com,admin1@khawarsons.com,admin2@khawarsons.com,newperson@khawarsons.com"
```

The owner is always re-added in code, so you can't accidentally remove yourself or
be outranked.

## Per-user preferences (self-service "modify the bot for me")

Anyone can tell the bot, in chat, how to help them — e.g. "from now on focus on
fuel issues for me", "only show me my region", "keep my summary to 5 items". The
bot saves it (`remember_preference` tool → Firestore `preferences/<email>`) and
honors it in future chats and in their personalized daily summary. This is
behavior/preference customization — not new code features.

## Daily summary delivery

The 9:15 PM summary is generated **per admin**, tailored to each person's saved
preferences, and DM'd to them. The bot learns each admin's DM space the first
time that admin messages it (stored in `admin_dms`). So a new admin should DM the
bot once ("hi") to start receiving summaries.

## Planned: scoped "Discord-style" roles (not built yet)

Below admin, position-based roles with only the access they need, e.g.:

| Example role | Scope |
|---|---|
| Regional manager | Read + act on tasks for their stores only |
| Fuel manager | Fuel/BOL/Veeder items across all stores |
| Reports admin | Daily-report tracking + reminders |

Implementation sketch: a `roles` map (email → role) in Firestore/env, each role
granting a set of permissions + a data scope (which stores). The brain and command
handlers check the permission/scope before acting. Owner stays above all roles.
