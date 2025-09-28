"""Database session management and base model definitions."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import settings


class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy models."""


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def session_scope() -> Generator:
    """Provide a transactional scope around a series of operations."""

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # pragma: no cover
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency for working with a database session."""

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # pragma: no cover
        session.rollback()
        raise
    finally:
        session.close()


