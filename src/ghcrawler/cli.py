import typer
import asyncio
from ghcrawler.core.crawler import AsyncCrawler

app = typer.Typer()


@app.command()
def crawl_stars(limit: int = 100_000, batch: int = 100):
    """Crawl GitHub stars for <limit> repositories."""
    asyncio.run(AsyncCrawler(target=limit, batch=batch).run())


if __name__ == "__main__":
    app()
