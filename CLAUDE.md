# EventPulse Backend

## Project
EventPulse — Production-grade event management and ticketing platform.
Tech: FastAPI (Python 3.12+), PostgreSQL 16, SQLAlchemy 2.0 + Alembic, Redis, Docker.

## Architecture
Feature-based architecture. Each business domain is a self-contained module under app/features/ with: models.py, schemas.py, crud.py, services.py, router.py.

## Coding Standards
- Python 3.12+ with type hints on every function parameter and return type
- Async/await for all database operations
- Docstrings on every class and every public function
- No hardcoded values — use config.py (Pydantic Settings)
- Cross-feature access goes through services.py, never directly through crud.py
- Models CAN be imported across features only for SQLAlchemy relationship definitions
- All endpoints must have proper error handling with custom HTTP exceptions
- All inputs must be validated through Pydantic schemas

## Commit Message Format
type(scope): short description

Types: feat, fix, chore, refactor, test, docs
Scope: the feature name (auth, users, events, orders, payments, etc.)
Rules: lowercase, no period at end, max 72 characters

Examples:
- feat(auth): add login and register endpoints
- fix(orders): prevent duplicate order creation
- test(tickets): add availability edge case tests
- chore(docker): add mailhog service to compose

## Branch Naming
- feature/auth-register-login
- feature/events-crud
- fix/order-race-condition
- chore/docker-setup

One feature per branch. Never mix features in one branch.

## PR Rules
- Title follows commit message format
- Description lists: what was built, endpoints added, tables created/modified, tests added
- All tests must pass
- Code review must pass
- Security review must pass
- No direct commits to main — always use feature branches

## Testing
- Framework: pytest + pytest-asyncio
- Structure: tests/features/test_<feature>.py (mirrors app/features/)
- Every feature must have tests covering: success cases, validation errors, auth failures, authorization failures, not-found cases, edge cases
- Use factory-boy for test data
- Use httpx.AsyncClient for API tests
- ALL test cases MUST pass before committing

## Alembic
- Create migration after any model creation or modification
- Always run: alembic revision --autogenerate -m "description"
- Always run: alembic upgrade head
- Verify migration before committing
- Migration must be included in the same branch as the feature

## Docker
- docker-compose.yml runs: PostgreSQL 16, Redis, pgAdmin, MailHog
- Start: docker-compose up -d
- Docker Desktop app is available on this Windows machine
