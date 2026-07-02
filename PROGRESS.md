# EventPulse Backend — Progress Tracker

## Current Status
- Phase: 9 (Performance, Security & Production) — COMPLETE. **BACKEND COMPLETE.**
- Phase 9 PRs: Redis caching (#16); rate-limiting (#17); db-health/readiness probe (#18);
  security hardening (#19) — headers + body-size-limit middleware, account lockout (10 fails
  /15m, Redis), webhook exempt from rate limit, CORS locked down; loadtest+OpenAPI (PR pending)
  — Locust file (loadtest/locustfile.py, not in image) + OpenAPI completeness test
  (every operation has summary+tags). 221 tests passing.
- App-level production-deploy items (nginx/SSL, prod docker-compose, Sentry/Prometheus,
  CI prod pipelines) are infra/ops, deferred — out of the in-repo app scope.
- NEXT: **web repo** (eventpulse-web), then mobile repo (eventpulse-mobile).

## Deployment phase (21 ideas) — backend changes
- **Idea 14 — AI Recommendations (Gemini) — MERGED (PR #23).** app/core/gemini.py (async
  client, graceful GeminiError fallback), recommendations/ai.py (Gemini ranking over the
  heuristic candidate pool, falls back to heuristic), AiRecommendedEvent schema, endpoints
  GET /recommendations/for-me + GET /events/{id}/similar. config GEMINI_API_KEY/GEMINI_MODEL.
  google-generativeai added (lazy import). No migration. 240 tests.
- **Idea 15 — AI Event Descriptions (Gemini) — MERGED (PR #24).** POST /events/generate-description
  (auth): keywords[] + tone → generated description via Gemini with a templated fallback
  (returns ai_generated flag). services.generate_event_description. No migration. 247 tests.
- **Idea 16 — AI Review Moderation (Gemini) — this PR.** reviews/moderation.py classifies
  review text allow/flag/reject (fails OPEN on error/unconfigured). submit_review: reject→422
  "Review was flagged as inappropriate", flag→saved hidden + moderation_status="flagged".
  New Review.moderation_status column (MIGRATION 5f2e8b959690). Org endpoints:
  GET /events/{id}/reviews/management (all incl hidden), POST /reviews/{id}/approve.
  Added UnprocessableEntityError (422) + ModerationStatus enum. 255 tests.
  NOTE: test DB (eventpulse_test) is built via create_all (checkfirst) — a NEW COLUMN on an
  existing table needs the test DB DROPPED so it recreates: `docker compose exec -T postgres
  psql -U postgres -c "DROP DATABASE IF EXISTS eventpulse_test WITH (FORCE);"` (new tables are fine).
  See eventpulse-project-plan.md for web/mobile tasks per phase.
- **Idea 18 — AI Analytics Summary (Gemini) — this PR.** GET /analytics/ai-summary?event_id={id}
  (org member only): builds sales + attendance analytics for the event and asks Gemini for a
  concise natural-language paragraph, degrading to a deterministic template summary when Gemini
  is unconfigured/errors/returns blank (returns generated_by_ai flag). analytics/ai.py
  (generate_event_summary + _fallback_summary), AiAnalyticsSummary schema. Refactored
  event_sales/event_attendance into public (auth) + private _event_*_data (no-auth) helpers so
  the summary reuses the aggregates without re-authorizing. No migration. 264 tests.
- **Idea 19 — AI Chatbot for Attendees (Gemini) — this PR.** POST /api/v1/events/{id}/chat
  (auth required): {question} → Gemini answer grounded in event details + ticket tiers, returns
  {answer, generated_by_ai, questions_remaining}. New app/features/chat/ module (schemas/ai/
  services). Rate limit 5 questions/user/event/hour via a MANUAL Redis fixed-window counter
  (app/core/redis.py record_chat_question, key chat:questions:{user}:{event}, incr + expire on
  first) — NOT slowapi (needs per-user+event granularity). New TooManyRequestsError (429).
  Graceful Gemini fallback (polite message, generated_by_ai=false, still 200). Config
  CHATBOT_MAX_QUESTIONS_PER_HOUR=5 / CHATBOT_WINDOW_SECONDS=3600. No migration. 275 tests.
  SECURITY (code-review MEDIUM, fixed): chat only answers PUBLISHED events (404 otherwise) and
  only feeds ACTIVE tiers to Gemini, so draft/cancelled events + inactive-tier pricing aren't
  leaked to any authed user via the chatbot.
  NOTE: chat rate limit is active even in tests (manual Redis counter, unaffected by the
  suite's _disable_rate_limit slowapi fixture); _reset_redis autouse fixture flushes it per test.
- **Idea 11 — WebSocket Real-Time Updates (backend) — IN PROGRESS (saved, not yet CI-verified).**
  WS endpoint GET /api/v1/ws/events/{event_id} (app/features/events/ws.py): public (count is public
  info), sends an initial {attendee_count, checked_in} snapshot then forwards Redis pub/sub messages
  on channel `event:attendees:{event_id}` until disconnect (asyncio.wait over a forward task +
  a drain task). broadcast_attendee_count(db, event_id) publishes the current count. Hooked into
  payments/services.handle_webhook: _confirm_order_and_issue_tickets now returns order.event_id;
  after db.commit() the webhook calls events_ws.broadcast_attendee_count (lazy import). Added
  attendees/services.count_for_event (public no-auth wrapper of crud.count_for_event). Registered
  ws router in main.py. No migration.
  TESTS (tests/features/test_websocket.py): channel/payload helpers ✅, broadcast publishes correct
  count via real Redis pub/sub ✅ (both PASSED locally). The TestClient WS-handshake test is
  @pytest.mark.skip — Starlette TestClient uses its own portal event loop which clashes with the
  import-time async engine ("Future attached to a different loop"); NOT a code bug (snapshot query
  runs). RESUME: re-run `docker compose run --rm api ruff format/check` + full pytest, then commit
  any format fixes, push, PR. THEN web + mobile WS clients (live attendee count on EventDetail).
- NOTE: anon-tier 20/min folded into 100/min default (slowapi default_limits can't vary
  per-request auth state cleanly); documented deviation.

## (Phase 8 — COMPLETE)
- Phase: 8 (Analytics, Recommendations & Admin) — COMPLETE
- Done this phase: `analytics` (PR #13), `recommendations` (PR #14), `admin` (PR pending) —
  audit_logs (Table 15 = ALL 15 TABLES NOW LIVE), admin dashboard + user/org/event management
  + audit-log viewer, log_action() utility wired into event create/publish/cancel,
  order confirm, payment refund, org create/invite/role-change/member-remove, user role change.
- Migration head: 4db3a67e2fae (audit_logs).
- NEXT: Phase 9 (Redis caching, rate-limiting via slowapi, DB/query optimization, security
  headers + hardening, load testing). Then web repo, then mobile repo.
- DEFERRED to Phase 9: API rate limiting (no limiter exists anywhere yet).

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
- **analytics** (PR #13) — event sales/attendance, org overview, platform dashboard (no model)
- **recommendations** (PR #14) — weighted personalized feed + similar events (no model)
- **admin** (PR pending) — audit_logs (Table 15), dashboard, user/org/event mgmt, audit viewer,
  log_action() wired into mutations across events/payments/organizations/users

## Merged Branches
- #1 auth, #2 users, #3 organizations, #4 categories, #5 events, #6 media,
  #7 tickets, #8 orders, #9 attendees, #10 payments, #11 reviews, #12 notifications,
  #13 analytics, #14 recommendations

## Created Tables (15 of 15 — COMPLETE)
- users, user_profiles, organizations, organization_members, categories, events,
  event_media, ticket_types, orders, order_items, attendees, payments, reviews,
  notifications, audit_logs
- Migration head: 4db3a67e2fae (audit_logs).
- 201 tests passing. APScheduler runs cleanup_expired_orders every 60s + daily event reminders.

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
