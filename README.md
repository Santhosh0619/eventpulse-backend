# EventPulse Backend

Production-grade event management and ticketing platform — FastAPI backend.

EventPulse enables organizations to create, manage, and sell tickets for events while
providing attendees with a seamless discovery, booking, and check-in experience. This
repository is the high-performance API layer that powers the web dashboard and the
mobile app.

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI (Python 3.12+) |
| Database | PostgreSQL 16 |
| ORM / Migrations | SQLAlchemy 2.0 (async) + Alembic |
| Caching | Redis |
| Background Jobs | APScheduler |
| Payments | Stripe |
| Push Notifications | Firebase Cloud Messaging (FCM) |
| Email | aiosmtplib + Jinja2 (MailHog in dev) |
| File Storage | Local filesystem (`uploads/`) |
| Auth | JWT (access + refresh tokens), bcrypt |
| Containerization | Docker + Docker Compose |
| Testing | pytest + pytest-asyncio + factory-boy |

## Architecture

Feature-based architecture. Each business domain is a self-contained module under
`app/features/` with its own `models.py`, `schemas.py`, `crud.py`, `services.py`, and
`router.py`. Cross-cutting concerns live in `app/core/` and shared utilities in
`app/shared/`.

## Getting Started

```bash
# 1. Clone the repository
git clone https://github.com/Santhosh0619/eventpulse-backend.git
cd eventpulse-backend

# 2. Create your .env file from the example and fill in secrets
cp .env.example .env

# 3. Start infrastructure (PostgreSQL, Redis, pgAdmin, MailHog)
docker-compose up -d

# 4. Create a virtual environment and install dependencies
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows
pip install -r requirements.txt -r requirements-dev.txt

# 5. Apply database migrations
alembic upgrade head

# 6. Run the API
uvicorn app.main:app --reload --port 8000
```

API docs are available at http://localhost:8000/docs once running.
Health check: http://localhost:8000/api/v1/health

## Project Structure

See `CLAUDE.md` for full conventions, the feature architecture rules, and coding
standards. Development progress is tracked in `PROGRESS.md`.
