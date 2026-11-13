# Self-hosting admin

Once it's running, Kin mostly looks after itself. These are the things worth knowing.

## Backups

**Everything Kin knows lives in one [SQLite](glossary.md#sqlite) file** — `/data/app.db`. Back up that file and you've backed up everything.

```bash
# A clean, safe backup of a live database:
sqlite3 /path/to/kin-data/app.db ".backup 'kin-backup-$(date +%F).db'"
```

Or just stop the container and copy `/data`. Do this before upgrades, and keep a copy somewhere off the machine (a NAS, another disk, or object storage). It's the single most important thing on this page.

!!! tip "Automate it"
    A daily `sqlite3 ... .backup` via cron (or a scheduled script on Unraid) is cheap insurance against disk failure.

## Upgrades

1. Back up `/data` (above).
2. `docker pull skyej/kin-crm:latest`.
3. Recreate the container with the same `-v ...:/data` mapping.

Kin runs migrations automatically on startup — new columns and tables appear without you doing anything. Upgrades are designed to be non-destructive.

## Managing people

As the [instance owner](glossary.md#instance-owner), **Settings → Households & members** is your control panel:

- Add a person (they get their own private Kin).
- Group people into [households](glossary.md#household) and edit any household's config.
- Promote/demote [instance owners](glossary.md#instance-owner) and [household owners](glossary.md#household-owner).
- Toggle the **hide config** lock per person.

!!! warning "Removing ≠ undoing a link"
    When two accounts link into one household, their data is *merged*. Removing someone later gives them their own fresh Kin — it doesn't split the merged data back out. Link thoughtfully.

## Troubleshooting

### "Database is locked" or slow writes
Kin runs SQLite in WAL mode with a busy timeout already configured. If you see lock errors, make sure the `/data` volume is on fast local storage (not a slow network share) and you aren't running two containers against the same file.

### Reminders fire at the wrong time
Almost always a `TZ` mismatch. Set `TZ` to your real timezone and recreate the container.

### AI / [Immich](glossary.md#immich) / voice "not configured"
These are all optional and **per household**. Check **Household → Edit household config** (not the main Settings page) and use each section's **Test connection** button.

### Can't reach it from outside
Kin binds to port `8000` inside the container. Map it to a host port and, for external access, put it behind a [reverse proxy](glossary.md#reverse-proxy) — see [Installation](installation.md).

### I forgot my password / am locked out
There's no in-app reset by design (self-hosted, no email). As the instance owner you can add another admin account and recover from there — another reason to back up `/data`.
