"""SMTP email sender with Jinja2 templates.

Renders HTML templates from ``email_templates/`` and sends via SMTP. In
development this targets MailHog; in production, Gmail SMTP (configured via env).
"""

import logging
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import settings

logger = logging.getLogger("eventpulse.email")

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "email_templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_template(template_name: str, **context: object) -> str:
    """Render a Jinja2 email template from ``email_templates/`` to an HTML string."""
    template = _env.get_template(template_name)
    return template.render(**context)


async def send_email(to: str, subject: str, html_body: str) -> None:
    """Send an HTML email via the configured SMTP server.

    Failures are logged rather than raised so that email delivery problems never
    break the surrounding request flow (e.g. registration still succeeds).
    """
    message = EmailMessage()
    message["From"] = settings.FROM_EMAIL
    message["To"] = to
    message["Subject"] = subject
    message.set_content("This message requires an HTML-capable email client.")
    message.add_alternative(html_body, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME or None,
            password=settings.SMTP_PASSWORD or None,
            use_tls=settings.SMTP_USE_TLS,
        )
    except Exception:  # noqa: BLE001 - email delivery is best-effort
        logger.exception("Failed to send email to %s (subject=%s)", to, subject)


async def send_verification_email(to: str, token: str) -> None:
    """Send the email-verification message with a tokenized link."""
    link = f"{settings.WEB_APP_URL}/verify-email?token={token}"
    html = render_template("verify_email.html", verification_link=link)
    await send_email(to, "Verify your EventPulse email", html)


async def send_password_reset_email(to: str, token: str) -> None:
    """Send the password-reset message with a tokenized link."""
    link = f"{settings.WEB_APP_URL}/reset-password?token={token}"
    html = render_template("reset_password.html", reset_link=link)
    await send_email(to, "Reset your EventPulse password", html)
