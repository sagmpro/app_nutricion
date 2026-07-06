import json
from datetime import datetime
from itertools import zip_longest
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.profile import UserProfile
from app.models.saved_meal import SavedMeal, classify_health
from app.models.meal import MEAL_TYPE_LABELS, MEAL_TYPES
from app.models.exercise_type import ExerciseType
from app.models.activity_day import ActivityDayConfig
from app.services.auth_service import get_current_user
from app.services.nutrition import (
    calculate_bmr, calculate_tdee, calculate_target_calories,
    get_activity_days_list, get_effective_meal_times, DAYS_LETTERS, DAYS_OF_WEEK,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/perfil")
def perfil_form(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    activity_days = get_activity_days_list(profile) if profile else []
    exercise_types = db.query(ExerciseType).filter(
        (ExerciseType.is_default == True) | (ExerciseType.user_id == current_user.id)
    ).order_by(ExerciseType.id).all()

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

    day_configs: dict[int, list] = {}
    for c in (profile.activity_day_configs if profile else []):
        day_configs.setdefault(c.day_of_week, []).append(c)

    return templates.TemplateResponse(request, "profile/form.html", {
        "profile": profile,
        "activity_days": activity_days,
        "day_configs": day_configs,
        "exercise_types": exercise_types,
        "days_letters": DAYS_LETTERS,
        "days_names": DAYS_OF_WEEK,
        "stats": stats,
        "success": request.query_params.get("success"),
        "enabled_meals": enabled_meals,
        "meal_times": meal_times,
        "effective_meal_times": effective_meal_times,
        "current_user": current_user,
    })


@router.post("/perfil/proponer-horario")
async def proponer_horario(request: Request, db: Session = Depends(get_db)):
    from app.services.claude_service import propose_meal_schedule
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
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
    goal_description: str = Form(default=""),
    target_calories: str = Form(default=""),
    current_fat_pct: str = Form(default=""),
    target_fat_pct: str = Form(default=""),
    target_days: str = Form(default=""),
    dietary_type: str = Form(default="omnivoro"),
    food_intolerances: str = Form(default=""),
    disliked_foods: str = Form(default=""),
    preferred_foods: str = Form(default=""),
    training_time: str = Form(default=""),
    training_end: str = Form(default=""),
    cooking_facilities: str = Form(default=""),
    max_meal_repeats: int = Form(default=2),
    country: str = Form(default=""),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    form_data = await request.form()

    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
        db.flush()

    # Rebuild ActivityDayConfigs from form — multiple sessions per day via getlist
    db.query(ActivityDayConfig).filter(ActivityDayConfig.profile_id == profile.id).delete()
    activity_days = []
    first_start = first_end = None
    for i in range(7):
        if form_data.get(f"day_{i}_active") == "1":
            et_values = form_data.getlist(f"day_{i}_exercise_type")
            start_values = form_data.getlist(f"day_{i}_start")
            end_values = form_data.getlist(f"day_{i}_end")
            sessions_added = 0
            for et_raw, start, end in zip_longest(et_values, start_values, end_values, fillvalue=""):
                et_id = int(et_raw) if str(et_raw).strip().isdigit() else None
                start = (start or "").strip() or None
                end = (end or "").strip() or None
                db.add(ActivityDayConfig(
                    profile_id=profile.id,
                    day_of_week=i,
                    exercise_type_id=et_id,
                    start_time=start,
                    end_time=end,
                ))
                sessions_added += 1
                if first_start is None and start:
                    first_start = start
                if first_end is None and end:
                    first_end = end
            if sessions_added:
                activity_days.append(i)

    profile.name = name
    profile.age = age
    profile.gender = gender
    profile.weight_kg = weight_kg
    profile.height_cm = height_cm
    profile.goal_type = goal_type
    profile.goal_description = goal_description.strip() or None
    profile.target_calories = int(target_calories) if target_calories.strip() else None
    profile.current_fat_pct = float(current_fat_pct) if current_fat_pct.strip() else None
    profile.target_fat_pct = float(target_fat_pct) if target_fat_pct.strip() else None
    profile.target_days = int(target_days) if target_days.strip() else None
    profile.activity_days = json.dumps(activity_days)
    profile.dietary_type = dietary_type
    profile.food_intolerances = food_intolerances.strip() or None
    profile.disliked_foods = disliked_foods.strip() or None
    profile.preferred_foods = preferred_foods.strip() or None
    # Keep global training_time/training_end as fallback (derived from first active day)
    profile.training_time = first_start or training_time.strip() or None
    profile.training_end = first_end or training_end.strip() or None
    profile.cooking_facilities = cooking_facilities.strip() or None
    profile.max_meal_repeats = max(1, min(7, max_meal_repeats))
    profile.country = country.strip() or None

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


# ---- Recetario ----

@router.get("/perfil/recetario")
def recetario(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meals = (
        db.query(SavedMeal)
        .filter(SavedMeal.user_id == current_user.id)
        .order_by(SavedMeal.last_served_at.desc())
        .all()
    )
    grouped: dict[str, list] = {}
    for m in meals:
        grouped.setdefault(m.meal_type, []).append(m)
    grouped_meals = [(t, MEAL_TYPE_LABELS.get(t, t), grouped[t]) for t in MEAL_TYPES if t in grouped]
    for t, ms in grouped.items():
        if t not in MEAL_TYPES:
            grouped_meals.append((t, t.capitalize(), ms))

    return templates.TemplateResponse(request, "profile/recetario.html", {
        "current_user": current_user,
        "saved_meals": meals,
        "grouped_meals": grouped_meals,
        "meal_type_labels": MEAL_TYPE_LABELS,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/perfil/recetario/agregar")
async def agregar_receta(
    request: Request,
    name: str = Form(...),
    meal_type: str = Form(...),
    description: str = Form(default=""),
    calories: int = Form(default=0),
    protein_g: float = Form(default=0.0),
    carbs_g: float = Form(default=0.0),
    fat_g: float = Form(default=0.0),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    name = name.strip()
    if not name:
        return RedirectResponse("/perfil/recetario?error=El+nombre+es+requerido", status_code=303)

    existing = db.query(SavedMeal).filter(
        SavedMeal.user_id == current_user.id,
        SavedMeal.name == name,
        SavedMeal.meal_type == meal_type,
    ).first()
    if existing:
        return RedirectResponse("/perfil/recetario?error=Ya+existe+ese+plato+en+ese+tipo+de+comida", status_code=303)

    db.add(SavedMeal(
        user_id=current_user.id,
        name=name,
        meal_type=meal_type,
        description=description.strip() or None,
        calories=max(0, calories),
        protein_g=max(0.0, protein_g),
        carbs_g=max(0.0, carbs_g),
        fat_g=max(0.0, fat_g),
        ingredients_json="[]",
        times_served=0,
    ))
    db.commit()
    return RedirectResponse("/perfil/recetario?success=Plato+agregado+correctamente", status_code=303)


@router.post("/perfil/recetario/{meal_id}/rating")
async def rate_meal(
    meal_id: int,
    request: Request,
    db: Session = Depends(get_db),
    rating: int = Form(...),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)
    meal = db.query(SavedMeal).filter(SavedMeal.id == meal_id, SavedMeal.user_id == current_user.id).first()
    if meal:
        meal.rating = max(1, min(5, rating))
        db.commit()
    return RedirectResponse("/perfil/recetario", status_code=303)


@router.post("/perfil/recetario/{meal_id}/toggle-excluir")
async def toggle_excluir(meal_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)
    meal = db.query(SavedMeal).filter(SavedMeal.id == meal_id, SavedMeal.user_id == current_user.id).first()
    if meal:
        meal.is_excluded = not meal.is_excluded
        db.commit()
    return RedirectResponse("/perfil/recetario", status_code=303)


@router.post("/perfil/recetario/{meal_id}/eliminar")
async def eliminar_receta(meal_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)
    meal = db.query(SavedMeal).filter(SavedMeal.id == meal_id, SavedMeal.user_id == current_user.id).first()
    if meal:
        db.delete(meal)
        db.commit()
    return RedirectResponse("/perfil/recetario", status_code=303)


@router.post("/perfil/recetario/eliminar-multiple")
async def eliminar_multiple(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)
    form_data = await request.form()
    raw_ids = form_data.getlist("meal_ids")
    ids = [int(i) for i in raw_ids if str(i).strip().isdigit()]
    if ids:
        db.query(SavedMeal).filter(
            SavedMeal.id.in_(ids),
            SavedMeal.user_id == current_user.id,
        ).delete(synchronize_session=False)
        db.commit()
    return RedirectResponse(f"/perfil/recetario?success={len(ids)}+receta{'s' if len(ids) != 1 else ''}+eliminada{'s' if len(ids) != 1 else ''}", status_code=303)


@router.post("/perfil/recetario/generar-ia")
async def generar_receta_ia(
    request: Request,
    db: Session = Depends(get_db),
    meal_type: str = Form(...),
    description: str = Form(default=""),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    from app.services.claude_service import generate_meal_for_recetario
    try:
        result = generate_meal_for_recetario(profile, meal_type, description.strip())
    except Exception as e:
        return RedirectResponse(f"/perfil/recetario?error=Error+al+generar+receta:+{str(e)[:60]}", status_code=303)

    existing = db.query(SavedMeal).filter(
        SavedMeal.user_id == current_user.id,
        SavedMeal.name == result.get("nombre", ""),
        SavedMeal.meal_type == meal_type,
    ).first()
    if existing:
        return RedirectResponse("/perfil/recetario?success=La+receta+ya+estaba+en+tu+recetario", status_code=303)

    import types as _types
    meal_obj = _types.SimpleNamespace(
        name=result.get("nombre", "Receta IA"),
        meal_type=meal_type,
        ingredients_json=json.dumps(result.get("ingredientes", []), ensure_ascii=False),
        calories=result.get("calorias", 0),
        protein_g=result.get("proteinas_g", 0.0),
        carbs_g=result.get("carbohidratos_g", 0.0),
        fat_g=result.get("grasas_g", 0.0),
        description=result.get("descripcion", ""),
        recipe_text=None,
    )
    upsert_saved_meal(db, current_user.id, meal_obj)
    name_enc = result.get("nombre", "Receta").replace(" ", "+")
    return RedirectResponse(f"/perfil/recetario?success=Receta+generada:+{name_enc}", status_code=303)
