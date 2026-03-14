# Contributing to AWS Cost Optimizer

Thank you for your interest in contributing. This guide will help you get started.

## Getting Started

### Prerequisites

- Python 3.11+ (3.13 recommended)
- Node.js 22+
- Rust stable (for desktop builds only)

### Local Setup

```bash
# Backend
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
make run

# Frontend
cd client
npm ci
npm run dev
```

### Running Tests

```bash
cd server
make test           # All tests
make test-unit      # Unit tests only
make test-integration  # Integration tests only
make test-cov       # With coverage (80% minimum enforced)
```

## How to Contribute

### Reporting Bugs

Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md) issue template. Include:
- Steps to reproduce
- Expected vs actual behavior
- Platform and version information
- Relevant logs or screenshots

### Suggesting Features

Use the [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md) issue template. Describe:
- The problem your feature would solve
- Your proposed solution
- Any alternatives you've considered

### Submitting Code

1. Fork the repository
2. Create a feature branch from `dev`: `git checkout -b feat/my-feature dev`
3. Make your changes
4. Add tests for new functionality
5. Run the full test suite: `make test-cov`
6. Run the pre-push check: `bash scripts/prepush_check.sh --full`
7. Commit with a descriptive message following [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat:` new features
   - `fix:` bug fixes
   - `test:` adding or updating tests
   - `docs:` documentation changes
   - `refactor:` code changes that neither fix bugs nor add features
   - `ci:` CI/CD changes
8. Push and open a Pull Request against `dev`

## Code Standards

### Python (Backend)

- Type hints on all function signatures
- Pydantic models for all data contracts
- No `# type: ignore` without a comment explaining why
- Follow existing patterns in the codebase

### TypeScript (Frontend)

- Strict mode enabled — no `any` types
- Interfaces in `types.ts` must mirror Pydantic models in `contracts.py`
- Functional components with hooks (no class components)

### Tests

- Every new feature needs unit tests
- API changes need integration tests
- Coverage must stay at or above 80%
- Use `pytest.approx()` for floating-point comparisons
- Use the existing fixtures (`s3_mock`, `tmp_store`, `client`) — don't create parallel infrastructure

## Adding a New Recommendation Type

This is the most common type of contribution. The steps are:

1. Add an enum value to `RecommendationType` in `server/app/models/contracts.py`
2. Add scanner logic in `server/app/scanner/service.py`
3. Add scoring factors in `server/app/scoring/service.py`:
   - `REVERSIBILITY_SCORES` entry
   - `_data_loss_risk()` case
   - Savings calculation handler
4. Add execution logic in `server/app/executor/service.py`:
   - `REQUIRED_PERMISSIONS` entry
   - `_execute_action()` handler
   - Pre/post state capture handlers
5. If reversible: add to `REVERSIBLE_ACTIONS` and add a handler in `server/app/executor/rollback.py`
6. Add the TypeScript type to `client/src/types.ts`
7. Add unit and integration tests

## Project Structure

See [docs/Onboarding and Contributing Guide.md](docs/Onboarding%20and%20Contributing%20Guide.md) for a detailed project map.

## Questions?

Open a [Discussion](https://github.com/celestinryf/AWS-Cost-Optimizer/discussions) or reach out via an issue.
