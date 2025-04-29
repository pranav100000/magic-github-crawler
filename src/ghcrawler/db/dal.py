"""High‑level, sync helpers around SQLAlchemy session.

These keep SQL in **one place** so later refactors (async, raw COPY, etc.) touch only this file.
"""
from collections.abc import Iterable
from datetime import date
from contextlib import contextmanager

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .engine import SessionLocal
from .models import Repository, RepoStarSnapshot

@contextmanager
def session_scope() -> Iterable[Session]:
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def upsert_repository(*, repo_id: int, name_owner: str, language: str | None = None) -> None:
    """Insert new repo or touch `updated_at` if it already exists."""
    stmt = (
        insert(Repository)
        .values(id=repo_id, name_owner=name_owner, language=language)
        .on_conflict_do_update(index_elements=["id"], set_={"language": language})
    )
    with session_scope() as s:
        s.execute(stmt)

def bulk_insert_snapshots(records: list[tuple[int, date, int]]) -> None:
    """Insert many (repo_id, snapshot_date, star_count) rows.
    Ignore duplicates (ON CONFLICT DO NOTHING).
    """
    if not records:
        return

    stmt = insert(RepoStarSnapshot).values([
        {"repo_id": rid, "snapshot_date": d, "star_count": stars} for rid, d, stars in records
    ]).on_conflict_do_nothing(index_elements=["repo_id", "snapshot_date"])

    with session_scope() as s:
        s.execute(stmt)