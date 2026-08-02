import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.invitation import Invitation
from app.models.profile import UserProfile
from app.models.meal_plan import MealPlan
from app.models.meal import Meal
from app.models.shopping_list import ShoppingList
from app.models.shopping_item import ShoppingItem
from app.models.food_stock import FoodStock
from app.models.saved_meal import SavedMeal
from app.models.household import HouseholdMember
from app.models.token_usage import TokenUsage
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
    # send_invitation_email(email, token)  # email deshabilitado temporalmente
    invite_url = f"{settings.app_base_url}/registro/{token}"
    return RedirectResponse(
        f"/admin/usuarios?success=Link+de+invitación+generado&invite_link={invite_url}",
        status_code=303,
    )


@router.post("/admin/usuarios/{user_id}/eliminar")
def eliminar_usuario(user_id: int, request: Request, db: Session = Depends(get_db)):
    current = _require_admin(request, db)
    if isinstance(current, RedirectResponse):
        return current
    if user_id == current.id:
        return RedirectResponse("/admin/usuarios?error=No+puedes+eliminar+tu+propia+cuenta", status_code=303)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse("/admin/usuarios?error=Usuario+no+encontrado", status_code=303)

    # Delete all user data in dependency order
    db.query(SavedMeal).filter(SavedMeal.user_id == user_id).delete()
    db.query(FoodStock).filter(FoodStock.user_id == user_id).delete()
    db.query(HouseholdMember).filter(HouseholdMember.user_id == user_id).delete()
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if profile:
        plan_ids = [p.id for p in db.query(MealPlan.id).filter(MealPlan.profile_id == profile.id).all()]
        if plan_ids:
            list_ids = [s.id for s in db.query(ShoppingList.id).filter(ShoppingList.meal_plan_id.in_(plan_ids)).all()]
            if list_ids:
                db.query(ShoppingItem).filter(ShoppingItem.shopping_list_id.in_(list_ids)).delete()
            db.query(ShoppingList).filter(ShoppingList.meal_plan_id.in_(plan_ids)).delete()
            db.query(Meal).filter(Meal.meal_plan_id.in_(plan_ids)).delete()
            db.query(MealPlan).filter(MealPlan.id.in_(plan_ids)).delete()
        db.delete(profile)
    db.delete(user)
    db.commit()
    return RedirectResponse(f"/admin/usuarios?success=Usuario+{user.email}+eliminado", status_code=303)


_TOKEN_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6":          {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5-20251001":  {"input": 0.80,  "output": 4.00},
}
_DEFAULT_PRICING = {"input": 3.00, "output": 15.00}


def _token_cost(model: str | None, input_tok: int, output_tok: int) -> float:
    p = _TOKEN_PRICING.get(model or "", _DEFAULT_PRICING)
    return (input_tok * p["input"] + output_tok * p["output"]) / 1_000_000


@router.get("/admin/tokens")
def admin_tokens(request: Request, db: Session = Depends(get_db)):
    current = _require_admin(request, db)
    if isinstance(current, RedirectResponse):
        return current

    # Breakdown by function + model per user (used to compute cost accurately)
    breakdown_raw = (
        db.query(
            TokenUsage.user_id,
            TokenUsage.function_name,
            TokenUsage.model,
            func.sum(TokenUsage.input_tokens).label("input_total"),
            func.sum(TokenUsage.output_tokens).label("output_total"),
            func.count(TokenUsage.id).label("calls"),
        )
        .group_by(TokenUsage.user_id, TokenUsage.function_name, TokenUsage.model)
        .all()
    )

    breakdown_by_user: dict = {}
    user_costs: dict[int, float] = {}
    for r in breakdown_raw:
        cost = _token_cost(r.model, r.input_total or 0, r.output_total or 0)
        entry = {
            "function_name": r.function_name,
            "model": r.model or "—",
            "input_total": r.input_total or 0,
            "output_total": r.output_total or 0,
            "calls": r.calls,
            "cost": cost,
        }
        breakdown_by_user.setdefault(r.user_id, []).append(entry)
        user_costs[r.user_id] = user_costs.get(r.user_id, 0.0) + cost

    # Totals per user
    rows = (
        db.query(
            User.id,
            User.email,
            func.sum(TokenUsage.input_tokens).label("input_total"),
            func.sum(TokenUsage.output_tokens).label("output_total"),
            func.count(TokenUsage.id).label("calls"),
        )
        .join(TokenUsage, TokenUsage.user_id == User.id)
        .group_by(User.id, User.email)
        .order_by(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens).desc())
        .all()
    )

    # Grand totals
    grand = db.query(
        func.sum(TokenUsage.input_tokens),
        func.sum(TokenUsage.output_tokens),
        func.count(TokenUsage.id),
    ).first()

    grand_cost = sum(user_costs.values())

    return templates.TemplateResponse(request, "admin/tokens.html", {
        "current_user": current,
        "rows": rows,
        "breakdown_by_user": breakdown_by_user,
        "user_costs": user_costs,
        "grand_input": grand[0] or 0,
        "grand_output": grand[1] or 0,
        "grand_calls": grand[2] or 0,
        "grand_cost": grand_cost,
    })


@router.post("/admin/invitaciones/{inv_id}/cancelar")
def cancelar_invitacion(inv_id: int, request: Request, db: Session = Depends(get_db)):
    current = _require_admin(request, db)
    if isinstance(current, RedirectResponse):
        return current
    inv = db.query(Invitation).filter(Invitation.id == inv_id, Invitation.used == False).first()
    if inv:
        inv.used = True
        db.commit()
    return RedirectResponse("/admin/usuarios?success=Invitacion+cancelada", status_code=303)


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
