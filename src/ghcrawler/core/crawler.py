import asyncio
from datetime import date
import logging  # Import logging
import calendar  # Import calendar module
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
]

# Ranges needing secondary date segmentation (low stars, very likely to hit 1k limit)
DATE_SEGMENTED_STAR_RANGES = [
    "stars:10001..50000",
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

# Default concurrency level - Reduced to be more conservative with secondary limits
DEFAULT_CONCURRENCY = 3


class AsyncCrawler:
    def __init__(
        self,
        target: int = 100_000,
        batch: int = 100,
        concurrency: int = DEFAULT_CONCURRENCY,
    ):
        self.target = target
        self.batch = batch
        self.fetched = 0
        self.today = date.today()
        self.semaphore = asyncio.Semaphore(concurrency)
        self.stop_event = asyncio.Event()  # Event to signal stopping

    async def _process_segment(self, gh: GithubClient, query: str) -> bool:
        """
        Helper to process pagination for a single specific query string.
        Returns True if the overall target was reached during processing, False otherwise.
        """
        logger.info(f"Processing segment: {query}")
        cursor = None
        segment_fetched_count = 0
        target_reached_in_segment = False

        while True:
            # Check if stop signal received or target already met before making API call
            if self.stop_event.is_set():
                logger.info(f"Stop signal received for query: {query}. Halting.")
                break  # Stop processing this segment
            if self.fetched >= self.target:
                logger.info(
                    f"Target reached ({self.target}) globally. Stopping segment: {query}"
                )
                if not self.stop_event.is_set():
                    self.stop_event.set()  # Ensure stop signal is set
                target_reached_in_segment = True
                break

            if segment_fetched_count >= MAX_RESULTS_PER_QUERY:
                logger.warning(
                    f"Reached MAX_RESULTS_PER_QUERY ({MAX_RESULTS_PER_QUERY}) for query '{query}'. Stopping pagination for this query."
                )
                break  # Segment limit reached

            try:
                # Check stop signal again before potentially long API call
                if self.stop_event.is_set():
                    logger.info(
                        f"Stop signal received before API call for query: {query}. Halting."
                    )
                    break

                current_batch = min(
                    self.batch, MAX_RESULTS_PER_QUERY - segment_fetched_count
                )
                # Ensure we don't exceed overall target in this batch request (approximate)
                current_batch = min(
                    current_batch, self.target - self.fetched + 1
                )  # +1 to be safe
                if current_batch <= 0:
                    break  # Avoid batch size <= 0

                logger.debug(
                    f"Query '{query}': Requesting batch size {current_batch}, after: {cursor}"
                )
                page = await gh.search_repos(
                    search_query=query, after=cursor, batch=current_batch
                )

            except Exception as e:
                # Check if the error is due to cancellation
                if isinstance(e, asyncio.CancelledError):
                    logger.warning(f"Task for query '{query}' was cancelled.")
                    raise  # Re-raise cancellation
                logger.error(
                    f"Error fetching page for query '{query}' (after: {cursor}): {e}. Skipping rest of this query.",
                    exc_info=True,
                )
                break  # Error occurred, stop this segment

            if not page.repos:
                logger.info(
                    f"No more results found for query: {query} (after: {cursor})"
                )
                break  # End of pagination for this query

            # --- Database Operations ---
            # Consider making DB operations truly async if they become a bottleneck
            # For now, keeping them synchronous but releasing GIL allows some concurrency
            try:
                # 1 · metadata upsert
                for repo in page.repos:
                    dal.upsert_repository(
                        repo_id=repo.id,
                        name_owner=repo.nameWithOwner,
                        language=None,  # populate later if needed
                    )

                # 2 · snapshot insert (bulk)
                snapshot_rows = [
                    (r.id, self.today, r.stargazerCount) for r in page.repos
                ]
                dal.bulk_insert_snapshots(snapshot_rows)
            except Exception as db_err:
                logger.error(
                    f"Database error during processing query '{query}': {db_err}",
                    exc_info=True,
                )
                # Decide if we should stop the segment or continue? For now, stop.
                break

            # --- Update Counts & Cursor ---
            count_in_page = len(page.repos)
            # Lock fetch update? Not strictly necessary with asyncio if DB ops release GIL
            # but could be added if race conditions appear. For now, assume okay.
            self.fetched += count_in_page
            segment_fetched_count += count_in_page
            cursor = page.end_cursor

            # --- Progress Output & Target Check ---
            logger.info(
                f"Query '{query}': Fetched {count_in_page} (Seg total: {segment_fetched_count}, Overall: {self.fetched}/{self.target}) | Cost={page.cost} Remaining={page.remaining}"
            )

            # Check if target reached *after* processing this page
            if self.fetched >= self.target:
                logger.info(
                    f"Target reached ({self.target}) after processing page for query: {query}"
                )
                if not self.stop_event.is_set():
                    self.stop_event.set()  # Signal others to stop
                target_reached_in_segment = True
                # Don't break here, let the loop condition handle it next iteration
                # to ensure has_next check runs.

            if not page.has_next:
                logger.info(f"GitHub indicates no more pages for query: {query}")
                break  # End of pagination for this query

        return target_reached_in_segment

    async def _process_segment_wrapper(self, gh: GithubClient, query: str):
        """Acquires semaphore, runs segment processing, releases semaphore."""
        async with self.semaphore:
            # Check stop event *before* starting processing for this segment
            if self.stop_event.is_set() or self.fetched >= self.target:
                logger.info(
                    f"Skipping segment '{query}' as stop signal is set or target reached."
                )
                return
            try:
                await self._process_segment(gh, query)
            except asyncio.CancelledError:
                logger.warning(f"Segment processing task for '{query}' cancelled.")
            except Exception as e:
                logger.error(
                    f"Unhandled exception in segment wrapper for '{query}': {e}",
                    exc_info=True,
                )

    async def run(self):
        logger.info(
            f"Starting crawl. Target: {self.target}, Batch: {self.batch}, Concurrency: {self.semaphore._value}"
        )
        self.fetched = 0
        self.stop_event.clear()  # Ensure event is clear at start
        tasks = []
        all_queries = []

        today = date.today()
        current_year = today.year
        current_month = today.month
        years_to_process = list(range(2008, current_year + 1))

        # 1. Generate all queries first
        logger.info("--- Generating Queries ---")

        # Simple star ranges
        all_queries.extend(SIMPLE_STAR_RANGES)
        logger.info(f"Added {len(SIMPLE_STAR_RANGES)} simple star range queries.")

        # Date-segmented star ranges (Monthly) - Generate in reverse chronological order (more recent first)
        for star_query in DATE_SEGMENTED_STAR_RANGES:
            for year in reversed(years_to_process):
                months_this_year = (
                    range(1, current_month + 1)
                    if year == current_year
                    else range(1, 13)
                )
                for month in reversed(
                    list(months_this_year)
                ):  # Process recent months first within a year
                    month_start_day = 1
                    month_end_day = calendar.monthrange(year, month)[1]
                    start_date_str = f"{year}-{month:02d}-{month_start_day:02d}"
                    end_date_str = f"{year}-{month:02d}-{month_end_day:02d}"
                    date_range = f"created:{start_date_str}..{end_date_str}"
                    combined_query = f"{star_query} {date_range}"
                    all_queries.append(combined_query)
        logger.info(f"Generated a total of {len(all_queries)} queries.")

        # 2. Process queries concurrently
        logger.info("--- Processing Segments Concurrently ---")
        async with GithubClient(_SETTINGS.github_token) as gh:
            for query in all_queries:
                # Check before creating task if we should stop
                if self.stop_event.is_set() or self.fetched >= self.target:
                    logger.info(
                        "Target reached or stop event set. Halting task creation."
                    )
                    break

                # Create and store task (wrapper handles semaphore)
                task = asyncio.create_task(self._process_segment_wrapper(gh, query))
                tasks.append(task)

            # Wait for all created tasks to complete
            logger.info(
                f"Waiting for {len(tasks)} segment processing tasks to complete..."
            )
            # Using return_exceptions=True to prevent gather from stopping on first error/cancellation
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log any exceptions that occurred in tasks
            for i, result in enumerate(results):
                if isinstance(result, Exception) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    # Find the original query associated with this task index if possible
                    # (Requires tasks and all_queries to align, which they should here)
                    query_for_error = (
                        all_queries[i] if i < len(all_queries) else "unknown query"
                    )
                    logger.error(
                        f"Task for query '{query_for_error}' failed with exception: {result}",
                        exc_info=result,
                    )
                elif isinstance(result, asyncio.CancelledError):
                    logger.warning(
                        f"Task {i} was cancelled (likely due to target being reached)."
                    )

        final_fetched = self.fetched  # Read final count
        logger.info(
            f"✔ Crawl attempt finished. Total repositories fetched: {final_fetched}/{self.target}"
        )
        if final_fetched >= self.target:
            logger.info("Target successfully reached.")
        else:
            logger.warning(
                f"Target ({self.target}) not reached. Fetched {final_fetched}."
            )
