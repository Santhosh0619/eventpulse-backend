# EventPulse Backend — Progress Tracker

## Current Status
- Phase: 7 (Reviews & Notifications) — COMPLETE (pending PR #12 merge)
- Last completed: `notifications` feature verified, reviewed, and ready to merge (PR #12).
- Next: Phase 8 (analytics, recommendations, admin = audit_logs table), then Phase 9
  (caching/rate-limiting/security hardening), then web repo, then mobile repo.

### notifications feature (DONE)
- Notification model (Table 13, no updated_at) + migration 37ce071de6f6 (APPLIED to dev DB)
- GET /notifications, GET /notifications/unread-count, PUT /notifications/{id}/read,
  PUT /notifications/read-all
- send_notification() with best-effort FCM (firebase, lazy/guarded, off-event-loop via
  asyncio.to_thread) + email dispatch (autoescaped Jinja2 notification.html template)
- PUT /users/me/fcm-token (deferred from Phase 2) added to users feature; rejects whitespace
- Triggers wired: order_confirmed (payments webhook), review_reply (reviews respond)
- dispatch_event_reminders() + daily 9AM cron job in utils/scheduler.py; idempotent (dedups
  already-reminded attendees), single batched commit
- NotificationType enum added to shared/enums.py
- Review fixes applied: notification CRUD now flushes (commit=False) when called inside the
  payments transaction so order-confirm + ticket-issue + notification stay atomic
- DEFERRED to Phase 9: API rate limiting (no limiter exists anywhere yet)

## Completed Phases
- Phase 0 — Automation infrastructure + project foundation
- Phase 2 — Authentication & User Management (auth, users)
- Phase 3 — Organization Management (organizations)
- Phase 4 — Event Management & Categories (categories, events, media)
- Phase 5 — Ticketing & Orders (tickets, orders) — concurrency-safe, APScheduler expiry
- Phase 6 — Payments & Attendees (attendees, payments/Stripe) — webhook fulfillment
- Phase 7 — Reviews & Notifications (reviews, notifications) — multi-channel dispatch, reminders

## Completed Features
- **auth** (Phase 2, PR #1), **users** (Phase 2, PR #2)
- **organizations** (Phase 3, PR #3)
- **categories** (PR #4), **events** (PR #5), **media** (PR #6) — Phase 4
- **tickets** (PR #7) — tiers, availability, atomic reserve/release
- **orders** (PR #8) — pipeline, cancel, expiry scheduler, concurrency test
- **attendees** (PR #9) — QR ticket gen, check-in, stats, CSV export
- **payments** (PR #10) — Stripe intents, webhook fulfillment, refunds; place_order now PENDING
- **reviews** (PR #11) — verified-attendee reviews, summaries, organizer responses, moderation
- **notifications** (PR #12) — multi-channel dispatch, fcm-token, triggers, daily reminders

## Merged Branches
- #1 auth, #2 users, #3 organizations, #4 categories, #5 events, #6 media,
  #7 tickets, #8 orders, #9 attendees, #10 payments, #11 reviews, #12 notifications

## Created Tables (14 of 15)
- users, user_profiles, organizations, organization_members, categories, events,
  event_media, ticket_types, orders, order_items, attendees, payments, reviews, notifications
- Remaining: audit_logs (Phase 8). Migration head: 37ce071de6f6
- 172 tests passing. APScheduler runs cleanup_expired_orders every 60s + daily event reminders.

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
