# Kin — a personal relationship manager (self-hosted CRM for friends & family)

Kin helps you remember the people in your life: birthdays, how you met, what's going on with
them, and when you last actually talked. It's built to be gentle and low-friction rather than
another guilt-inducing task list — nudges are soft, everything AI or Instagram touches waits for
your approval, and quick-capture journaling is the core interaction.

## Features

- **Web UI with login** — simple email/password accounts, session-based auth, first-run setup wizard.
- **Immich integration** — link a person to a recognized face in your [Immich](https://immich.app)
  library to pull in their photos automatically, plus an **"On this day"** widget on the dashboard
  powered by Immich's memories API.
- **Birthdays & notable dates** — track birthdays (year optional) plus any number of custom notable
  dates per person (anniversaries, kids' birthdays, etc.), surfaced on the dashboard as they approach.
- **Journal-style logging** — a single quick-capture text box updates a person's profile/timeline
  seamlessly. No rigid fields required.
- **Cross-tagging** — tag multiple people in one journal entry (e.g. a group hangout) and it shows
  up on *everyone's* timeline automatically.
- **Attach photos to entries** — browse and attach Immich photos (by date, or by a linked person)
  directly onto a journal entry/event.
- **AI assist (optional, bring-your-own-key)** — works with OpenAI or any OpenAI-compatible endpoint
  (including a local Ollama server). Extracts suggested tags/notable dates from journal entries,
  writes profile summaries, suggests conversation starters, and drafts birthday messages. Every AI
  output is a *suggestion* you explicitly approve — nothing is written to a profile automatically.
- **Instagram check-ins (optional, unofficial, off by default)** — periodically checks for new posts
  from people you follow and queues them for review. See the big warning below before enabling this.
- **Human-in-the-loop everything** — birthday message drafts and Instagram-derived updates always
  land in a Review Queue. The app never sends or posts anything on your behalf.
- **AuDHD-friendly design choices**:
  - A single "Today" dashboard: birthdays, notable dates, memories, and a gentle "time to reach out"
    list — nothing punitive, everything snoozable.
  - Per-person check-in cadence reminders (e.g. "every 60 days") instead of a guilt-inducing streak
    counter.
  - Quick-capture journal entry is just one big text box — minimal required fields.
  - Visual-first UI (avatar grid, tag colors) instead of dense spreadsheets.
  - Optional "energy cost" tag on entries (low/medium/high) for planning social bandwidth.
  - Full JSON/CSV export at any time — your data, no lock-in.

## Quick start (Docker)

```bash
git clone <this repo> kin && cd kin
cp .env.example .env    # edit TZ etc. if you like
docker compose up -d --build
```

Then open `http://localhost:8000` and follow the setup wizard to create your admin account.

Your data lives in a Docker volume (`kin_data`) mounted at `/data` inside the container — a SQLite
database plus any cached Instagram session files. Back it up like any other volume, or export data
any time from the in-app **Export** page.

### Using Postgres instead of SQLite

SQLite (the default) is plenty for personal use and keeps this a single container. If you'd rather
run Postgres, set `DATABASE_URL` (e.g. `postgresql+psycopg2://user:pass@postgres:5432/kin`) as an
environment variable and add a `postgres` service to `docker-compose.yml`.

## Connecting Immich

1. In Immich, go to **Account Settings → API Keys** and create a new key.
2. In Kin, go to **Settings → Immich**, enter your Immich server URL and the API key, and hit
   *Test connection*.
3. On a person's profile, click **Link Immich face** to associate them with a recognized face —
   their photos and the "On this day" widget will start working immediately.

## Connecting an AI assistant

Kin works fully without AI — it's purely additive. In **Settings → AI assistant**, set:
- **API base URL**: `https://api.openai.com/v1` for OpenAI, or e.g. `http://ollama:11434/v1` for a
  local Ollama server on the same Docker network.
- **API key**: your OpenAI key (Ollama doesn't check this — put any placeholder value).
- **Model**: e.g. `gpt-4o-mini`, or a local model name like `llama3.1`.

## ⚠️ About the Instagram integration

This uses [`instagrapi`](https://github.com/subzeroid/instagrapi), an **unofficial**,
reverse-engineered client — there is no public Instagram API for monitoring other accounts' posts.
Please read before enabling it in **Settings → Instagram**:

- It's against Instagram's Terms of Service. Use a **secondary/throwaway account** that follows the
  people you want to track — never your primary personal account.
- Instagram may challenge the login (2FA/checkpoint) or restrict the account, especially on first
  login from a new server. This integration may need occasional maintenance as Instagram changes.
- Nothing is posted, messaged, or liked automatically — it only *reads* recent posts from accounts
  you specify and queues them in the Review Queue for you to turn into a journal entry or dismiss.
- If this doesn't feel worth the risk, just leave it disabled — every other feature works fine
  without it.

## Data model, in brief

- **People** are your contacts: birthday, how you met, tags, notable dates, check-in cadence.
- **Journal entries** are the core activity log — a note, hangout, call, gift, milestone, etc. Each
  entry can tag any number of people and have any number of attached photos.
- **Review queue** holds AI-adjacent, not-yet-applied items: birthday message drafts and incoming
  Instagram posts.

## Security notes

- Sessions use a signed cookie (secret auto-generated and persisted to your data volume on first
  run). This app has no CSRF token layer beyond `SameSite=Lax` cookies — it's designed for **trusted,
  private-network use** (home server, VPN, Tailscale, etc.), not for exposing directly to the public
  internet without a reverse proxy that adds its own auth/rate limiting.
- API keys/passwords for Immich, AI providers, and Instagram are stored in the database in plain
  text (necessary since the app needs to use them). Treat your data volume like any other secrets
  store.

## Development

The app is a single FastAPI service rendering server-side Jinja2 templates with HTMX/Alpine.js for
interactivity (both vendored locally under `app/static/js` — no CDN/build step required). No
Alembic — a small startup migration helper in `app/migrations.py` patches new columns onto existing
SQLite databases as the schema evolves.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --reload
```
