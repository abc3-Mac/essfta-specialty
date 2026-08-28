"""Outbound mail for editor invites, via Mailgun SMTP (stdlib only).

ALL programmatic sending in this household goes through Mailgun — never a
mailbox provider's SMTP (standing rule since the Migadu suspension). Configure
with the same credential the Ghost blogs use:

    SMTP_HOST=smtp.mailgun.org  SMTP_PORT=587  SMTP_USER=...  SMTP_PASS=...
    MAIL_FROM="ESSFTA Specialty Shows <specialty@mg.collver.biz>"   (optional)
    SITE_URL=https://essfta-specialty.collver.biz                   (optional)

With no SMTP_* env set the feature is simply off: configured() is False, the
UI drops its email promises, and callers fall back to hand-delivery.
"""
import os
import smtplib
from email.message import EmailMessage

HOST = os.environ.get("SMTP_HOST", "")
PORT = int(os.environ.get("SMTP_PORT", "587") or 587)
USER = os.environ.get("SMTP_USER", "")
PASSWORD = os.environ.get("SMTP_PASS", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "ESSFTA Specialty Shows <specialty@mg.collver.biz>")
SITE_URL = os.environ.get("SITE_URL", "https://essfta-specialty.collver.biz")


def configured() -> bool:
    return bool(HOST and USER and PASSWORD)


def _send(to: str, subject: str, body: str):
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(HOST, PORT, timeout=20) as s:
        s.starttls()
        s.login(USER, PASSWORD)
        s.send_message(msg)


def send_invite(to: str, display_name: str, username: str, password: str, is_reset=False):
    """Returns None on success, or a short human-readable error string."""
    if not configured():
        return "email is not configured on this server"
    if is_reset:
        subject = "ESSFTA Specialty Shows — your password was reset"
        intro = "Your password for the ESSFTA specialty-show calendar was reset."
    else:
        subject = "ESSFTA Specialty Shows — your editor account"
        intro = ("You have been given an editor account on the ESSFTA "
                 "specialty-show calendar.")
    body = f"""Hello {display_name},

{intro}

  Sign in:  {SITE_URL}/dashboard
  Username: {username}
  Password: {password}

Editors can add and edit shows, upload the calendar spreadsheet, and use the
bulk tools. The Help page on the dashboard explains every button.

Keep this message somewhere safe, or note the password down — it is not
stored anywhere it can be looked up again. If you lose it, any admin can
reset it from the dashboard.

ESSFTA Specialty Shows
{SITE_URL}
"""
    try:
        _send(to, subject, body)
        return None
    except Exception as e:  # smtplib raises many types; the caller shows this to an admin
        return f"{type(e).__name__}: {e}"
