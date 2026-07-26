"""Plain SMTP email sending. Used for certificate delivery (permanent copy
in the employee's own inbox, independent of whether they can still log
into the app later) -- and available as a general-purpose sender for
anything else that needs actual email rather than a push notification.

Requires these settings (add to app/core/config.py if not already present):
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
    SMTP_FROM_ADDRESS, SMTP_USE_TLS (bool)
"""
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings


def send_email(
    to: str,
    subject: str,
    body: str,
    attachment_path: str | None = None,
    attachment_filename: str | None = None,
) -> None:
    """Sends a plain-text email, optionally with one file attached.
    Raises on failure -- callers that shouldn't fail their main flow over
    an email hiccup (e.g. certificate issuance) should wrap this in
    try/except themselves, same pattern as the Celery task's broker-down
    handling elsewhere in this codebase."""
    msg = MIMEMultipart()
    msg["From"] = settings.SMTP_FROM_ADDRESS
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_path is not None:
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header(
            "Content-Disposition", "attachment",
            filename=attachment_filename or attachment_path.split("/")[-1],
        )
        msg.attach(part)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM_ADDRESS, [to], msg.as_string())