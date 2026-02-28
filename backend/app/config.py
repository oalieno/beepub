from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    redis_url: str = "redis://redis:6379"
    secret_key: str
    access_token_expire_minutes: int = 30
    books_dir: str = "/data/books"
    covers_dir: str = "/data/covers"

    class Config:
        env_file = ".env"


settings = Settings()
