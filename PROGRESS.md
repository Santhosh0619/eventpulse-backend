# EventPulse Backend — Progress Tracker

## Current Status
- Phase: 2 (Authentication & User Management) — IN PROGRESS
- Last completed: `auth` feature (PR #1 merged, squash af68c4b)
- Next step: `users` feature (profile CRUD, avatar upload)

## Completed Phases
- Phase 0 — Automation infrastructure + project foundation

## Completed Features
- **auth** (Phase 2) — register, login, refresh, verify-email, forgot/reset-password, logout.
  Models: User, UserProfile. Migration 7b48f1058945. 27 tests. PR #1.

## Merged Branches
- feature/auth -> main (PR #1, squash)

## Active Endpoints
- GET  /api/v1/health
- POST /api/v1/auth/register
- POST /api/v1/auth/login
- POST /api/v1/auth/refresh
- POST /api/v1/auth/verify-email
- POST /api/v1/auth/forgot-password
- POST /api/v1/auth/reset-password
- POST /api/v1/auth/logout

## Created Tables
- users (Table 1)
- user_profiles (Table 2)

## Environment Notes
- Everything runs in Docker (container python:3.12-slim). NO local venv.
- Run: `docker compose run --rm api <cmd>` (pytest, alembic, ruff). API at localhost:8000.
- gh CLI not on tool-shell PATH; prefix PowerShell with the registry PATH refresh.
- Migrations are incremental (one per feature). bcrypt pinned 4.0.1 (passlib compat).
- Autonomous build mode: no text permission questions; mobile hook gates tool calls.
