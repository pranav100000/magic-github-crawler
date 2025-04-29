import aiohttp, asyncio
import logging  # Use standard logging
from typing import Any, TypedDict, List, Optional
from pydantic import BaseModel
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryCallState,
)
from ghcrawler.config import get_settings
from .rate_limiting import RateLimiter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

# Small delay added *before* each request to ease CPU pressure / request frequency
INTER_REQUEST_DELAY_SECONDS = 0.25
# Estimated cost acquired *before* the request
PRE_ACQUIRE_COST = 1

# --- Rate Limiter Configuration ---
# Primary limit: Typically 5000 points/hour
# Secondary limit (points): 2000 points/minute
# Secondary limit (CPU): ~60s CPU / 60s real time for GraphQL

# We tune the limiter based on the stricter secondary point limit.
SECONDARY_POINTS_PER_MINUTE = 2000
# Reduce capacity slightly to prevent large initial bursts, respecting secondary limits
LIMITER_CAPACITY = min(_SETTINGS.bucket_capacity, 1000)

# global limiter tuned for GitHub secondary rate limits
_limiter = RateLimiter(
    capacity=LIMITER_CAPACITY,  # Use a potentially reduced capacity
    refill_per_min=SECONDARY_POINTS_PER_MINUTE,  # Refill based on secondary points/min limit
)


class GithubAbuseRateLimitError(Exception):
    """Custom exception for GitHub abuse rate limit error."""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(
            f"GitHub abuse rate limit hit. Retry after {retry_after} seconds."
        )


# --- Tenacity Callbacks ---
def log_retry(retry_state: RetryCallState):
    """Log retry attempts."""
    attempt = retry_state.attempt_number
    exception = retry_state.outcome.exception()
    wait_time = retry_state.next_action.sleep
    logger.warning(
        f"Retrying attempt {attempt} after exception {exception}. Waiting {wait_time:.2f}s."
    )


def wait_strategy(retry_state: RetryCallState) -> float:
    """Determine wait time based on exception type."""
    exception = retry_state.outcome.exception()
    if isinstance(exception, GithubAbuseRateLimitError):
        # Respect Retry-After header for abuse limits
        return float(exception.retry_after)
    else:
        # Use exponential backoff for other errors
        # Re-create the exponential wait parameters used in the decorator
        return wait_exponential(multiplier=1, min=2, max=10)(retry_state)


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

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_strategy,
        retry=retry_if_exception_type((aiohttp.ClientError, GithubAbuseRateLimitError)),
        before_sleep=log_retry,
    )
    async def search_repos(
        self, *, search_query: str, after: str | None = None, batch: int = 100
    ) -> GithubPage:
        """Searches repositories using a specific query string and handles pagination."""
        cursor_var = f', after: "{after}"' if after else ""
        query = {
            "query": f"""
            query {{
                search(query: \"{search_query}\", type: REPOSITORY, first: {batch}{cursor_var}) {{
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
        logger.debug(
            f"Executing GraphQL query for segment: {search_query}, after: {after}"
        )

        # --- Acquire estimated cost and apply delay BEFORE the request ---
        await _limiter.acquire(PRE_ACQUIRE_COST)
        await asyncio.sleep(INTER_REQUEST_DELAY_SECONDS)

        async with self._session.post(_ENDPOINT, json=query) as resp:  # type: ignore[index]
            # --- Abuse Rate Limit Check ---
            if resp.status == 403:
                try:
                    data = await resp.json()
                    body_text = str(data).lower()
                except aiohttp.ContentTypeError:
                    body_text = (await resp.text()).lower()

                if "abuse" in body_text or "secondary rate limit" in body_text:
                    retry_after_header = resp.headers.get("Retry-After")
                    if retry_after_header:
                        try:
                            wait_seconds = int(retry_after_header)
                            logger.warning(
                                f"GitHub abuse rate limit detected. Will retry after {wait_seconds} seconds."
                            )
                            raise GithubAbuseRateLimitError(retry_after=wait_seconds)
                        except ValueError:
                            logger.error(
                                f"Could not parse Retry-After header: {retry_after_header}"
                            )
                    else:
                        logger.warning(
                            "GitHub abuse rate limit detected, but no Retry-After header found. Using default backoff."
                        )

            # Check for other errors (like 404, 5xx, etc.)
            resp.raise_for_status()

            data: dict[str, Any] = await resp.json()
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

            return GithubPage(
                repos=repos,
                end_cursor=info["endCursor"],
                has_next=info["hasNextPage"],
                cost=cost,
                remaining=remaining,
            )
