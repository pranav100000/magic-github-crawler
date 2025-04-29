from dotenv import load_dotenv
import os, pytest, asyncio, vcr
from ghcrawler.api import GithubClient

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
pytestmark = pytest.mark.skipif(not TOKEN, reason="GITHUB_TOKEN not set")

my_vcr = vcr.VCR(path_transformer=vcr.VCR.ensure_suffix(".yaml"))

@my_vcr.use_cassette("github_search.yaml")
@pytest.mark.asyncio
async def test_search_repos():
    async with GithubClient(TOKEN) as gh:
        page = await gh.search_repos(batch=10)
    assert len(page.repos) == 10
    assert page.cost >= 1