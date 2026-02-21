from functools import lru_cache
import os


class Settings:
    def __init__(self) -> None:
        self.api_prefix = os.getenv("API_PREFIX", "/api/v1")
        self.environment = os.getenv("ENVIRONMENT", "development")
        self.app_name = os.getenv("APP_NAME", "aws-cost-optimizer-api")
        self.cors_origins = self._parse_cors_origins()

    def _parse_cors_origins(self) -> list[str]:
        raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
        origins = [item.strip() for item in raw.split(",") if item.strip()]
        return origins or ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
