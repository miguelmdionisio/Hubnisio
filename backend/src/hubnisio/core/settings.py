"""Application settings, read from environment variables prefixed with HUBNISIO_."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HUBNISIO_",
        env_file=("../.env", ".env"),
        extra="ignore",
    )

    environment: str = "development"
    # libpq form (postgresql://user:password@host:port/db); used as-is by the job queue.
    database_url: str

    @property
    def sqlalchemy_url(self) -> str:
        """The database URL with the psycopg driver selected, as SQLAlchemy expects it."""
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  # filled from the environment
