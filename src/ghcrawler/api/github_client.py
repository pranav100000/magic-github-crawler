import aiohttp, asyncio
from typing import Any, TypedDict, List, Optional
from pydantic import BaseModel
from ghcrawler.config import get_settings
from .rate_limiting import RateLimiter

class RepoNode(BaseModel):
    id: int
    nameWithOwner: str
    stargazerCount: int

class GithubPage(BaseModel):
    repos: List[RepoNode]
    end_cursor: Optional[str]
    has_next: bool
    cost: int
    remaining: int

_SETTINGS = get_settings()
_ENDPOINT = _SETTINGS.github_graphql_endpoint or "https://api.github.com/graphql"

# global limiter tuned for a single GitHub token
_limiter = RateLimiter(capacity=_SETTINGS.bucket_capacity, refill_per_min=_SETTINGS.bucket_refill_per_min)

class GithubClient:
    """Minimal async wrapper around GitHub GraphQL."""

    def __init__(self, token: str):
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(headers=self._headers)
        return self

    async def __aexit__(self, *exc):
        await self._session.close()  # type: ignore[arg‑type]

    async def search_repos(self, *, after: str | None = None, batch: int = 100) -> GithubPage:
        cursor_var = f', after: "{after}"' if after else ""
        query = {
            "query": f"""
            query {{
                search(query: \"stars:>0\", type: REPOSITORY, first: {batch}{cursor_var}) {{
                    pageInfo {{ endCursor hasNextPage }}
                    nodes {{
                    ... on Repository {{
                        databaseId
                        nameWithOwner
                        stargazerCount
                    }}
                    }}
                }}
                rateLimit {{ cost remaining }}
            }}"""
        }
        async with self._session.post(_ENDPOINT, json=query) as resp:  # type: ignore[index]
            data: dict[str, Any] = await resp.json()

        # handle errors (omitted for brevity)
        info = data["data"]["search"]["pageInfo"]
        repos = [
            RepoNode(
                id=n["databaseId"],
                nameWithOwner=n["nameWithOwner"],
                stargazerCount=n["stargazerCount"],
            )
            for n in data["data"]["search"]["nodes"]
        ]
        cost = data["data"]["rateLimit"]["cost"]
        remaining = data["data"]["rateLimit"]["remaining"]

        await _limiter.acquire(cost)

        return GithubPage(repos=repos, end_cursor=info["endCursor"], has_next=info["hasNextPage"], cost=cost, remaining=remaining)