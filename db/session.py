import os
from contextlib import contextmanager
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base


# Load environment variables from .env if present.
load_dotenv()


def _get_database_url(explicit_url: str | None) -> str:
    url = explicit_url or os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Database URL must be provided via argument or DATABASE_URL env variable.")
    return url


def create_session_factory(database_url: str | None = None, echo: bool = False) -> sessionmaker[Session]:
    engine = create_engine(_get_database_url(database_url), echo=echo, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def session_scope(database_url: str | None = None, echo: bool = False) -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    factory = create_session_factory(database_url=database_url, echo=echo)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
