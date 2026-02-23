.PHONY: install install-dev test test-unit test-integration test-cov run build docker-run clean

# Prefer the repo-root .venv, then a local venv, then whatever python3 is on PATH.
VENV     := $(wildcard ../.venv/bin/python3 venv/bin/python3)
PYTHON   := $(if $(VENV),$(firstword $(VENV)),python3)
PIP      := $(PYTHON) -m pip
PYTEST   := $(PYTHON) -m pytest
UVICORN  := $(PYTHON) -m uvicorn

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements-dev.txt

# Run all tests
test:
	$(PYTEST) tests/ -v

# Unit tests only (no I/O, fast)
test-unit:
	$(PYTEST) tests/unit -m unit -v

# Integration tests (TestClient + real SQLite in temp dir)
test-integration:
	$(PYTEST) tests/integration -m integration -v

# Full test run with coverage report (fails under 80%)
test-cov:
	$(PYTEST) tests/ \
		--cov=app \
		--cov-report=term-missing \
		--cov-report=xml:coverage.xml \
		--cov-fail-under=80

# Run the dev server with hot-reload
run:
	$(UVICORN) app.main:app --reload --port 8000

# Build the Docker image
build:
	docker build -t aws-cost-optimizer-api:local .

# Run via docker-compose (creates .env from .env.example if missing)
docker-run:
	@[ -f .env ] || cp .env.example .env
	docker compose up --build

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete 2>/dev/null; true
	rm -f coverage.xml .coverage
