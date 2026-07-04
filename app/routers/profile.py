import json
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.profile import UserProfile
from app.services.nutrition import (
    calculate_bmr, calculate_tdee, calculate_target_calories,
    get_activity_days_list, get_effective_meal_times, DAYS_LETTERS, DAYS_OF_WEEK,
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

    all_meal_types = ["desayuno", "media_manana", "almuerzo", "media_tarde", "cena"]
    try:
        enabled_meals = json.loads(profile.enabled_meals) if profile and profile.enabled_meals else all_meal_types
    except (ValueError, TypeError):
        enabled_meals = all_meal_types
    try:
        meal_times = json.loads(profile.meal_times) if profile and profile.meal_times else {}
    except (ValueError, TypeError):
        meal_times = {}

    effective_meal_times = get_effective_meal_times(profile)

    return templates.TemplateResponse(request, "profile/form.html", {
        "profile": profile,
        "activity_days": activity_days,
        "days_letters": DAYS_LETTERS,
        "days_names": DAYS_OF_WEEK,
        "stats": stats,
        "success": request.query_params.get("success"),
        "enabled_meals": enabled_meals,
        "meal_times": meal_times,
        "effective_meal_times": effective_meal_times,
    })


@router.post("/perfil/proponer-horario")
async def proponer_horario(db: Session = Depends(get_db)):
    from app.services.claude_service import propose_meal_schedule
    profile = db.query(UserProfile).first()
    if not profile:
        return JSONResponse({"error": "Perfil no encontrado"}, status_code=404)
    try:
        result = propose_meal_schedule(profile)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)[:120]}, status_code=500)


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
    dietary_type: str = Form(default="omnivoro"),
    food_intolerances: str = Form(default=""),
    disliked_foods: str = Form(default=""),
    preferred_foods: str = Form(default=""),
    training_time: str = Form(default=""),
    cooking_facilities: str = Form(default=""),
    max_meal_repeats: int = Form(default=2),
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
    profile.dietary_type = dietary_type
    profile.food_intolerances = food_intolerances.strip() or None
    profile.disliked_foods = disliked_foods.strip() or None
    profile.preferred_foods = preferred_foods.strip() or None
    profile.training_time = training_time.strip() or None
    profile.cooking_facilities = cooking_facilities.strip() or None
    profile.max_meal_repeats = max(1, min(7, max_meal_repeats))

    all_meal_types = ["desayuno", "media_manana", "almuerzo", "media_tarde", "cena"]
    enabled = [mt for mt in all_meal_types if form_data.get(f"meal_enabled_{mt}") == "1"]
    profile.enabled_meals = json.dumps(enabled if enabled else all_meal_types)
    times = {}
    for mt in all_meal_types:
        if form_data.get(f"meal_automode_{mt}") == "1":
            times[mt] = "auto"
        else:
            t = form_data.get(f"meal_time_{mt}", "").strip()
            if t:
                times[mt] = t
    profile.meal_times = json.dumps(times) if times else None

    profile.updated_at = datetime.now()
    db.commit()
    return RedirectResponse("/perfil?success=1", status_code=303)
