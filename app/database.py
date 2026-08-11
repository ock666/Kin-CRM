from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    # check_same_thread=False lets FastAPI's threadpool share the SQLite connection.
    # timeout ensures a blocked writer/reader eventually raises instead of wedging the
    # whole pool; pool_pre_ping/keep-alive stop stale connections from leaking.
    connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    future=True,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=30,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


@event.listens_for(engine, "connect")
def _sqlite_on_connect(dbapi_conn, _record):
    # WAL dramatically reduces reader/writer lock contention on the single SQLite file,
    # and busy_timeout makes concurrent access back off and retry instead of erroring
    # immediately. Both are the usual fixes for intermittent "database is locked" hangs.
    if settings.DATABASE_URL.startswith("sqlite"):
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
