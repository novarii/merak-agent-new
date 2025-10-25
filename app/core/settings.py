from pydantic import Field, field_validator
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
    cors_origins: list[str] = Field(default_factory=list)

    class Config:
        env_file = ".env"
        case_sensitive = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: str | list[str] | None) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


settings = Settings()
