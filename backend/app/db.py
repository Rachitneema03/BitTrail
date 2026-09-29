from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_s = settings()
if _s.is_sqlite:
    _connect_args: dict = {"check_same_thread": False}
elif ":6543" in _s.database_url:
    # Supabase transaction pooler (PgBouncer): server-side prepared statements are not supported
    _connect_args = {"prepare_threshold": None}
else:
    _connect_args = {}
engine = create_engine(_s.database_url, connect_args=_connect_args, pool_pre_ping=True, pool_size=5, max_overflow=5) \
    if not _s.is_sqlite else create_engine(_s.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        lock_down_public_api()


def lock_down_public_api() -> None:
    """Enable Row Level Security (no policies) on every BitTrail table.

    On Supabase, tables in the `public` schema are also served by the auto-generated REST API to anyone holding
    the publishable/anon key. BitTrail never uses that API; the backend connects as a role that bypasses RLS.
    RLS-with-no-policies therefore blocks the REST API completely without affecting the app. Idempotent.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            conn.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
