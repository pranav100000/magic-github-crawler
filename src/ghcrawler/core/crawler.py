import asyncio
from datetime import date
from ghcrawler.api import GithubClient
from ghcrawler.db import dal
from ghcrawler.config import get_settings

_SETTINGS = get_settings()

class AsyncCrawler:
    def __init__(self, target: int = 100_000, batch: int = 100):
        self.target = target
        self.batch = batch
        self.fetched = 0
        self.today = date.today()

    async def run(self):
        async with GithubClient(_SETTINGS.github_token) as gh:
            cursor = None
            while self.fetched < self.target:
                page = await gh.search_repos(after=cursor, batch=self.batch)

                # 1 · metadata upsert
                for repo in page.repos:
                    dal.upsert_repository(
                        repo_id=repo.id,
                        name_owner=repo.nameWithOwner,
                        language=None,  # populate later if needed
                    )

                # 2 · snapshot insert (bulk)
                snapshot_rows = [
                    (r.id, self.today, r.stargazerCount) for r in page.repos
                ]
                dal.bulk_insert_snapshots(snapshot_rows)

                self.fetched += len(page.repos)
                cursor = page.end_cursor

                # 3 · progress output
                print(
                    f"[crawler] {self.fetched}/{self.target} repos — cost={page.cost} remaining={page.remaining}"
                )

                if not page.has_next:
                    break  # safety guard for unexpected early termination

        print("✔ Crawl complete: ", self.fetched, "repos")