import json
from datetime import date
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.profile import UserProfile
from app.models.meal_plan import MealPlan
from app.models.food_stock import FoodStock
from app.services.auth_service import get_current_user
from app.services.nutrition import calculate_bmr, calculate_tdee, calculate_target_calories, get_activity_days_list, DAYS_OF_WEEK

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _build_greeting(profile, plans_count: int, today_consumed: int, today_total: int, week_consumed: int, week_total: int) -> dict:
    first_name = profile.name.split()[0] if profile.name else "amigo"

    if plans_count == 0:
        return {
            "greeting": f"Hola, {first_name}!",
            "message": "Tu perfil esta listo. Genera tu primer plan semanal y empieza tu camino hacia tus objetivos.",
            "emoji": "rocket",
            "color": "blue",
        }

    if week_total == 0:
        return {
            "greeting": f"Hola, {first_name}!",
            "message": "Tienes un plan activo. Empieza a marcar las comidas que consumes para ver tu progreso.",
            "emoji": "plan",
            "color": "amber",
        }

    week_pct = round(week_consumed / week_total * 100) if week_total > 0 else 0

    if today_total > 0:
        if today_consumed == today_total:
            return {
                "greeting": f"Dia completado, {first_name}!",
                "message": f"Registraste las {today_total} comidas de hoy. Eso es constancia real. Sigue manana igual!",
                "emoji": "check",
                "color": "green",
            }
        if today_consumed == 0:
            return {
                "greeting": f"Hola, {first_name}!",
                "message": f"Hoy tienes {today_total} comidas planificadas. Empieza a marcarlas a medida que las consumes.",
                "emoji": "food",
                "color": "amber",
            }
        remaining = today_total - today_consumed
        return {
            "greeting": f"Vas bien, {first_name}!",
            "message": f"Ya llevas {today_consumed}/{today_total} comidas hoy. {remaining} mas y completaras el dia.",
            "emoji": "up",
            "color": "green",
        }

    # No meals today (plan is from another week)
    if week_pct >= 80:
        return {
            "greeting": f"Gran semana, {first_name}!",
            "message": f"Seguiste el {week_pct}% de tu plan esta semana. Esa disciplina marca la diferencia.",
            "emoji": "trophy",
            "color": "green",
        }
    if week_pct >= 50:
        return {
            "greeting": f"Buen trabajo, {first_name}!",
            "message": f"Seguiste el {week_pct}% de tu plan. Cada comida registrada te acerca a tu objetivo.",
            "emoji": "chart",
            "color": "green",
        }
    if week_consumed > 0:
        return {
            "greeting": f"Hola, {first_name}!",
            "message": f"Llevas {week_consumed} comidas registradas esta semana. Intenta marcarlas todas para ver tu progreso real.",
            "emoji": "idea",
            "color": "amber",
        }
    return {
        "greeting": f"Hola, {first_name}!",
        "message": "Tienes un plan listo. Recuerda marcar las comidas que consumes para seguir tu progreso.",
        "emoji": "wave",
        "color": "amber",
    }


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    latest_plan = None
    plans_count = 0
    if profile:
        latest_plan = (
            db.query(MealPlan)
            .filter(MealPlan.profile_id == profile.id)
            .order_by(MealPlan.created_at.desc())
            .first()
        )
        plans_count = db.query(MealPlan).filter(MealPlan.profile_id == profile.id).count()

    stock_count = db.query(FoodStock).filter(FoodStock.user_id == current_user.id).count()

    stats = None
    greeting = None
    if profile:
        bmr = calculate_bmr(profile)
        activity_days = get_activity_days_list(profile)
        tdee = calculate_tdee(bmr, len(activity_days))
        target = calculate_target_calories(profile, tdee)
        activity_names = [DAYS_OF_WEEK[d] for d in activity_days]
        stats = {
            "bmr": round(bmr),
            "tdee": round(tdee),
            "target_calories": round(target),
            "activity_days": activity_names,
        }

        # Compute consumed meal counts for greeting
        today_consumed = 0
        today_total = 0
        week_consumed = 0
        week_total = 0
        if latest_plan:
            today_weekday = date.today().weekday()
            days_since = (date.today() - latest_plan.week_start).days
            is_current_week = 0 <= days_since <= 6

            for meal in latest_plan.meals:
                week_total += 1
                if meal.consumed:
                    week_consumed += 1
                if is_current_week and meal.day_of_week == today_weekday:
                    today_total += 1
                    if meal.consumed:
                        today_consumed += 1

        greeting = _build_greeting(profile, plans_count, today_consumed, today_total, week_consumed, week_total)

    return templates.TemplateResponse(request, "dashboard.html", {
        "profile": profile,
        "latest_plan": latest_plan,
        "stock_count": stock_count,
        "stats": stats,
        "greeting": greeting,
        "current_user": current_user,
    })
