.PHONY: install install-dev deps-lock deps-check test test-unit test-integration test-cov run build docker-run clean

# Prefer the repo-root .venv, then a local venv, then whatever python3 is on PATH.
VENV     := $(wildcard ../.venv/bin/python3 venv/bin/python3)
PYTHON   := $(if $(VENV),$(firstword $(VENV)),python3)
PIP      := $(PYTHON) -m pip
PYTEST   := $(PYTHON) -m pytest
UVICORN  := $(PYTHON) -m uvicorn
PIP_COMPILE := pip-compile

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements-dev.txt

deps-lock:
	CUSTOM_COMPILE_COMMAND="pip-compile --strip-extras requirements.in" \
		$(PIP_COMPILE) --quiet --strip-extras requirements.in -o requirements.txt
	CUSTOM_COMPILE_COMMAND="pip-compile --strip-extras requirements-dev.in" \
		$(PIP_COMPILE) --quiet --strip-extras requirements-dev.in -o requirements-dev.txt
	CUSTOM_COMPILE_COMMAND="pip-compile --strip-extras requirements-bundle.in" \
		$(PIP_COMPILE) --quiet --strip-extras requirements-bundle.in -o requirements-bundle.txt

deps-check:
	@set -eu; \
	tmp_dir="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmp_dir"' EXIT; \
	cp requirements.txt "$$tmp_dir/requirements.txt"; \
	cp requirements-dev.txt "$$tmp_dir/requirements-dev.txt"; \
	cp requirements-bundle.txt "$$tmp_dir/requirements-bundle.txt"; \
	CUSTOM_COMPILE_COMMAND="pip-compile --strip-extras requirements.in" \
		$(PIP_COMPILE) --quiet --strip-extras requirements.in -o requirements.txt; \
	CUSTOM_COMPILE_COMMAND="pip-compile --strip-extras requirements-dev.in" \
		$(PIP_COMPILE) --quiet --strip-extras requirements-dev.in -o requirements-dev.txt; \
	CUSTOM_COMPILE_COMMAND="pip-compile --strip-extras requirements-bundle.in" \
		$(PIP_COMPILE) --quiet --strip-extras requirements-bundle.in -o requirements-bundle.txt; \
	status=0; \
	if ! diff -u "$$tmp_dir/requirements.txt" requirements.txt; then status=1; fi; \
	if ! diff -u "$$tmp_dir/requirements-dev.txt" requirements-dev.txt; then status=1; fi; \
	if ! diff -u "$$tmp_dir/requirements-bundle.txt" requirements-bundle.txt; then status=1; fi; \
	if [[ "$$status" -ne 0 ]]; then \
		echo "Dependency lockfiles changed. Run 'make deps-lock' and commit the updated lockfiles."; \
		exit 1; \
	fi

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
