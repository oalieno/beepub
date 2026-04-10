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
    # localhost dev origins are always allowed automatically.
    cors_origins: str = ""
    dev: bool = False

    @property
    def cors_allowed_origins(self) -> list[str]:
        # Native iOS/Android Capacitor apps and the reverse proxy itself.
        origins: list[str] = [
            "capacitor://localhost",
            "ionic://localhost",
            "http://localhost",
            "https://localhost",
        ]
        if self.dev:
            origins += [
                "http://localhost:5173",
                "http://localhost:80",
                "http://localhost:8080",
            ]
        if self.cors_origins:
            origins += [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return origins


settings = Settings()
