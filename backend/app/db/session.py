from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()
_kwargs = {"connect_args": {"check_same_thread": False}} if _settings.database_url.startswith("sqlite") else {"pool_pre_ping": True}
engine = create_engine(_settings.database_url, **_kwargs)

if _settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):  # enforce referential integrity on SQLite
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
