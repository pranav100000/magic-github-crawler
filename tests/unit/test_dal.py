from datetime import date
from ghcrawler.db import dal
from ghcrawler.db.engine import SessionLocal
from ghcrawler.db.models import Repository, RepoStarSnapshot

TODAY = date.today()

def test_upsert_idempotent():
    dal.upsert_repository(repo_id=1, name_owner="octocat/Hello‑World", language="Python")
    dal.upsert_repository(repo_id=1, name_owner="octocat/Hello‑World", language="Python")

    with SessionLocal() as s:
        assert s.query(Repository).count() == 1

def test_bulk_insert_snapshots():
    dal.bulk_insert_snapshots([(1, TODAY, 42), (1, TODAY, 42)])  # duplicate row ignored
    dal.bulk_insert_snapshots([(1, TODAY, 99)])  # conflict ignored

    with SessionLocal() as s:
        snap = (
            s.query(RepoStarSnapshot)
            .filter_by(repo_id=1, snapshot_date=TODAY)
            .one()
        )
    assert snap.star_count == 42  # unchanged due to DO NOTHING