from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    redis_url: str = "redis://redis:6379"
    secret_key: str
    access_token_expire_minutes: int = 10080  # 7 days
    books_dir: str = "/data/books"
    covers_dir: str = "/data/covers"
    illustrations_dir: str = "/data/illustrations"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-exp"
    llm_provider: str = "gemini"

    class Config:
        env_file = ".env"


settings = Settings()
