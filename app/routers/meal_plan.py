import json
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.profile import UserProfile
from app.models.meal_plan import MealPlan
from app.models.meal import Meal, MEAL_TYPE_ORDER, MEAL_TYPE_LABELS
from app.services.nutrition import (
    calculate_bmr, calculate_tdee, calculate_target_calories,
    get_activity_days_list, DAYS_OF_WEEK, DAYS_SHORT,
)
from app.services.claude_service import generate_meal_plan as claude_generate

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _build_days_data(meal_plan: MealPlan) -> list[dict]:
    days = []
    for day_num in range(7):
        day_meals = sorted(
            [m for m in meal_plan.meals if m.day_of_week == day_num],
            key=lambda m: m.meal_order,
        )
        days.append({
            "name": DAYS_OF_WEEK[day_num],
            "short": DAYS_SHORT[day_num],
            "day_num": day_num,
            "meals": [
                {
                    "id": m.id,
                    "type": m.meal_type,
                    "type_label": MEAL_TYPE_LABELS.get(m.meal_type, m.meal_type),
                    "name": m.name,
                    "description": m.description,
                    "calories": m.calories,
                    "protein_g": round(m.protein_g, 1),
                    "carbs_g": round(m.carbs_g, 1),
                    "fat_g": round(m.fat_g, 1),
                    "ingredients": json.loads(m.ingredients_json or "[]"),
                }
                for m in day_meals
            ],
            "total_calories": sum(m.calories for m in day_meals),
            "total_protein": round(sum(m.protein_g for m in day_meals), 1),
            "total_carbs": round(sum(m.carbs_g for m in day_meals), 1),
            "total_fat": round(sum(m.fat_g for m in day_meals), 1),
        })
    return days


def _save_meals_from_response(db: Session, plan_id: int, result: dict):
    for day_data in result.get("plan", []):
        day_num = day_data.get("dia_numero", 0)
        for meal_data in day_data.get("comidas", []):
            meal_type = meal_data.get("tipo", "desayuno")
            meal = Meal(
                meal_plan_id=plan_id,
                day_of_week=day_num,
                meal_type=meal_type,
                meal_order=MEAL_TYPE_ORDER.get(meal_type, 0),
                name=meal_data.get("nombre", ""),
                description=meal_data.get("descripcion", ""),
                calories=int(meal_data.get("calorias", 0)),
                protein_g=float(meal_data.get("proteinas_g", 0)),
                carbs_g=float(meal_data.get("carbohidratos_g", 0)),
                fat_g=float(meal_data.get("grasas_g", 0)),
                ingredients_json=json.dumps(meal_data.get("ingredientes", [])),
            )
            db.add(meal)


@router.get("/plan")
def plan_index(request: Request, db: Session = Depends(get_db)):
    latest = db.query(MealPlan).order_by(MealPlan.created_at.desc()).first()
    if latest:
        return RedirectResponse(f"/plan/{latest.id}", status_code=303)
    profile = db.query(UserProfile).first()
    return templates.TemplateResponse(request, "meal_plan/no_plan.html", {
        "profile": profile,
        "error": request.query_params.get("error"),
    })


@router.post("/plan/generar")
def generar_plan(request: Request, db: Session = Depends(get_db)):
    profile = db.query(UserProfile).first()
    if not profile:
        return RedirectResponse("/perfil?error=Completa+tu+perfil+primero", status_code=303)

    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    meal_plan = MealPlan(profile_id=profile.id, week_start=week_start, status="pending")
    db.add(meal_plan)
    db.commit()
    db.refresh(meal_plan)

    try:
        bmr = calculate_bmr(profile)
        activity_days = get_activity_days_list(profile)
        tdee = calculate_tdee(bmr, len(activity_days))
        target = calculate_target_calories(profile, tdee)

        result = claude_generate(profile, bmr, tdee, target)
        meal_plan.raw_json = json.dumps(result)
        _save_meals_from_response(db, meal_plan.id, result)
        db.commit()
        return RedirectResponse(f"/plan/{meal_plan.id}", status_code=303)

    except Exception as e:
        db.delete(meal_plan)
        db.commit()
        return RedirectResponse(f"/plan?error={str(e)[:100]}", status_code=303)


@router.get("/plan/{plan_id}")
def ver_plan(request: Request, plan_id: int, db: Session = Depends(get_db)):
    meal_plan = db.query(MealPlan).filter(MealPlan.id == plan_id).first()
    if not meal_plan:
        return RedirectResponse("/plan", status_code=303)

    days = _build_days_data(meal_plan)
    all_plans = db.query(MealPlan).order_by(MealPlan.created_at.desc()).all()

    return templates.TemplateResponse(request, "meal_plan/view.html", {
        "meal_plan": meal_plan,
        "days": days,
        "all_plans": all_plans,
        "has_shopping_list": meal_plan.shopping_list is not None,
        "error": request.query_params.get("error"),
    })


@router.post("/plan/{plan_id}/aprobar")
def aprobar_plan(plan_id: int, db: Session = Depends(get_db)):
    meal_plan = db.query(MealPlan).filter(MealPlan.id == plan_id).first()
    if meal_plan:
        meal_plan.status = "approved"
        db.commit()
    return RedirectResponse(f"/plan/{plan_id}", status_code=303)


@router.post("/plan/{plan_id}/regenerar")
def regenerar_plan(plan_id: int, db: Session = Depends(get_db)):
    meal_plan = db.query(MealPlan).filter(MealPlan.id == plan_id).first()
    if not meal_plan:
        return RedirectResponse("/plan", status_code=303)

    profile = meal_plan.profile
    for meal in list(meal_plan.meals):
        db.delete(meal)
    db.commit()

    try:
        bmr = calculate_bmr(profile)
        activity_days = get_activity_days_list(profile)
        tdee = calculate_tdee(bmr, len(activity_days))
        target = calculate_target_calories(profile, tdee)

        result = claude_generate(profile, bmr, tdee, target)
        meal_plan.raw_json = json.dumps(result)
        meal_plan.status = "pending"
        _save_meals_from_response(db, meal_plan.id, result)
        db.commit()
        return RedirectResponse(f"/plan/{plan_id}", status_code=303)

    except Exception as e:
        return RedirectResponse(f"/plan/{plan_id}?error={str(e)[:100]}", status_code=303)
