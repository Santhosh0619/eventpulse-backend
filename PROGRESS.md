# EventPulse Backend — Progress Tracker

## Current Status
- Phase: 6 (Payments & Attendees) — STARTING
- Last completed: Phase 5 COMPLETE (tickets, orders); PR #8 merged (4d729a1)
- Next step: `payments` feature (Stripe), then `attendees` (QR check-in)

## Completed Phases
- Phase 0 — Automation infrastructure + project foundation
- Phase 2 — Authentication & User Management (auth, users)
- Phase 3 — Organization Management (organizations)
- Phase 4 — Event Management & Categories (categories, events, media)
- Phase 5 — Ticketing & Orders (tickets, orders) — concurrency-safe, APScheduler expiry

## Completed Features
- **auth** (Phase 2, PR #1), **users** (Phase 2, PR #2)
- **organizations** (Phase 3, PR #3)
- **categories** (PR #4), **events** (PR #5), **media** (PR #6) — Phase 4
- **tickets** (PR #7) — tiers, availability, atomic reserve/release
- **orders** (PR #8) — pipeline, mock confirm, cancel, expiry scheduler, concurrency test

## Merged Branches
- #1 auth, #2 users, #3 organizations, #4 categories, #5 events, #6 media,
  #7 tickets, #8 orders

## Created Tables (11 of 15)
- users, user_profiles, organizations, organization_members, categories, events,
  event_media, ticket_types, orders, order_items (+ alembic_version)
- Remaining: payments, attendees (Phase 6), reviews, notifications (Phase 7),
  audit_logs (Phase 8)

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
