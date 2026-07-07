import logging
import secrets
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str
    redis_url: str = "redis://redis:6379"
    # Baked into the Docker image by CI; "dev" when running from source
    app_version: str = "dev"
    # JWT signing secret. Leave unset to auto-generate one on first start,
    # persisted at secret_key_file (a shared volume in docker-compose, so
    # every backend-image service signs with the same key). The migrate
    # service runs alone before the others start, so generation is race-free.
    secret_key: str = ""
    secret_key_file: str = "/data/app/secret_key"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    books_dir: str = "/data/books"
    covers_dir: str = "/data/covers"
    illustrations_dir: str = "/data/illustrations"

    # Demo-instance login hint, shown on the login page when demo_mode is
    # on. The flag grants no access by itself: no account is created and no
    # auth is bypassed — the operator creates the demo account manually and
    # chooses to publish its credentials here. It also locks the demo
    # account's password so visitors can't lock each other out.
    demo_mode: bool = False
    demo_username: str = "demo"
    demo_password: str = ""

    # Comma-separated list of additional web origins allowed by CORS, e.g.
    # "https://beepub.example.com,https://reader.example.com". Capacitor and
    # localhost origins are always allowed automatically.
    cors_origins: str = ""

    @property
    def cors_allowed_origins(self) -> list[str]:
        # Native iOS/Android Capacitor apps. Browser localhost origins are
        # handled by cors_allowed_origin_regex so any local dev port works.
        origins: list[str] = [
            "capacitor://localhost",
            "ionic://localhost",
        ]
        if self.cors_origins:
            origins += [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return origins

    @property
    def cors_allowed_origin_regex(self) -> str:
        return r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"

    @model_validator(mode="after")
    def _resolve_secret_key(self) -> "Settings":
        if self.secret_key:
            return self
        path = Path(self.secret_key_file)
        try:
            self.secret_key = path.read_text().strip()
            if self.secret_key:
                return self
        except FileNotFoundError:
            pass
        except OSError as err:
            raise RuntimeError(
                f"SECRET_KEY is not set and {path} is unreadable ({err}); "
                "set SECRET_KEY explicitly"
            ) from err
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.secret_key = secrets.token_hex(32)
            path.write_text(self.secret_key)
            path.chmod(0o600)
        except OSError as err:
            raise RuntimeError(
                f"SECRET_KEY is not set and a generated one could not be "
                f"persisted to {path} ({err}); set SECRET_KEY explicitly"
            ) from err
        logger.info("Generated new SECRET_KEY, persisted to %s", path)
        return self


settings = Settings()
