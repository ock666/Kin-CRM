# Quick start

Get Kin running in about five minutes. No cloud account, no phone home — it all lives on your machine.

## The short version

=== "Docker (any OS)"

    ```bash
    docker run -d --name kin \
      -p 8000:8000 \
      -v kin-data:/data \
      -e TZ=Australia/Brisbane \
      --restart unless-stopped \
      skyej/kin-crm:latest
    ```

    Then open <http://localhost:8000> in your browser.

=== "Unraid"

    1. In the Unraid **Docker** tab, click **Add Container**.
    2. Set **Repository** to `skyej/kin-crm:latest`.
    3. Add a port mapping: **Host** `8000` → **Container** `8000`.
    4. Add a path mapping: `/mnt/user/appdata/kin-crm` → `/data`.
    5. Set the variable `TZ` to your timezone (e.g. `Australia/Brisbane`).
    6. Click **Apply**.

    Then open `http://<your-unraid-ip>:8000`.

!!! info "New to Docker?"
    [Docker](glossary.md#docker) bundles an app with everything it needs, so you don't install a dozen dependencies by hand. The one command above downloads Kin and starts it in one go — copy, paste, done. The only concept worth knowing up front is the [volume](glossary.md#docker-volume): it's the folder where Kin keeps your data between restarts.

## First run

The first time you open Kin, a **setup wizard** asks you to:

1. Choose a **name**, an **email** (this is your login), and a **password**.
2. That's it — you're the first [instance owner](glossary.md#instance-owner).

Everything else (AI, [Immich](glossary.md#immich), voice, calendar) is optional and can be configured later.

## Next steps

- [Core concepts](concepts.md) — the mental model: people, journal, and gentle nudges.
- [Installation](installation.md) — environment variables, HTTPS, and reverse proxies.
- [Multiple people](multi-user.md) — share Kin with a partner or host it for friends.

!!! tip "Where's my data?"
    Everything lives in the [Docker volume](glossary.md#docker-volume) (`/data`). [Back it up](admin.md#backups) before you upgrade anything.
