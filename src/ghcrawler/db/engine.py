from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ghcrawler.config import get_settings

_settings = get_settings()
_ENGINE = create_engine(_settings.db_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=_ENGINE, autoflush=False, autocommit=False, future=True)

def engine():
    """Return the singleton SQLAlchemy engine."""
    return _ENGINE