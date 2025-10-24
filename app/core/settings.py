from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    openai_api_key: str
    vector_store_id: str
    redis_url: str | None = None
    supabase_jwks_url: str | None = None
    supabase_jwt_audience: str | None = None
    supabase_jwt_issuer: str | None = None
    supabase_jwt_secret: str | None = None
    debug: bool = False
    log_level: str = "info"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
