# Installation

Kin is a single Docker container with a local SQLite database. There's nothing else to install.

## Requirements

- A machine that can run Docker (any Linux box, a NAS, or an Unraid server).
- About 100 MB of RAM when idle, more if you enable AI or voice.

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `TZ` | `UTC` | Your timezone, e.g. `Australia/Brisbane`. Set this or reminders will fire at the wrong time. |
| `DATA_DIR` | `/data` | Where the database lives. Point it at a persistent volume. |
| `DISABLE_SCHEDULER` | `0` | Set to `1` to turn off background jobs (useful when running more than one container against the same DB). |
| `ALLOWED_HOSTS` | `*` | Comma-separated hostnames the server accepts. `*` is fine for LAN-only use. |
| `DATABASE_URL` | *(auto)* | Override the SQLite path if you need Postgres. |

!!! warning "Mount `/data` persistently"
    If you don't map a volume to `/data`, your database is wiped every time the container is recreated. The Quick start example already does this with `kin-data`.

## HTTPS and reverse proxies

Kin works fine over plain HTTP on your home network. To reach it securely from outside (or to use a nice hostname), put it behind a reverse proxy:

- **Nginx Proxy Manager**, **Caddy**, or **Traefik** all work — point them at `http://<host>:8000`.
- A custom domain like `kin.example.com` with a Let's Encrypt cert is the usual setup.

!!! note "You're the one person using it?"
    If it's just you, an SSH tunnel is even simpler: `ssh -L 8000:localhost:8000 <your-server>` and open <http://localhost:8000>. No public exposure, no DNS.

## Updating

Pull the latest image and recreate the container. Your data survives because it's in `/data`.

```bash
docker pull skyej/kin-crm:latest
docker rm -f kin
# re-run your docker run command from the Quick start
```

See [Upgrading](admin.md#upgrades) for the full story.
