# Kin — remember your people, not the pressure

Kin is a self-hosted relationship manager built by and for neurodivergent brains.
It handles the remembering, nudging, and structure of staying in touch — so you
can focus on the people, not the overwhelm.

## Why Kin exists

Kin was born from a lived need. I'm Skye — a 30-year-old trans woman in
Brisbane, Australia, living with AuDHD, rejection sensitive dysphoria (RSD),
and high social anxiety.

Relationships can be exhausting when the social world doesn't come with an
instruction manual: one ambiguous reply turns into hours of rumination, "you
should reach out more" lands as guilt instead of a lifeline, and overwhelm makes
even remembering a friend's birthday feel like a chore.

Kin is the gentle external brain I built to cope. It remembers what I can't
always hold onto, gives me a safe sounding board when confusion or RSD takes
over, and helps me regulate and make sense of the social world instead of
dreading it. Every design choice — the soft nudges, the human-in-the-loop AI,
the freedom to snooze or step back — comes from what actually helps me.

I hope it can help others too.

## Design philosophy

- **Gentle, never punitive.** Check-in reminders are soft "needs watering" nudges,
  not guilt-inducing overdue alarms. Everything is snoozable. Nothing shouts.
- **Human-in-the-loop AI.** AI writes suggestions; you review and approve.
  Nothing is applied to a profile or sent anywhere without your explicit click.
- **Low barrier to capture.** One big text box. Minimal required fields.
  Cross-tag people in one entry. Brain dump first, organise later.
- **Visual-first.** Avatar grids, tag colours, water meters — built for brains
  that balk at dense spreadsheets and long forms.
- **No lock-in.** Full JSON/CSV export, local SQLite database, data stays on
  your server. Leave anytime with everything.
- **AuDHD/RSD-first.** Designed around the realities of executive dysfunction,
  rejection sensitivity, and social anxiety before anything else.

## Features

### Today dashboard

- **Upcoming birthdays & notable dates** surfaced as they approach (configurable
  lead time). Birthday message drafts auto-generated daily and waiting in the
  Review Queue for your approval — nothing is ever sent or posted automatically.
