# Contributing to NowForever Ops Bot

This is an internal operations tool for Now & Forever / Khawar & Sons. Contributions are limited to the engineering team.

---

## Development Setup

### 1. Clone the repo

```zsh
git clone https://github.com/aayan-cpu/nowforever-ops-bot.git
cd nowforever-ops-bot
```

### 2. Set up a virtual environment

If you are on Python 3.12 or earlier (recommended):

```zsh
python3 -m venv .venv
source .venv/bin/activate
```

If you are on Python 3.14 (the development machine), use pyenv:

```zsh
# Install pyenv if needed
brew install pyenv

# Install Python 3.12
pyenv install 3.12.4
pyenv local 3.12.4

# Create venv with 3.12
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```zsh
pip install -r requirements.txt
```

### 4. Run locally

```zsh
python -m app.server
```

Then open http://127.0.0.1:8000/dashboard in your browser.

---

## Branch Naming Conventions

| Type | Pattern | Example |
|---|---|---|
| Feature | `feature/description` | `feature/add-firestore` |
| Bug fix | `fix/description` | `fix/webhook-token-check` |
| Documentation | `docs/description` | `docs/update-room-mappings` |
| Phase milestone | `phase/number` | `phase/3` |

---

## Commit Message Guidelines

Use the following prefixes:

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation change
- `refactor:` — code restructure, no behavior change
- `chore:` — dependency updates, config changes
- `deploy:` — deployment-related changes

Examples:
```
feat: add /chat/events webhook handler
fix: handle empty message text in classifier
docs: add room mapping for Bissonnet
chore: update gcloud deploy command in README
```

---

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes
3. Test locally: `python -m app.server`
4. Open a PR against `main`
5. Tag `@aayan-cpu` for review
6. PRs require at least 1 approval before merging

---

## What NOT to Commit

Never commit:

- `*.sqlite3` or `*.db` files (database)
- `.env` files (API keys, secrets)
- Google Vault export data (mbox, CSV files with message content)
- Service account JSON key files (`*-sa-key.json`, `credentials.json`)
- Any file with real employee names, phone numbers, or addresses
- `__pycache__/` directories
- `.venv/` virtual environment directory

These are already covered by `.gitignore`, but double-check before committing.

---

## Testing

There is no automated test suite yet (Phase 3 milestone). For now, test manually:

1. Start the server locally
2. Open http://127.0.0.1:8000/dashboard — should show tasks and stats
3. Open http://127.0.0.1:8000/alerts — should show high-priority issues
4. POST to http://127.0.0.1:8000/chat/test with a test payload

Example test payload:

```json
{
  "type": "MESSAGE",
  "space": { "name": "spaces/AAAAayKiMyg" },
  "message": { "text": "alerts" }
}
```

---

## Architecture Reference

See the main [README.md](../README.md) for the full architecture diagram and project overview.

For deployment instructions, see [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md).

For Google Chat API setup, see [docs/CHAT_API_SETUP.md](./docs/CHAT_API_SETUP.md).

---

## Contact

Project owner: **Aayan Farooqi** — aayan@khawarsons.com  
GitHub: [@aayan-cpu](https://github.com/aayan-cpu)
