"""API v1 router package."""
from . import auth, people, journal, dashboard, settings, ai, conflicts, push, export, stats

routers = [
    auth.router,
    people.router,
    journal.router,
    dashboard.router,
    settings.router,
    ai.router,
    conflicts.router,
    push.router,
    export.router,
    stats.router,
]