- **"Time to reach out"** list — gentle cadence nudges ("it's been a while
  since you talked to X"), with one-tap snooze and mark-contacted. Every overdue
  person gets person-specific **quick reply ideas** (AI-generated from their
  profile and your shared history, with a template fallback when AI isn't
  configured) — copy-paste scripts to break the silence barrier.
- **Grace mode** ("stepping back for now"): pause all gentle nudges and push
  notifications for a week, no questions asked, no reason needed. Taking space
  is productive relational work.
- **"Read back when anxious"** — a personal reassurance note you write yourself,
  plus recently unlocked achievements, to ground you on hard days.
- **"On this day"** Immich photo memories widget.

### People & relationships

- **Rich profiles**: birthday, how-you-met, pronouns, relationship label,
  location, contact info, occupation, hobbies, AI bio blurb, notes timeline.
- **Friend rank**: a live-computed completeness score (0–100) that gently
  nudges you to fill in what's missing — "not yet known: their birthday"
  rather than a guilt counter.
- **"Needs watering" cadence meter** — a plant metaphor instead of an overdue
  red alert. Healthy, getting dry, needs watering, or dormant (no cadence set).
- **Tag circles**: group people by tag into colour-coded circles (family, work,
  friends) with visual headers and an "Uncircled" bucket. Tag colour picker per
  circle.
- **Relationship states** (system-suggests, you confirm):
  - *In conflict* — auto-derived from unresolved conflict logs (the user already
    logged the conflict, no extra click needed).
  - *Wants space* / *Drifted* — user-set states that soften or suppress
    reach-out nudges and push notifications for that person.
- **Scratchpad** — fleeting "bring up next time" reminders (e.g. "ask how her
  vet visit went") pinned prominently on the person's profile and surfaced in
  the journal form.
- **Notable people** — lightweight references to someone in their life who
  doesn't need a full CRM profile (e.g. their partner, kids).
- **Notable dates** — anniversaries, kids' birthdays, and other recurring dates
  surfaced alongside birthdays.
- **Cross-tag journal entries** — tag multiple people in one entry and it
  appears on *all* of their timelines.

### Journal: quick-capture logging

- One text box. Minimal friction. Optional title, date, location, energy cost
  (low/medium/high), and event type (hangout, call, message, gift, milestone…).
- **Energy cost tracking**: tag how draining an interaction was, so you can plan
  social bandwidth over time.
- Attach Immich photos to entries via an inline asset browser.
- AI auto-extracts tags, notable dates, and follow-up reminders from entries
  — you review and apply what's useful, dismiss the rest.

### Conflict resolution (RSD-aware)

- Log something that felt off — no urgency, no pressure to act.
- **"Talk it through"**: a persistent, streaming support chat with an AI
  counsellor persona (gpt-4o recommended). Preloaded with the conflict summary
  and relationship context. Validates first, helps you work through feelings
  and arrive at a logical understanding. Transcript persists per conflict,
  auto-archives after 14 days ("water under the bridge"), and is always
  exportable.
- **Resolution plan**: auto-generated structured guide (summary, feelings,
  goal, ordered steps, copy-paste messages, boundary scripts, release option)
  after 15 minutes of chat inactivity. Also manually triggerable.
- **RSD grounding check** — "what are the facts vs. what's the story anxiety
  is telling me?" embedded in every conflict card.
- **"Save insight to journal"** — capture a key takeaway from the chat as a
  journal entry on the person's timeline (AI-drafts, you edit).
- **Release path**: "Letting this go" is explicitly a first-class, equally
  valid resolution — not a fallback.

### Gamification (non-punitive, celebrating rest too)

- Shared household-wide XP and levels (not per-user — matching the
  shared-workspace model).
- 45+ achievements: consistency streaks, breadth/depth, special moments, and
  **rest achievements** that celebrate taking space (snoozing a check-in,
  entering grace mode, releasing a conflict, setting "wants space").
- Achievements are unlocked silently; a toast only appears for something
  genuinely noteworthy (a level-up or a new badge).

### AI assistant (optional, bring-your-own-key)

Works with any OpenAI-compatible chat completions endpoint (OpenAI, Ollama,
local servers). Two separate models configurable in Settings:

- **Primary model** (e.g. gpt-4o-mini): profile summaries, fact extraction,
  conversation starters, gap questions, icebreaker scripts, birthday drafts,
  gift ideas, bio blurbs.
- **Support chat model** (e.g. gpt-4o): the "Talk it through" conflict
  counsellor and resolution plan generation.

All AI output is a **suggestion** you explicitly approve or dismiss — nothing
is written to a profile automatically.

### Regulation toolkit

- Sidebar `🧘 Regulation` link — always accessible, zero AI, no pressure.
- 5-4-3-2-1 grounding, box breathing (interactive countdown), facts-vs-RSD
  reality check framework, physical grounding tips.
- Inclusive help lines — AU, US, UK — with crisis numbers, mental health
  support, and dedicated LGBTQIA+ helplines. Explicitly secular and
  queer-affirming. No religiously affiliated organisations.

### PWA: install anywhere, gentle push notifications

- Install Kin as a standalone app (mobile or desktop) via the PWA manifest.
- Opt-in, aggregated push notifications for birthdays and overdue cadences
  — quiet, never spammy, silenced during grace mode.
- Offline-first: the app shell caches and works without a connection.

### Integrations

- **Immich**: link a person to a recognized face, pull in their photos
  automatically, browse assets from journal entries, "On this day" dashboard
  widget.
- **Instagram** (optional, unofficial, off by default): periodically reads
  recent posts from accounts you follow and queues them for review. Uses a
  reverse-engineered client; see the `⚠️ About Instagram` section.

### Data ownership

- Full JSON export (people, journal, tags, notable dates, conflicts, chat
  transcripts, resolution plans, gift ideas, Instagram posts, settings).
- CSV export (people + journal).
- JSON/CSV import (get-or-create by name, non-destructive).
- All data lives in a local SQLite database (or Postgres if you prefer).

---

## Architecture

Kin is a single FastAPI service rendering server-side Jinja2 templates with
HTMX and Alpine.js for interactivity (both vendored locally under
`app/static/js` — no CDN, no build step, no Node toolchain needed).

- **Database**: SQLite (default, plenty for personal use) with an optional
  Postgres path.
- **Migrations**: a small startup migration helper (`app/migrations.py`)
  patches new columns onto existing tables as the schema evolves — no Alembic
  required.
- **Scheduler**: APScheduler runs daily jobs (birthday drafts, Instagram poll,
  push notifications) plus a per-15-minute job for idle resolution plans.
- **Auth**: session-based via signed cookies; first-run setup wizard.
- **PWA**: service worker for offline + push; web manifest for install.

## Quick start (Docker)

```bash
git clone https://github.com/ock666/personal-crm.git kin && cd kin
cp .env.example .env    # edit TZ etc. if you like
docker compose up -d --build
```

Open `http://localhost:8000` and follow the setup wizard to create your admin
account.

Your data lives in the Docker volume `/mnt/user/appdata/personal-crm_kin_data`
mapped to `/data` inside the container — a SQLite database plus any cached
Instagram session files. Back it up like any other volume, or export from the
in-app **Export** page anytime.

### Using Postgres instead of SQLite

SQLite is plenty for personal use. If you'd rather run Postgres, set
`DATABASE_URL` (e.g. `postgresql+psycopg2://user:pass@postgres:5432/kin`) as
an environment variable and add a `postgres` service to `docker-compose.yml`.

## Configuration

Set these in `docker-compose.yml` under `environment:` or in a `.env` file:

| Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `/data` | Where the SQLite DB + uploads live inside the container |
| `TZ` | `UTC` | Server timezone (affects daily job scheduling) |
| `DISABLE_SCHEDULER` | `0` | Set to `1` to disable background jobs (testing) |
| `SESSION_SECRET` | auto-generated | Persisted to `/data/.session_secret` on first run |
| `DATABASE_URL` | (SQLite) | Optional Postgres connection string |

In-app settings (stored in the database, configurable via Settings page):
birthday lead time, default check-in cadence, daily job hour, support chat
model, conflict plan idle minutes, chat retention days, push preferences.

## Connecting Immich

1. In Immich, go to **Account Settings → API Keys** and create a new key.
2. In Kin, go to **Settings → Immich**, enter your Immich server URL and the
   API key, and press *Test connection*.
3. On a person's profile, click **Link Immich face** to associate them with a
   recognised face — their photos and the "On this day" widget start working
   immediately.

## Connecting an AI assistant

Kin works fully without AI — it's purely additive. To enable it, go to
**Settings → AI assistant** and fill in:

- **API base URL**: `https://api.openai.com/v1` for OpenAI, or e.g.
  `http://ollama:11434/v1` for a local Ollama server on the same Docker
  network.
- **API key**: your OpenAI key (Ollama doesn't validate this — put any
  placeholder value).
- **Primary model**: e.g. `gpt-4o-mini`, or a local model name like
  `llama3.2`.
- **Support chat model**: e.g. `gpt-4o` — used exclusively for the "Talk it
  through" conflict support chat and resolution plan generation. A more capable
  model is recommended for the counselling role.

Press *Test connection* to verify everything works.

## ⚠️ About the Instagram integration

This uses [`instagrapi`](https://github.com/subzeroid/instagrapi), an
**unofficial**, reverse-engineered client — there is no public Instagram API
for monitoring other accounts' posts. Please read before enabling it in
**Settings → Instagram**:

- It's against Instagram's Terms of Service. Use a **secondary/throwaway
  account** that follows the people you want to track — never your primary
  personal account.
- Instagram may challenge the login (2FA/checkpoint) or restrict the account,
  especially on first login from a new server. This integration may need
  occasional maintenance as Instagram changes.
- Nothing is posted, messaged, or liked automatically — it only *reads* recent
  posts from accounts you specify and queues them in the Review Queue for you
  to turn into a journal entry or dismiss.
- If this doesn't feel worth the risk, leave it disabled — every other feature
  works fine without it.

## Data model (in brief)

- **People**: name, birthday, how-you-met, contact info, occupation, hobbies,
  tags, notable dates/people, scratchpad items, gift ideas, check-in cadence,
  relationship state, Immich/Instagram linkage, avatar.
- **Journal entries**: body, date, event type, energy cost, location, source
  (manual/instagram/ai), attached photos, cross-referenced people.
- **Conflicts**: summary, status (unresolved/resolved/released), AI-generated
  approach suggestions, persistent support chat transcript with associated AI
  counsellor messages, auto-generated resolution plans.
- **Review queue**: pending birthday message drafts, AI gift suggestions, and
  unreviewed Instagram posts — all awaiting explicit user approval.
- **Tags**: free-form, per-person, with configurable colours. Filter people,
  group into circles, AI-extractable from entries.
- **Settings**: key/value store for Immich creds, AI keys/models, Instagram
  creds, push preferences, grace state, cadence defaults, retention windows.

## Privacy & security

- Sessions use a signed cookie (secret auto-generated and persisted to your
  data volume on first run). The app has no CSRF token layer beyond
  `SameSite=Lax` cookies — it's designed for **trusted, private-network use**
  (home server, VPN, Tailscale, etc.), not for exposing directly to the public
  internet without a reverse proxy that adds its own auth and rate limiting.
- API keys and passwords for Immich, AI providers, and Instagram are stored in
  the database in plain text (necessary since the app needs to use them to call
  external services). Treat your data volume the same way you'd treat any other
  secrets store.
- AI features send data to your configured AI provider (OpenAI, Ollama, or a
  local server). Conflict support chat transcripts are kept on your server and
  auto-archived after 14 days; they are fully exportable and removable.
- All personal data lives on your hardware. There are no analytics, no
  telemetry, no external servers, and no third-party services beyond the
  optional integrations you explicitly configure (Immich, Instagram, AI).
- This app is not a replacement for professional mental health care. If you
  need immediate support, crisis and help lines are listed on the Regulation
  toolkit page.

## Development

Kin is a single FastAPI service with server-side Jinja2 rendering, HTMX and
Alpine.js for interactivity, and SQLite by default.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --reload
```

### Running tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

152 tests covering auth, people, journal, export, reviews, settings, push,
gamification, friend rank, conflict resolution, support chat, birthday
calculation, quick replies, resolution plans, achievements, retention, grace
mode, check-in logic, states, circles, and import/export.

There's also `scripts/smoke_test.sh`, a curl-based smoke test for running
against a live, freshly-started container — see `TESTING.md`.
