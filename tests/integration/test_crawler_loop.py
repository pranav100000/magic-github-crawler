from dotenv import load_dotenv
import os
import pytest
import vcr
from ghcrawler.core.crawler import AsyncCrawler

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
pytestmark = pytest.mark.skipif(not TOKEN, reason="GITHUB_TOKEN not set")

my_vcr = vcr.VCR(path_transformer=vcr.VCR.ensure_suffix(".yaml"))


@my_vcr.use_cassette("crawler_two_pages.yaml")
@pytest.mark.asyncio
async def test_crawl_two_pages():
    crawler = AsyncCrawler(target=200, batch=100)  # 2 pages
    await crawler.run()
    assert crawler.fetched >= 200
