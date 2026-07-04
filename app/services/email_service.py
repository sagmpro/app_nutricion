import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.config import settings

logger = logging.getLogger(__name__)


def _build_html(register_url: str) -> str:
    return f"""
    <div style="font-family:sans-serif;max-width:500px;margin:auto;padding:32px">
      <h2 style="color:#16a34a">🥗 NutriPlan</h2>
      <p>Te han invitado a usar NutriPlan para gestionar tu nutrición personalizada.</p>
      <p>Haz clic en el botón para crear tu cuenta:</p>
      <a href="{register_url}"
         style="display:inline-block;background:#16a34a;color:white;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600;margin:16px 0">
        Crear mi cuenta
      </a>
      <p style="color:#6b7280;font-size:13px">Este enlace expira en 7 días. Si no esperabas esta invitación, ignora este mensaje.</p>
    </div>
    """


def _send_via_gmail(to_email: str, register_url: str) -> bool:
    if not settings.gmail_user or not settings.gmail_app_password:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Te invitaron a NutriPlan"
        msg["From"] = f"NutriPlan <{settings.gmail_user}>"
        msg["To"] = to_email
        msg.attach(MIMEText(_build_html(register_url), "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(settings.gmail_user, settings.gmail_app_password)
            server.sendmail(settings.gmail_user, to_email, msg.as_string())
        logger.info(f"Invitation email sent via Gmail to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Gmail send error: {e}")
        return False


def _send_via_resend(to_email: str, register_url: str) -> bool:
    if not settings.resend_api_key:
        return False
    try:
        import resend
        resend.api_key = settings.resend_api_key
        resend.Emails.send({
            "from": settings.resend_from_email,
            "to": [to_email],
            "subject": "Te invitaron a NutriPlan",
            "html": _build_html(register_url),
        })
        logger.info(f"Invitation email sent via Resend to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Resend error: {e}")
        return False


def send_invitation_email(to_email: str, token: str) -> bool:
    """Send invitation email. Returns True on success, False if no provider configured."""
    register_url = f"{settings.app_base_url}/registro/{token}"

    if _send_via_gmail(to_email, register_url):
        return True
    if _send_via_resend(to_email, register_url):
        return True

    logger.info(f"No email provider configured — invitation link: {register_url}")
    return False
