from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str
    redis_url: str = "redis://redis:6379"
    secret_key: str
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    books_dir: str = "/data/books"
    covers_dir: str = "/data/covers"
    illustrations_dir: str = "/data/illustrations"

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


settings = Settings()
