"""Edge-case unit tests for Settings / CORS origin parsing.

Settings uses an lru_cache'd factory (get_settings). The conftest autouse
fixture clears the cache before/after every test, so monkeypatching CORS_ORIGINS
always takes effect.
"""

import pytest
from app.core.settings import Settings


@pytest.mark.unit
class TestCorsOriginsParsing:
    def test_default_includes_localhost_3000(self):
        """Default value includes the standard dev origins."""
        settings = Settings()
        assert "http://localhost:3000" in settings.cors_origins
        assert "http://127.0.0.1:3000" in settings.cors_origins

    def test_default_includes_tauri_origins(self):
        settings = Settings()
        assert "tauri://localhost" in settings.cors_origins
        assert "https://tauri.localhost" in settings.cors_origins

    def test_default_includes_vite_dev_server(self):
        settings = Settings()
        assert "http://localhost:1420" in settings.cors_origins
        assert "http://127.0.0.1:1420" in settings.cors_origins

    def test_custom_single_origin(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "http://example.com")
        settings = Settings()
        assert settings.cors_origins == ["http://example.com"]

    def test_custom_multiple_origins_parsed_correctly(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "http://a.com,http://b.com,http://c.com")
        settings = Settings()
        assert settings.cors_origins == ["http://a.com", "http://b.com", "http://c.com"]

    def test_leading_and_trailing_spaces_stripped(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", " http://a.com , http://b.com ")
        settings = Settings()
        assert "http://a.com" in settings.cors_origins
        assert "http://b.com" in settings.cors_origins

    def test_empty_string_falls_back_to_default(self, monkeypatch):
        """Empty CORS_ORIGINS env var → fallback to ['http://localhost:3000']."""
        monkeypatch.setenv("CORS_ORIGINS", "")
        settings = Settings()
        assert settings.cors_origins == ["http://localhost:3000"]

    def test_commas_only_falls_back_to_default(self, monkeypatch):
        """A string of only commas produces no valid origins → fallback."""
        monkeypatch.setenv("CORS_ORIGINS", ",,,")
        settings = Settings()
        assert settings.cors_origins == ["http://localhost:3000"]

    def test_spaces_only_falls_back_to_default(self, monkeypatch):
        """Whitespace-only value → all items empty after strip → fallback."""
        monkeypatch.setenv("CORS_ORIGINS", "   ,   ,   ")
        settings = Settings()
        assert settings.cors_origins == ["http://localhost:3000"]

    def test_mixed_valid_and_blank_entries_ignores_blanks(self, monkeypatch):
        """Blank items (from double-commas) are filtered out."""
        monkeypatch.setenv("CORS_ORIGINS", "http://a.com,,http://b.com")
        settings = Settings()
        assert settings.cors_origins == ["http://a.com", "http://b.com"]

    def test_no_cors_origins_env_returns_six_default_origins(self):
        """Without any env override, should have 6 default origins."""
        settings = Settings()
        assert len(settings.cors_origins) == 6


@pytest.mark.unit
class TestOtherSettings:
    def test_default_api_prefix(self):
        settings = Settings()
        assert settings.api_prefix == "/api/v1"

    def test_custom_api_prefix(self, monkeypatch):
        monkeypatch.setenv("API_PREFIX", "/api/v2")
        settings = Settings()
        assert settings.api_prefix == "/api/v2"

    def test_default_environment(self):
        settings = Settings()
        assert settings.environment == "development"

    def test_custom_environment(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        settings = Settings()
        assert settings.environment == "production"

    def test_default_app_name(self):
        settings = Settings()
        assert settings.app_name == "aws-cost-optimizer-api"

    def test_custom_app_name(self, monkeypatch):
        monkeypatch.setenv("APP_NAME", "my-custom-app")
        settings = Settings()
        assert settings.app_name == "my-custom-app"
