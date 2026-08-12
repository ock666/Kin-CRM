#!/bin/bash
set -e

if [ -n "$PUID" ] && [ -n "$PGID" ]; then
    if ! getent group "$PGID" >/dev/null; then
        groupadd -o -g "$PGID" abc
    fi
    if ! getent passwd "$PUID" >/dev/null; then
        useradd -o -u "$PUID" -g "$PGID" -d /app -s /bin/bash abc
    fi
    if ! chown -R "$PUID:$PGID" /data; then
        echo "Warning: Could not set ownership on /data directory" >&2
    fi
    exec gosu "$PUID:$PGID" "$@"
fi

exec "$@"
