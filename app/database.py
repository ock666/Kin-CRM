from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

_IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")


def _configure_engine():
    kwargs = {"future": True}
    if _IS_SQLITE:
        # A single uvicorn process serves SQLite. Sharing a handful of pooled,
        # per-thread connections (QueuePool) is fragile: a connection checked in
        # from a different thread than it was checked out on can leave the pool's
        # accounting wedged (seen as 'Connections in pool: 0 / overflow: -5') with
        # every request then blocking on a checkout. StaticPool reuses exactly one
        # connection, serialized internally, which is the safe, standard pattern for
        # in-process SQLite and never deadlocks under FastAPI's threadpool.
        connect_args = {"check_same_thread": False, "timeout": 30}
        from sqlalchemy.pool import StaticPool

        kwargs.update(
            connect_args=connect_args,
            poolclass=StaticPool,
        )
    return create_engine(settings.DATABASE_URL, **kwargs)


engine = _configure_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


@event.listens_for(engine, "connect")
def _sqlite_on_connect(dbapi_conn, _record):
    # WAL dramatically reduces reader/writer lock contention on the single SQLite file,
    # and busy_timeout makes concurrent access back off and retry instead of erroring
    # immediately. Both are the usual fixes for intermittent "database is locked" hangs.
    if _IS_SQLITE:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
