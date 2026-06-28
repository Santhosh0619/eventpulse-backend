# EventPulse Backend — Progress Tracker

## Current Status
- Phase: 5 (Ticketing & Orders) — STARTING
- Last completed: Phase 4 COMPLETE (categories, events, media); PR #6 merged (2f2014b)
- Next step: `tickets` feature, then `orders`

## Completed Phases
- Phase 0 — Automation infrastructure + project foundation
- Phase 2 — Authentication & User Management (auth, users)
- Phase 3 — Organization Management (organizations)
- Phase 4 — Event Management & Categories (categories, events, media)

## Completed Features
- **auth** (Phase 2) — PR #1.
- **users** (Phase 2) — PR #2.
- **organizations** (Phase 3) — PR #3.
- **categories** (Phase 4) — admin CRUD + seeding. PR #4.
- **events** (Phase 4) — lifecycle, search, publish/cancel. PR #5.
- **media** (Phase 4) — upload/list/delete/reorder. PR #6.

## Merged Branches
- feature/auth (#1), feature/users (#2), feature/organizations (#3),
  feature/categories (#4), feature/events (#5), feature/media (#6)

## Created Tables (8 of 15)
- users, user_profiles, organizations, organization_members,
  categories, events, event_media (+ alembic_version)

## Reminder
- ALWAYS `git checkout -b feature/<name>` BEFORE writing code (caught a slip on events).

## Active Endpoints
- GET  /api/v1/health
- POST /api/v1/auth/{register,login,refresh,verify-email,forgot-password,reset-password,logout}
- GET/PUT /api/v1/users/me
- GET  /api/v1/users/{id}
- PUT  /api/v1/users/me/avatar

## Created Tables
- users (Table 1), user_profiles (Table 2)

## Environment Notes
- Everything runs in Docker (container python:3.12-slim). NO local venv.
- Run: `docker compose run --rm api <cmd>` (pytest, alembic, ruff). API at localhost:8000.
- gh CLI not on tool-shell PATH; prefix PowerShell with the registry PATH refresh.
- Migrations are incremental (one per feature). bcrypt pinned 4.0.1 (passlib compat).
- Autonomous build mode: no text permission questions; mobile hook gates tool calls.
- Deferred: PUT /users/me/fcm-token -> Phase 7.
