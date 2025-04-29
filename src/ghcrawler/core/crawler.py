import asyncio
from datetime import date
import logging  # Import logging
import calendar # Import calendar module
from ghcrawler.api import GithubClient
from ghcrawler.db import dal
from ghcrawler.config import get_settings

_SETTINGS = get_settings()
logger = logging.getLogger(__name__)  # Setup logger

# --- Configuration for Segmentation ---

# Ranges processed directly (high stars, less likely to hit 1k limit per query)
SIMPLE_STAR_RANGES = [
    "stars:>100000",
    "stars:50001..100000",
    "stars:10001..50000",
]

# Ranges needing secondary date segmentation (low stars, very likely to hit 1k limit)
DATE_SEGMENTED_STAR_RANGES = [
    "stars:1001..10000",
    "stars:101..1000",
    "stars:51..100",
    "stars:11..50",
    "stars:1..10",
]

# Generate years for date segmentation (GitHub launched in 2008)
current_year = date.today().year
YEARS_FOR_SEGMENTATION = list(range(2008, current_year + 1))

# Limit for results per specific query (star range + optional date range)
MAX_RESULTS_PER_QUERY = 980


class AsyncCrawler:
    def __init__(self, target: int = 100_000, batch: int = 100):
        self.target = target
        self.batch = batch
        self.fetched = 0
        self.today = date.today()

    async def _process_segment(self, gh: GithubClient, query: str):
        """Helper to process pagination for a single specific query string."""
        logger.info(f"Processing query: {query}")
        cursor = None
        segment_fetched_count = 0

        while True:
            if self.fetched >= self.target:
                logger.info(
                    f"Target reached ({self.target}). Stopping processing for query: {query}"
                )
                return True  # Signal that target was reached

            if segment_fetched_count >= MAX_RESULTS_PER_QUERY:
                logger.warning(
                    f"Reached MAX_RESULTS_PER_QUERY ({MAX_RESULTS_PER_QUERY}) for query '{query}'. Stopping pagination for this query."
                )
                return False  # Signal target not reached, but query segment is done

            try:
                current_batch = min(
                    self.batch, MAX_RESULTS_PER_QUERY - segment_fetched_count
                )
                if current_batch <= 0:
                    break

                page = await gh.search_repos(
                    search_query=query, after=cursor, batch=current_batch
                )

            except Exception as e:
                logger.error(
                    f"Error fetching page for query '{query}' (after: {cursor}): {e}. Skipping rest of this query.",
                    exc_info=True,
                )
                return False  # Signal target not reached, error occurred

            if not page.repos:
                logger.info(
                    f"No more results found for query: {query} (after: {cursor})"
                )
                break  # End of pagination for this query

            # 1 · metadata upsert
            # Consider making DB operations async if they become a bottleneck
            for repo in page.repos:
                dal.upsert_repository(
                    repo_id=repo.id,
                    name_owner=repo.nameWithOwner,
                    language=None,  # populate later if needed
                )

            # 2 · snapshot insert (bulk)
            snapshot_rows = [(r.id, self.today, r.stargazerCount) for r in page.repos]
            dal.bulk_insert_snapshots(snapshot_rows)

            count_in_page = len(page.repos)
            self.fetched += count_in_page
            segment_fetched_count += count_in_page
            cursor = page.end_cursor

            # 3 · progress output
            logger.info(
                f"Query '{query}': Fetched {count_in_page} (Query total: {segment_fetched_count}, Overall: {self.fetched}/{self.target}) — Cost={page.cost} Remaining={page.remaining}"
            )

            if not page.has_next:
                logger.info(f"GitHub indicates no more pages for query: {query}")
                break  # End of pagination for this query

        return self.fetched >= self.target  # Return whether target was reached

    async def run(self):
        logger.info(f"Starting crawl. Target: {self.target} repositories, Batch size: {self.batch}")
        self.fetched = 0
        target_reached = False
        today = date.today() # Get today's date once
        current_year = today.year
        current_month = today.month

        # Regenerate years list based on the actual current year at runtime
        years_to_process = list(range(2008, current_year + 1))

        async with GithubClient(_SETTINGS.github_token) as gh:

            # 1. Process simple star ranges
            logger.info("--- Processing Simple Star Ranges ---")
            for star_query in SIMPLE_STAR_RANGES:
                target_reached = await self._process_segment(gh, star_query)
                if target_reached:
                    break
            if target_reached:
                 logger.info(f"✔ Crawl complete (target reached during simple ranges). Total fetched: {self.fetched}")
                 return

            # 2. Process date-segmented star ranges (Monthly)
            logger.info("--- Processing Date-Segmented Star Ranges (Monthly) ---")
            for star_query in DATE_SEGMENTED_STAR_RANGES:
                logger.info(f"-- Starting Monthly Date Segmentation for Star Range: {star_query} --")
                for year in reversed(years_to_process): # Use the dynamically generated list
                    logger.info(f"---- Processing Year: {year} for Star Range: {star_query} ----")

                    # Determine the range of months to iterate through for this year
                    if year == current_year:
                        months_to_process = range(1, current_month + 1) # Only up to current month
                    else:
                        months_to_process = range(1, 13) # All months for past years

                    for month in months_to_process:
                        # Calculate start and end dates for the month
                        month_start_day = 1
                        month_end_day = calendar.monthrange(year, month)[1]
                        start_date_str = f"{year}-{month:02d}-{month_start_day:02d}"
                        end_date_str = f"{year}-{month:02d}-{month_end_day:02d}"
                        date_range = f"created:{start_date_str}..{end_date_str}"

                        combined_query = f"{star_query} {date_range}"

                        target_reached = await self._process_segment(gh, combined_query)
                        if target_reached:
                            break # Stop processing months for this year if target reached

                    if target_reached:
                         break # Stop processing years for this star_query if target reached

                if target_reached:
                     break # Stop processing further star_queries if target reached

        logger.info(f"✔ Crawl complete. Total repositories fetched: {self.fetched}")
