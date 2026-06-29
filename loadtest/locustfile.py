"""Locust load test for EventPulse.

Exercises the read-heavy discovery paths (event search, detail, availability,
reviews) that dominate production traffic, plus an authenticated browsing flow.

Run (not part of the app image — install separately):

    pip install locust
    locust -f loadtest/locustfile.py --host http://localhost:8000

Then open http://localhost:8089 and configure users / spawn rate. The plan's
target is 500 concurrent users with p95 < 200 ms for reads.
"""

import random

from locust import HttpUser, between, task

API = "/api/v1"


class AnonymousVisitor(HttpUser):
    """Unauthenticated visitor browsing the public catalog (the common case)."""

    weight = 4
    wait_time = between(1, 4)

    def on_start(self) -> None:
        """Seed a list of event ids to drill into during the run."""
        self.event_ids: list[str] = []
        resp = self.client.get(f"{API}/events?limit=20", name="GET /events")
        if resp.status_code == 200:
            self.event_ids = [e["id"] for e in resp.json().get("items", [])]

    @task(5)
    def browse_events(self) -> None:
        """List events, optionally filtered by city."""
        params = random.choice(["", "?city=Pune", "?limit=10", "?is_featured=true"])
        self.client.get(f"{API}/events{params}", name="GET /events")

    @task(3)
    def view_event_detail(self) -> None:
        """Open an event detail page plus its availability and reviews."""
        if not self.event_ids:
            return
        event_id = random.choice(self.event_ids)
        self.client.get(f"{API}/events/{event_id}", name="GET /events/{id}")
        self.client.get(
            f"{API}/events/{event_id}/availability",
            name="GET /events/{id}/availability",
        )
        self.client.get(
            f"{API}/events/{event_id}/reviews/summary",
            name="GET /events/{id}/reviews/summary",
        )

    @task(1)
    def health(self) -> None:
        """Hit the liveness probe."""
        self.client.get(f"{API}/health", name="GET /health")


class AuthenticatedUser(HttpUser):
    """A logged-in user browsing recommendations and their orders."""

    weight = 1
    wait_time = between(2, 5)

    def on_start(self) -> None:
        """Log in once; fall back to anonymous browsing if credentials are unset."""
        self.headers: dict[str, str] = {}
        creds = {"email": "loadtest@example.com", "password": "Password123!"}
        resp = self.client.post(
            f"{API}/auth/login", json=creds, name="POST /auth/login"
        )
        if resp.status_code == 200:
            self.headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    @task(3)
    def recommendations(self) -> None:
        """Fetch the personalized feed (requires auth)."""
        if self.headers:
            self.client.get(
                f"{API}/recommendations/events",
                headers=self.headers,
                name="GET /recommendations/events",
            )

    @task(2)
    def my_orders(self) -> None:
        """List the user's orders."""
        if self.headers:
            self.client.get(
                f"{API}/users/me/orders",
                headers=self.headers,
                name="GET /users/me/orders",
            )
