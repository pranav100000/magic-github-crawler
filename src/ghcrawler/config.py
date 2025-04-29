from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App-wide configuration pulled from environment variables or .env."""

    # Database
    db_user: str = "crawler"
    db_password: str = "crawler"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "ghstars"

    # GitHub
    github_token: str
    github_graphql_endpoint: str = "https://api.github.com/graphql"
    request_concurrency: int = 10

    # Rate‑limit bucket (Based on GitHub's standard 5000 points/hour GraphQL limit)
    bucket_capacity: int = 200
    bucket_refill_per_hour: int = 5000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache()
def get_settings() -> Settings:  # pragma: no cover
    return Settings()
