import pytest
from ghcrawler.db.engine import SessionLocal, engine
from ghcrawler.db.models import Base

@pytest.fixture(scope="session", autouse=True)
def _create_db():
    # Re‑create schema on a temp database (use the same container)
    Base.metadata.create_all(bind=engine())
    yield
    Base.metadata.drop_all(bind=engine())