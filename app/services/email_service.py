import logging
from app.config import settings

logger = logging.getLogger(__name__)


def send_invitation_email(to_email: str, token: str) -> bool:
    """Send invitation email. Returns True on success, False if Resend not configured."""
    if not settings.resend_api_key:
        logger.info(f"No RESEND_API_KEY — invitation link: {settings.app_base_url}/registro/{token}")
        return False
    try:
        import resend
        resend.api_key = settings.resend_api_key
        register_url = f"{settings.app_base_url}/registro/{token}"
        resend.Emails.send({
            "from": settings.resend_from_email,
            "to": [to_email],
            "subject": "Te invitaron a NutriPlan",
            "html": f"""
            <div style="font-family:sans-serif;max-width:500px;margin:auto;padding:32px">
              <h2 style="color:#16a34a">NutriPlan</h2>
              <p>Te han invitado a usar NutriPlan para gestionar tu nutricion personalizada.</p>
              <p>Haz clic en el boton para crear tu cuenta:</p>
              <a href="{register_url}"
                 style="display:inline-block;background:#16a34a;color:white;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600;margin:16px 0">
                Crear mi cuenta
              </a>
              <p style="color:#6b7280;font-size:13px">Este enlace expira en 7 dias. Si no esperabas esta invitacion, ignora este mensaje.</p>
            </div>
            """,
        })
        return True
    except Exception as e:
        logger.error(f"Error sending invitation email: {e}")
        return False
