"""
Shared test fixtures for unit and integration tests.

Key design decision:
  app/api/routes/optimizer.py does `from app.dependencies import run_store`.
  That binds a local name at import time. Patching `app.dependencies.run_store`
  afterwards does NOT affect the already-bound reference inside the routes module.
  Both locations must be patched independently.
"""

import boto3
import pytest
from moto import mock_aws
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import create_app
from app.state.store import RunStore
from app.scanner.service import ScannerService
from app.scoring.service import ScoringService
from app.executor.service import ExecutionService
from app.executor.rollback import RollbackService


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """Set fake AWS credentials so boto3 clients don't fail to initialize."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(autouse=True)
def s3_mock(aws_credentials):
    """Wrap every test in a moto S3 mock with pre-populated test resources.

    moto patches at the HTTP intercept layer, so all boto3 clients (including
    lazily created and cached module-level ones) route to this backend.
    Each test starts with a fresh, isolated S3 state.
    """
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        # Objects referenced by executor and rollback unit tests
        s3.put_object(Bucket="test-bucket", Key="test/key.parquet", Body=b"x" * 1024)
        s3.put_object(Bucket="test-bucket", Key="test/key", Body=b"x" * 512)
        yield s3


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the lru_cache on get_settings() before/after each test so that
    monkeypatch.setenv changes to API_PREFIX, CORS_ORIGINS, etc. take effect."""
    from app.core.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def tmp_store(tmp_path):
    """
    Fresh SQLite-backed RunStore per test.

    Uses a temp file (not ':memory:') because RunStore opens a new connection
    per operation — SQLite ':memory:' creates a fresh database per connection,
    so data would be lost between calls.
    """
    return RunStore(db_path=str(tmp_path / "runs.db"))


@pytest.fixture()
def client(tmp_store):
    """
    FastAPI TestClient with all module-level singletons replaced.

    Patches both `app.dependencies.*` AND `app.api.routes.optimizer.*`
    because the route module holds its own import-time binding that is
    independent of the source in app.dependencies.
    """
    with (
        patch("app.dependencies.run_store", tmp_store),
        patch("app.api.routes.optimizer.run_store", tmp_store),
        patch("app.dependencies.scanner_service", ScannerService()),
        patch("app.api.routes.optimizer.scanner_service", ScannerService()),
        patch("app.dependencies.scoring_service", ScoringService()),
        patch("app.api.routes.optimizer.scoring_service", ScoringService()),
        patch("app.dependencies.execution_service", ExecutionService()),
        patch("app.api.routes.optimizer.execution_service", ExecutionService()),
        patch("app.dependencies.rollback_service", RollbackService()),
        patch("app.api.routes.optimizer.rollback_service", RollbackService()),
    ):
        with TestClient(create_app(), raise_server_exceptions=True) as tc:
            yield tc


# ---------------------------------------------------------------------------
# Env-var helpers for executor / rollback unit tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def no_permissions(monkeypatch):
    """Strip all granted executor permissions."""
    monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "")


@pytest.fixture()
def allow_destructive(monkeypatch):
    """Allow DELETE_STALE_OBJECT actions."""
    monkeypatch.setenv("ALLOW_DESTRUCTIVE_EXECUTION", "true")


@pytest.fixture()
def deny_destructive(monkeypatch):
    """Block DELETE_STALE_OBJECT actions (the default)."""
    monkeypatch.setenv("ALLOW_DESTRUCTIVE_EXECUTION", "false")
