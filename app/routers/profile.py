import json
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.profile import UserProfile
from app.services.nutrition import (
    calculate_bmr, calculate_tdee, calculate_target_calories,
    get_activity_days_list, DAYS_LETTERS, DAYS_OF_WEEK,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/perfil")
def perfil_form(request: Request, db: Session = Depends(get_db)):
    profile = db.query(UserProfile).first()
    activity_days = get_activity_days_list(profile) if profile else []

    stats = None
    if profile:
        bmr = calculate_bmr(profile)
        tdee = calculate_tdee(bmr, len(activity_days))
        target = calculate_target_calories(profile, tdee)
        stats = {"bmr": round(bmr), "tdee": round(tdee), "target_calories": round(target)}

    return templates.TemplateResponse(request, "profile/form.html", {
        "profile": profile,
        "activity_days": activity_days,
        "days_letters": DAYS_LETTERS,
        "days_names": DAYS_OF_WEEK,
        "stats": stats,
        "success": request.query_params.get("success"),
    })


@router.post("/perfil")
async def perfil_save(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    age: int = Form(...),
    gender: str = Form(...),
    weight_kg: float = Form(...),
    height_cm: float = Form(...),
    goal_type: str = Form(...),
    target_calories: str = Form(default=""),
    current_fat_pct: str = Form(default=""),
    target_fat_pct: str = Form(default=""),
    target_days: str = Form(default=""),
):
    form_data = await request.form()
    activity_days = []
    for i in range(7):
        if form_data.get(f"day_{i}") == "1":
            activity_days.append(i)

    profile = db.query(UserProfile).first()
    if not profile:
        profile = UserProfile()
        db.add(profile)

    profile.name = name
    profile.age = age
    profile.gender = gender
    profile.weight_kg = weight_kg
    profile.height_cm = height_cm
    profile.goal_type = goal_type
    profile.target_calories = int(target_calories) if target_calories.strip() else None
    profile.current_fat_pct = float(current_fat_pct) if current_fat_pct.strip() else None
    profile.target_fat_pct = float(target_fat_pct) if target_fat_pct.strip() else None
    profile.target_days = int(target_days) if target_days.strip() else None
    profile.activity_days = json.dumps(activity_days)
    profile.updated_at = datetime.now()

    db.commit()
    return RedirectResponse("/perfil?success=1", status_code=303)
