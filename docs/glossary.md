# Glossary

A quick reference for the words this project (and self-hosting generally) throws around.

**API key**
A secret string that lets one service talk to another (e.g. Kin → Immich, or Kin → OpenAI). Treat it like a password — don't share it or commit it.

**Container**
A self-contained bundle of an app and everything it needs to run. Docker runs these. Kin is one container.

**Docker**
The tool that runs containers. "Running Kin in Docker" just means Kin runs inside a container on your machine.

**Docker volume**
A named chunk of persistent storage that survives container restarts. Kin keeps its database in one (`/data`).

**Household**
A group of people sharing one Kin. A household of one is an individual account; several members share the same people, journal, and config.

**Immich**
A popular self-hosted photo library that Kin can optionally integrate with for faces, photos, and "on this day" memories.

**Instance**
A single running copy of Kin (one container, one database). "Instance owner" means the admin of that copy.

**Instance owner**
The administrator of a Kin instance — can add/remove anyone, manage any household, and toggle the config lock.

**Household owner**
Someone who manages a specific household's members and config. Multiple people can be owners.

**Journal**
Kin's quick-capture log of who you saw and what happened.

**Markdown**
A simple way to write formatted text with plain characters (`# heading`, `**bold**`). These docs are written in it.

**Reverse proxy**
A server that sits in front of Kin and handles HTTPS + nice hostnames (e.g. Nginx Proxy Manager, Caddy). Optional — Kin works fine on plain HTTP locally.

**SQLite**
Kin's database — a single file (`app.db`) rather than a separate database server. That's why backing up one file backs up everything.

**TTS (text-to-speech)**
Turning written text into spoken audio. Kin uses it (via Piper or OpenAI) so the support chat can *speak* its replies.

**Whisper**
OpenAI's speech-to-text model — Kin uses it (or a local equivalent) to transcribe voice notes.
