"""Application settings, read from environment variables prefixed with HUBNISIO_."""

from functools import lru_cache
from pathlib import Path

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

    # The user the API acts as until passkey login exists (see core/auth.py).
    dev_user_email: str | None = None

    # Secret files. Compose mounts them under /run/secrets; the defaults suit running in backend/.
    # AES-GCM keys for provider secrets, one "v<n>:<base64 key>" per line (see core/crypto.py).
    encryption_keys_file: Path = Path("../secrets/encryption-keys")
    enable_banking_key_file: Path = Path("../secrets/enable-banking.pem")
    # Where `cli ai-login` writes each member's AI connection string (ADR-0006), one file per
    # login. Compose bind-mounts secrets/ai there, since the command writes it.
    ai_secrets_dir: Path = Path("../secrets/ai")
    # Trading 212 API keys (ADR-0008), one file per account; a connection names its file.
    trading212_keys_dir: Path = Path("../secrets/trading212")
    # Garmin personal API keys (ADR-0009), one file per member; a health connection names its file.
    garmin_keys_dir: Path = Path("../secrets/garmin")
    # The MCP server (hubnisio.ai): the kill switch, and the member login it connects as (one of
    # the files above). It never uses database_url.
    ai_enabled: bool = False
    ai_dsn_file: Path | None = None

    # Enable Banking (ADR-0003): the application ID (the name of its .pem key file), and the URL the
    # bank sends the browser back to after authorization (https; allowed in the Control Panel).
    enable_banking_app_id: str | None = None
    enable_banking_redirect_url: str = "https://localhost:5173/finance/connections/callback"

    @property
    def sqlalchemy_url(self) -> str:
        """The database URL with the psycopg driver selected, as SQLAlchemy expects it."""
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  # filled from the environment
