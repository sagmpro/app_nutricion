import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.invitation import Invitation
from app.services.auth_service import verify_password, hash_password, set_session_cookie, get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "auth/login.html", {
        "error": request.query_params.get("error"),
        "next": request.query_params.get("next", "/dashboard"),
    })


@router.post("/login")
async def login(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/dashboard"),
):
    user = db.query(User).filter(User.email == email.lower().strip(), User.is_active == True).first()
    if not user or not user.hashed_password or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(request, "auth/login.html", {
            "error": "Email o contrasena incorrectos",
            "email": email,
            "next": next,
        }, status_code=401)
    response = RedirectResponse(next or "/dashboard", status_code=303)
    set_session_cookie(response, user.id)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("nutriplan_session")
    return response


@router.get("/registro/{token}")
def register_form(token: str, request: Request, db: Session = Depends(get_db)):
    inv = db.query(Invitation).filter(
        Invitation.token == token,
        Invitation.used == False,
        Invitation.expires_at > datetime.utcnow(),
    ).first()
    if not inv:
        return templates.TemplateResponse(request, "auth/login.html", {
            "error": "Enlace de invitacion invalido o expirado.",
        })
    return templates.TemplateResponse(request, "auth/register.html", {
        "token": token,
        "email": inv.email,
        "error": request.query_params.get("error"),
    })


@router.post("/registro/{token}")
async def register(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    password: str = Form(...),
    password2: str = Form(...),
):
    inv = db.query(Invitation).filter(
        Invitation.token == token,
        Invitation.used == False,
        Invitation.expires_at > datetime.utcnow(),
    ).first()
    if not inv:
        return RedirectResponse("/login?error=Enlace+invalido", status_code=303)
    if password != password2:
        return templates.TemplateResponse(request, "auth/register.html", {
            "token": token,
            "email": inv.email,
            "error": "Las contrasenas no coinciden.",
        })
    if len(password) < 8:
        return templates.TemplateResponse(request, "auth/register.html", {
            "token": token,
            "email": inv.email,
            "error": "La contrasena debe tener al menos 8 caracteres.",
        })
    # Create or activate user
    user = db.query(User).filter(User.email == inv.email).first()
    if not user:
        user = User(email=inv.email, role="user", is_active=True)
        db.add(user)
    user.hashed_password = hash_password(password)
    user.is_active = True
    inv.used = True
    db.commit()
    db.refresh(user)
    response = RedirectResponse("/perfil", status_code=303)
    set_session_cookie(response, user.id)
    return response
