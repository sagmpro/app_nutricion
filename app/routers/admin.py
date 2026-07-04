import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.invitation import Invitation
from app.services.auth_service import get_current_user
from app.services.email_service import send_invitation_email
from app.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _require_admin(request: Request, db: Session):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.role != "admin":
        return RedirectResponse("/dashboard", status_code=303)
    return user


@router.get("/admin/usuarios")
def admin_usuarios(request: Request, db: Session = Depends(get_db)):
    current = _require_admin(request, db)
    if isinstance(current, RedirectResponse):
        return current
    users = db.query(User).order_by(User.created_at).all()
    pending_invitations = db.query(Invitation).filter(
        Invitation.used == False,
        Invitation.expires_at > datetime.utcnow(),
    ).all()
    return templates.TemplateResponse(request, "admin/users.html", {
        "current_user": current,
        "users": users,
        "pending_invitations": pending_invitations,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
        "invite_link": request.query_params.get("invite_link"),
    })


@router.post("/admin/usuarios/invitar")
async def invitar_usuario(request: Request, db: Session = Depends(get_db), email: str = Form(...)):
    current = _require_admin(request, db)
    if isinstance(current, RedirectResponse):
        return current
    email = email.lower().strip()
    # Check if user already exists
    if db.query(User).filter(User.email == email).first():
        return RedirectResponse(f"/admin/usuarios?error=El+usuario+{email}+ya+existe", status_code=303)
    # Invalidate old pending invitations for this email
    db.query(Invitation).filter(Invitation.email == email, Invitation.used == False).update({"used": True})
    token = uuid.uuid4().hex
    inv = Invitation(
        email=email,
        token=token,
        invited_by=current.id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(inv)
    db.commit()
    sent = send_invitation_email(email, token)
    invite_url = f"{settings.app_base_url}/registro/{token}"
    msg = "Invitacion+enviada+por+email+y" if sent else "Email+no+configurado+"
    return RedirectResponse(
        f"/admin/usuarios?success={msg}link+disponible&invite_link={invite_url}",
        status_code=303,
    )


@router.post("/admin/usuarios/{user_id}/toggle")
def toggle_usuario(user_id: int, request: Request, db: Session = Depends(get_db)):
    current = _require_admin(request, db)
    if isinstance(current, RedirectResponse):
        return current
    if user_id == current.id:
        return RedirectResponse("/admin/usuarios?error=No+puedes+desactivar+tu+propia+cuenta", status_code=303)
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.is_active = not user.is_active
        db.commit()
    return RedirectResponse("/admin/usuarios", status_code=303)
