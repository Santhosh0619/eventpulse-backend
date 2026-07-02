"""AI-generated natural-language analytics summaries via Google Gemini.

Turns an event's raw sales and attendance aggregates into a short, plain-language
paragraph an organizer can read at a glance. Every entry point degrades
gracefully: when Gemini is unconfigured, rate-limited, or errors, a deterministic
template summary built from the same figures is returned instead, so the endpoint
always yields a useful paragraph.
"""

import json
from decimal import Decimal

from app.core.gemini import GeminiError, get_gemini
from app.features.analytics.schemas import AttendanceAnalytics, SalesAnalytics
from app.features.events.models import Event


def _analytics_payload(
    event: Event, sales: SalesAnalytics, attendance: AttendanceAnalytics
) -> dict:
    """Return a compact, prompt-friendly view of the event's analytics."""
    return {
        "event": {
            "title": event.title,
            "city": event.city,
            "status": event.status,
            "capacity": event.max_capacity,
        },
        "sales": {
            "currency": sales.currency,
            "total_revenue": float(sales.total_revenue),
            "total_orders": sales.total_orders,
            "total_tickets_sold": sales.total_tickets_sold,
            "daily": [
                {
                    "day": d.day.isoformat(),
                    "revenue": float(d.revenue),
                    "orders": d.orders,
                }
                for d in sales.daily
            ],
            "tiers": [
                {
                    "name": t.name,
                    "tickets_sold": t.tickets_sold,
                    "revenue": float(t.revenue),
                }
                for t in sales.tiers
            ],
        },
        "attendance": {
            "total_tickets": attendance.total,
            "checked_in": attendance.checked_in,
            "check_in_rate": attendance.check_in_rate,
            "hourly": [{"hour": h.hour, "count": h.count} for h in attendance.hourly],
        },
    }


def _summary_prompt(payload: dict) -> str:
    """Build the Gemini prompt for an event analytics summary."""
    return (
        "You are an analytics assistant for EventPulse, an event ticketing "
        "platform. Given the sales and attendance data for a single event, write "
        "a concise, friendly summary for the event's organizer.\n\n"
        f"Event analytics data:\n{json.dumps(payload)}\n\n"
        "Write 2-4 sentences of plain prose highlighting the most useful insights: "
        "total revenue and tickets sold, how sales trend across days, the "
        "best-selling ticket tier, the check-in / attendance rate, and any notable "
        "peak buying or check-in times. Use the currency provided in the data. If "
        "there is no sales data yet, say so plainly. Respond with ONLY the "
        "paragraph — no markdown, no headings, and no bullet points."
    )


def _money(currency: str, amount: Decimal) -> str:
    """Format a monetary amount with its currency code (e.g. ``USD 1,250.00``)."""
    return f"{currency} {amount:,.2f}"


def _fallback_summary(
    event: Event, sales: SalesAnalytics, attendance: AttendanceAnalytics
) -> str:
    """Build a deterministic summary paragraph from the raw numbers."""
    if sales.total_orders == 0:
        return (
            f'"{event.title}" has no confirmed sales yet, so there are no revenue '
            "or attendance figures to report."
        )
    tickets = sales.total_tickets_sold
    orders = sales.total_orders
    parts = [
        f'"{event.title}" has sold {tickets} '
        f"ticket{'s' if tickets != 1 else ''} across "
        f"{orders} order{'s' if orders != 1 else ''}, generating "
        f"{_money(sales.currency, sales.total_revenue)} in revenue."
    ]
    if sales.tiers:
        top = max(sales.tiers, key=lambda t: t.tickets_sold)
        if top.tickets_sold > 0:
            parts.append(
                f'The best-selling tier is "{top.name}" with {top.tickets_sold} sold.'
            )
    if attendance.total:
        rate = round(attendance.check_in_rate * 100)
        parts.append(
            f"{attendance.checked_in} of {attendance.total} attendees have "
            f"checked in ({rate}%)."
        )
        if attendance.hourly:
            peak = max(attendance.hourly, key=lambda h: h.count)
            parts.append(f"Check-ins peak around {peak.hour:02d}:00 UTC.")
    return " ".join(parts)


async def generate_event_summary(
    event: Event, sales: SalesAnalytics, attendance: AttendanceAnalytics
) -> tuple[str, bool]:
    """Return ``(summary, generated_by_ai)`` for an event's analytics.

    Uses Gemini when it is configured and reachable; otherwise falls back to a
    deterministic template built from the same figures.
    """
    gemini = get_gemini()
    if gemini.is_configured:
        prompt = _summary_prompt(_analytics_payload(event, sales, attendance))
        try:
            text = await gemini.generate_text(prompt, temperature=0.4)
        except GeminiError:
            text = ""
        if text.strip():
            return text.strip(), True
    return _fallback_summary(event, sales, attendance), False
