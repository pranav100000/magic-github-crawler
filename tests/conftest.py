import pytest
from ghcrawler.db.engine import SessionLocal, engine
from ghcrawler.db.models import Base
from sqlalchemy import text


@pytest.fixture(scope="session", autouse=True)
def create_db():
    # Re‑create schema on a temp database (use the same container)
    Base.metadata.create_all(bind=engine())
    yield
    Base.metadata.drop_all(bind=engine())


@pytest.fixture(scope="class", autouse=True)
def clean_database():
    """Clean all tables before each test."""
    with SessionLocal() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(
                text(f"TRUNCATE TABLE {table.name} RESTART IDENTITY CASCADE")
            )
        session.commit()
    yield
