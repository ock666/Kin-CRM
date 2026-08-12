#!/bin/bash
set -e

if [ -n "$PUID" ] && [ -n "$PGID" ]; then
    getent group "$PGID" >/dev/null || groupadd -o -g "$PGID" abc
    getent passwd "$PUID" >/dev/null || useradd -o -u "$PUID" -g "$PGID" -d /app -s /bin/bash abc
    chown -R "$PUID:$PGID" /data 2>/dev/null || true
    exec gosu "$PUID:$PGID" "$@"
fi

exec "$@"
