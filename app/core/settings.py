from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    openai_api_key: str
    vector_store_id: str
    debug: bool = False
    log_level: str = "info"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()