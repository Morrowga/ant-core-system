"""Email delivery for the landing page's public Contact and Support forms.

Uses the SAME SMTP settings already configured for this project
(app.core.config.Settings) -- SMTP_HOST / SMTP_PORT / SMTP_USERNAME /
SMTP_PASSWORD / SMTP_FROM_ADDRESS / SMTP_USE_TLS. Submissions land in the
same inbox as SMTP_USERNAME itself (the Gmail account already configured
for sending) -- deliberately NOT a new, separate required settings field,
since adding one would need to be set in every environment (local
included) before the app would even start. If a dedicated inbox is
wanted later, add a SUPPORT_INBOX_EMAIL field with a default that falls
back to SMTP_USERNAME, rather than a hard requirement.

If a shared email-sending utility already exists elsewhere in this
codebase (e.g. for invite emails or welcome emails), this should be
consolidated with that rather than kept as a second, separate mailer --
flagging this now since that file wasn't available to check against.

Sends synchronously via smtplib -- simple and fine for a low-volume
landing-page form; not meant to be a general-purpose transactional email
system.
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone

from app.core.config import settings

ESPRESSO = "#4A2E1E"
CREAM = "#FAF6F1"


def _render_template(heading: str, intro: str, rows: list[tuple[str, str]]) -> str:
    """One shared branded template for both forms -- a plain, readable
    email (not over-designed), with the brand's espresso color as the
    single accent, matching the landing page's own palette rather than
    inventing a separate visual identity just for email."""
    rows_html = "".join(
        f"""
        <tr>
          <td style="padding:10px 16px;border-bottom:1px solid #eee;color:#777;font-size:13px;
                     font-family:Arial,sans-serif;white-space:nowrap;vertical-align:top;">{label}</td>
          <td style="padding:10px 16px;border-bottom:1px solid #eee;color:#222;font-size:14px;
                     font-family:Arial,sans-serif;line-height:1.5;">{value}</td>
        </tr>"""
        for label, value in rows
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""
<html>
  <body style="margin:0;padding:0;background-color:{CREAM};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="background-color:{CREAM};padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellpadding="0" cellspacing="0"
                 style="background-color:#ffffff;border-radius:12px;overflow:hidden;
                        box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <tr>
              <td style="background-color:{ESPRESSO};padding:24px 32px;">
                <span style="font-family:Arial,sans-serif;font-size:20px;font-weight:700;
                             color:#ffffff;letter-spacing:0.5px;">ANTS</span>
              </td>
            </tr>
            <tr>
              <td style="padding:28px 32px 8px 32px;">
                <h1 style="margin:0 0 8px 0;font-family:Arial,sans-serif;font-size:18px;
                           color:{ESPRESSO};">{heading}</h1>
                <p style="margin:0;font-family:Arial,sans-serif;font-size:13px;color:#777;">
                  {intro}
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 16px 24px 16px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  {rows_html}
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 32px;background-color:#f7f3ef;">
                <p style="margin:0;font-family:Arial,sans-serif;font-size:11px;color:#999;">
                  Submitted {timestamp} via the ANTS landing page.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _send(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM_ADDRESS
    msg["To"] = settings.SMTP_USERNAME  # same inbox as the sending account
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(msg)


def send_contact_form_email(name: str, email: str, message: str) -> None:
    html = _render_template(
        heading="New contact form submission",
        intro="Someone reached out through the landing page's Contact section.",
        rows=[
            ("Name", name),
            ("Email", f'<a href="mailto:{email}" style="color:{ESPRESSO};">{email}</a>'),
            ("Message", message.replace(chr(10), "<br>")),
        ],
    )
    _send(f"[ANTS Contact] {name}", html)


def send_support_ticket_email(subject: str, message: str) -> None:
    html = _render_template(
        heading="New support ticket",
        intro="Submitted through the landing page's Support section (no account required).",
        rows=[
            ("Subject", subject),
            ("Message", message.replace(chr(10), "<br>")),
        ],
    )
    _send(f"[ANTS Support] {subject}", html)