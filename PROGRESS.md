# EventPulse Backend — Progress Tracker

## Current Status
- Phase: 7 (Reviews & Notifications) — IN PROGRESS
- Last completed: `reviews` feature merged (PR #11). `notifications` feature CODE WRITTEN
  on branch `feature/notifications` but NOT yet verified/reviewed/merged.
- PAUSED here (WIP commit on feature/notifications).

### Resume steps for `notifications` (next session)
1. `git checkout feature/notifications`
2. Run: `docker compose run --rm api sh -c "ruff format . && ruff check . && pytest tests/ -q"`
   (notifications tests were written but NEVER RUN — expect possible fixes)
3. Fix any failures, then run code+security review subagent, apply fixes
4. Commit, push, open PR #12, review, squash-merge, sync main, update PROGRESS
5. Then Phase 8 (analytics, recommendations, admin), Phase 9 (hardening), then web, then mobile

### What the notifications feature already includes (written, unverified)
- Notification model (Table 13, no updated_at) + migration 37ce071de6f6 (APPLIED to dev DB)
- GET /notifications, GET /notifications/unread-count, PUT /notifications/{id}/read,
  PUT /notifications/read-all
- send_notification() with best-effort FCM (firebase, lazy/guarded) + email dispatch
- PUT /users/me/fcm-token (deferred from Phase 2) added to users feature
- Triggers wired: order_confirmed (payments webhook), review_reply (reviews respond)
- dispatch_event_reminders() + daily 9AM cron job in utils/scheduler.py
- tests/features/test_notifications.py written (endpoints, fcm, review_reply trigger, reminders)
- main.py: notifications_router already registered from Phase 0; verify it imports cleanly

## Completed Phases
- Phase 0 — Automation infrastructure + project foundation
- Phase 2 — Authentication & User Management (auth, users)
- Phase 3 — Organization Management (organizations)
- Phase 4 — Event Management & Categories (categories, events, media)
- Phase 5 — Ticketing & Orders (tickets, orders) — concurrency-safe, APScheduler expiry
- Phase 6 — Payments & Attendees (attendees, payments/Stripe) — webhook fulfillment

## Completed Features
- **auth** (Phase 2, PR #1), **users** (Phase 2, PR #2)
- **organizations** (Phase 3, PR #3)
- **categories** (PR #4), **events** (PR #5), **media** (PR #6) — Phase 4
- **tickets** (PR #7) — tiers, availability, atomic reserve/release
- **orders** (PR #8) — pipeline, cancel, expiry scheduler, concurrency test
- **attendees** (PR #9) — QR ticket gen, check-in, stats, CSV export
- **payments** (PR #10) — Stripe intents, webhook fulfillment, refunds; place_order now PENDING

## Merged Branches
- #1 auth, #2 users, #3 organizations, #4 categories, #5 events, #6 media,
  #7 tickets, #8 orders, #9 attendees, #10 payments

## Created Tables (13 of 15)
- users, user_profiles, organizations, organization_members, categories, events,
  event_media, ticket_types, orders, order_items, attendees, payments
- Remaining: reviews, notifications (Phase 7), audit_logs (Phase 8). Migration head: a0e21a3d3e74
- 152 tests passing. APScheduler runs cleanup_expired_orders every 60s.

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
