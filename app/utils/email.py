"""SMTP email sender with Jinja2 templates.

Placeholder for Phase 0. Full implementation (aiosmtplib + Jinja2 rendering,
MailHog in dev, Gmail SMTP in prod) lands in Phase 2.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

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
    """Send an HTML email. Implemented in Phase 2 (aiosmtplib)."""
    raise NotImplementedError("Email sending is implemented in Phase 2")
