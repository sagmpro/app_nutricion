import json
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.profile import UserProfile
from app.models.meal_plan import MealPlan
from app.models.food_stock import FoodStock
from app.services.nutrition import calculate_bmr, calculate_tdee, calculate_target_calories, get_activity_days_list, DAYS_OF_WEEK

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    profile = db.query(UserProfile).first()
    latest_plan = (
        db.query(MealPlan).order_by(MealPlan.created_at.desc()).first()
        if profile else None
    )
    stock_count = db.query(FoodStock).count()

    stats = None
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

    return templates.TemplateResponse(request, "dashboard.html", {
        "profile": profile,
        "latest_plan": latest_plan,
        "stock_count": stock_count,
        "stats": stats,
    })
