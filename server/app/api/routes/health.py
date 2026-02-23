from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.settings import get_settings


router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
    timestamp: str


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

