import sqlalchemy as sa
from ghcrawler.db import engine, Base

def test_tables_exist():
    insp = sa.inspect(engine())
    assert set(insp.get_table_names()) >= {"repositories", "repo_star_snapshots"}