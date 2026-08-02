import json
from datetime import date, datetime, timedelta
from urllib.parse import quote as _urlquote
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.profile import UserProfile
from app.models.meal_plan import MealPlan
from app.models.meal import Meal, MEAL_TYPE_ORDER, MEAL_TYPE_LABELS, MEAL_TYPES
from app.models.food_stock import FoodStock
from app.models.saved_meal import SavedMeal, upsert_saved_meal
from app.models.activity_day import ActivityDayConfig
from app.services.auth_service import get_current_user
from app.services import household_service as hs
from app.services.ai_limits import get_remaining, log_action, get_all_limits, plan_from_recetario, meal_from_recetario
from app.services.nutrition import (
    calculate_bmr, calculate_tdee, calculate_target_calories,
    get_activity_days_list, get_effective_meal_times, DAYS_OF_WEEK, DAYS_SHORT,
)
from app.services.claude_service import (
    generate_meal_plan as claude_generate,
    generate_single_meal as claude_single_meal,
    generate_real_recipe_meal as claude_real_recipe,
    buscar_plato_por_nombre as claude_buscar_plato,
    generate_cheat_meal as claude_cheat_meal,
    analyze_food_photo as claude_analyze_photo,
    recalculate_calories_from_ingredients as claude_recalculate,
    generate_recipe as claude_generate_recipe,
    suggest_meal_names as claude_suggest_names,
    set_token_user_id,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _build_days_data(meal_plan: MealPlan, profile=None) -> list[dict]:
    from app.services.nutrition import get_effective_meal_times

    # Index ActivityDayConfigs by day_of_week (list — multiple sessions per day)
    day_config_map: dict[int, list] = {}
    if profile:
        for cfg in getattr(profile, "activity_day_configs", []):
            day_config_map.setdefault(cfg.day_of_week, []).append(cfg)

    days = []
    days_present = sorted({m.day_of_week for m in meal_plan.meals}) or list(range(7))
    for day_num in days_present:
        day_cfgs = day_config_map.get(day_num, [])
        is_training_day = len(day_cfgs) > 0
        # Use first session (earliest by order in DB) for meal-time calculation
        first_cfg = day_cfgs[0] if day_cfgs else None
        meal_times = get_effective_meal_times(profile, is_training_day, day_config=first_cfg) if profile else {}

        day_meals = sorted(
            [m for m in meal_plan.meals if m.day_of_week == day_num],
            key=lambda m: m.meal_order,
        )
        consumed_cals = sum(
            (m.actual_calories or m.calories) for m in day_meals if m.consumed
        )

        # Build session summaries for display
        sessions = []
        for cfg in day_cfgs:
            et = cfg.exercise_type
            sessions.append({
                "exercise_type": et.name if et else None,
                "exercise_icon": et.icon if et else None,
                "training_start": cfg.start_time,
                "training_end": cfg.end_time,
            })
        # Backward-compat single fields (first session)
        et0 = day_cfgs[0].exercise_type if day_cfgs else None
        days.append({
            "name": DAYS_OF_WEEK[day_num],
            "short": DAYS_SHORT[day_num],
            "day_num": day_num,
            "is_training_day": is_training_day,
            "sessions": sessions,
            "exercise_type": et0.name if et0 else None,
            "exercise_icon": et0.icon if et0 else None,
            "training_start": day_cfgs[0].start_time if day_cfgs else None,
            "training_end": day_cfgs[0].end_time if day_cfgs else None,
            "meal_times": meal_times,
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
                    "consumed": m.consumed,
                    "actual_calories": m.actual_calories,
                    "actual_name": m.actual_name,
                    "has_recipe": bool(m.recipe_text),
                }
                for m in day_meals
            ],
            "total_calories": sum(m.calories for m in day_meals),
            "consumed_calories": consumed_cals,
            "total_protein": round(sum(m.protein_g for m in day_meals), 1),
            "total_carbs": round(sum(m.carbs_g for m in day_meals), 1),
            "total_fat": round(sum(m.fat_g for m in day_meals), 1),
        })
    return days


def _save_meals_from_response(db: Session, plan_id: int, result: dict, user_id: int = None):
    from app.models.saved_meal import upsert_saved_meal
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
            if user_id:
                upsert_saved_meal(db, user_id, meal)


def _get_user_profile(db: Session, user_id: int):
    """Get profile scoped to current user."""
    return db.query(UserProfile).filter(UserProfile.user_id == user_id).first()


def _get_user_plan(db: Session, plan_id: int, user_id: int):
    """Get a meal plan belonging to the user or a shared household plan."""
    from app.models.household import HouseholdMember
    plan = (
        db.query(MealPlan)
        .join(UserProfile)
        .filter(MealPlan.id == plan_id, UserProfile.user_id == user_id)
        .first()
    )
    if plan:
        return plan
    member = db.query(HouseholdMember).filter(HouseholdMember.user_id == user_id).first()
    if member:
        return db.query(MealPlan).filter(
            MealPlan.id == plan_id,
            MealPlan.household_id == member.household_id,
            MealPlan.is_shared == True,
        ).first()
    return None


@router.get("/plan")
def plan_index(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    profile = _get_user_profile(db, current_user.id)
    if profile:
        latest = (
            db.query(MealPlan)
            .filter(MealPlan.profile_id == profile.id)
            .order_by(MealPlan.created_at.desc())
            .first()
        )
        if latest:
            return RedirectResponse(f"/plan/{latest.id}", status_code=303)

    return templates.TemplateResponse(request, "meal_plan/no_plan.html", {
        "profile": profile,
        "error": request.query_params.get("error"),
        "current_user": current_user,
    })


@router.post("/plan/generar")
async def generar_plan(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    profile = _get_user_profile(db, current_user.id)
    if not profile:
        return RedirectResponse("/perfil?error=Completa+tu+perfil+primero", status_code=303)

    form = await request.form()
    if form.get("dietary_type"):
        profile.dietary_type = form.get("dietary_type")
    db.commit()

    week_start_str = form.get("week_start", "")
    try:
        week_start = datetime.strptime(week_start_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        week_start = date.today()

    meal_plan = MealPlan(profile_id=profile.id, week_start=week_start, status="pending")
    db.add(meal_plan)
    db.commit()
    db.refresh(meal_plan)

    try:
        bmr = calculate_bmr(profile)
        activity_days = get_activity_days_list(profile)
        tdee = calculate_tdee(bmr, len(activity_days))
        target = calculate_target_calories(profile, tdee)

        user_meals = db.query(SavedMeal).filter(
            SavedMeal.user_id == current_user.id,
            SavedMeal.is_excluded == False,  # noqa: E712
        ).all()

        if get_remaining(db, current_user.id, "plan_generate") == 0:
            result = plan_from_recetario(db, current_user.id, profile, week_start)
            success_msg = _urlquote("Plan generado desde tu recetario (límite de IA alcanzado este mes)")
        else:
            set_token_user_id(current_user.id)
            result = claude_generate(profile, bmr, tdee, target, saved_meals=user_meals or None, week_start=week_start)
            log_action(db, current_user.id, "plan_generate")
            success_msg = _urlquote("¡Plan generado exitosamente!")
        meal_plan.raw_json = json.dumps(result)
        _save_meals_from_response(db, meal_plan.id, result, user_id=current_user.id)
        db.commit()
        return RedirectResponse(f"/plan/{meal_plan.id}?success={success_msg}", status_code=303)

    except Exception as e:
        db.delete(meal_plan)
        db.commit()
        return RedirectResponse(f"/plan?error={_urlquote(str(e)[:120])}", status_code=303)


@router.get("/plan/{plan_id}")
def ver_plan(request: Request, plan_id: int, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return RedirectResponse("/plan", status_code=303)

    profile = _get_user_profile(db, current_user.id)
    days = _build_days_data(meal_plan, profile)
    all_plans = (
        db.query(MealPlan)
        .filter(MealPlan.profile_id == profile.id)
        .order_by(MealPlan.created_at.desc())
        .all()
    ) if profile else []

    household_member = hs.get_member(current_user.id, db)

    from datetime import timedelta
    week_end = meal_plan.week_start + timedelta(days=6 - meal_plan.week_start.weekday())
    any_consumed = any(m.consumed for m in meal_plan.meals)

    ai_limits = get_all_limits(db, current_user.id)

    return templates.TemplateResponse(request, "meal_plan/view.html", {
        "meal_plan": meal_plan,
        "days": days,
        "all_plans": all_plans,
        "has_shopping_list": meal_plan.shopping_list is not None,
        "week_end": week_end,
        "any_consumed": any_consumed,
        "error": request.query_params.get("error"),
        "success": request.query_params.get("success"),
        "current_user": current_user,
        "household_member": household_member,
        "ai_limits": ai_limits,
    })


@router.post("/plan/{plan_id}/comida/{meal_id}/regenerar")
def regenerar_comida(plan_id: int, meal_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    import json as _json
    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return RedirectResponse("/plan", status_code=303)

    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    if not meal:
        return RedirectResponse(f"/plan/{plan_id}", status_code=303)

    profile = meal_plan.profile

    base_pct = {"desayuno": 0.25, "media_manana": 0.10, "almuerzo": 0.35, "media_tarde": 0.10, "cena": 0.20}
    bmr = calculate_bmr(profile)
    activity_days = get_activity_days_list(profile)
    tdee = calculate_tdee(bmr, len(activity_days))
    target_total = calculate_target_calories(profile, tdee)
    try:
        enabled = json.loads(profile.enabled_meals) if getattr(profile, "enabled_meals", None) else list(base_pct)
    except (ValueError, TypeError):
        enabled = list(base_pct)
    total_pct = sum(base_pct[m] for m in enabled if m in base_pct) or 1.0
    target_calories = int(target_total * (base_pct.get(meal.meal_type, 0.20) / total_pct))

    other_meals = [m.name for m in meal_plan.meals if m.day_of_week == meal.day_of_week and m.id != meal_id]
    new_regen_count = (meal.regen_count or 0) + 1

    set_token_user_id(current_user.id)
    try:
        if new_regen_count >= 3:
            # Use detailed real-recipe prompt after 3 regenerations
            result = claude_real_recipe(
                meal_name=meal.name,
                meal_type=meal.meal_type,
                target_calories=target_calories,
                profile=profile,
            )
        else:
            result = claude_single_meal(
                profile=profile,
                meal_type=meal.meal_type,
                day_name=DAYS_OF_WEEK[meal.day_of_week],
                target_calories=target_calories,
                current_meal_name=meal.name,
                other_meals=other_meals,
            )
        meal.name = result.get("nombre", meal.name)
        meal.description = result.get("descripcion", meal.description)
        meal.calories = int(result.get("calorias", meal.calories))
        meal.protein_g = float(result.get("proteinas_g", meal.protein_g))
        meal.carbs_g = float(result.get("carbohidratos_g", meal.carbs_g))
        meal.fat_g = float(result.get("grasas_g", meal.fat_g))
        meal.ingredients_json = _json.dumps(result.get("ingredientes", []))
        # Store detailed recipe if provided
        if result.get("receta_detallada"):
            meal.recipe_text = _json.dumps({"pasos": result["receta_detallada"].split("\n"), "fuente": "receta_detallada"})
        meal.regen_count = new_regen_count
        upsert_saved_meal(db, current_user.id, meal)
        db.commit()
    except Exception as e:
        return RedirectResponse(f"/plan/{plan_id}?error={_urlquote(f'Error regenerando comida: {str(e)[:80]}')}&day={meal.day_of_week}", status_code=303)

    return RedirectResponse(f"/plan/{plan_id}?day={meal.day_of_week}", status_code=303)


@router.post("/plan/{plan_id}/eliminar")
def eliminar_plan(plan_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if meal_plan:
        db.delete(meal_plan)
        db.commit()
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/{plan_id}/aprobar")
def aprobar_plan(plan_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if meal_plan:
        meal_plan.status = "approved"
        db.commit()
    return RedirectResponse(f"/plan/{plan_id}", status_code=303)


def _deduct_from_stock(db: Session, meal: Meal, user_id: int) -> None:
    """Best-effort deduction of meal ingredients from household/personal stock when consumed."""
    ingredients = json.loads(meal.ingredients_json or "[]")
    scope = hs.stock_filter(user_id, db)
    for ing in ingredients:
        name = ing.get("nombre", "").strip()
        quantity = float(ing.get("cantidad", 0))
        unit = ing.get("unidad", "")
        if not name or quantity <= 0:
            continue
        stock_item = (
            db.query(FoodStock)
            .filter(FoodStock.name.ilike(name), scope)
            .first()
        )
        if stock_item and stock_item.unit == unit:
            stock_item.quantity = max(0.0, stock_item.quantity - quantity)
            if stock_item.quantity == 0:
                db.delete(stock_item)


@router.post("/plan/{plan_id}/comida/{meal_id}/consumir")
def consumir_comida(plan_id: int, meal_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return RedirectResponse("/plan", status_code=303)

    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    day_num = meal.day_of_week if meal else 0
    if meal:
        meal.consumed = not meal.consumed
        if not meal.consumed:
            meal.actual_calories = None
            meal.actual_name = None
        else:
            _deduct_from_stock(db, meal, current_user.id)
        db.commit()
    return RedirectResponse(f"/plan/{plan_id}?day={day_num}", status_code=303)


@router.post("/plan/{plan_id}/comida/{meal_id}/foto-preview")
async def foto_consumida_preview(
    plan_id: int,
    meal_id: int,
    request: Request,
    db: Session = Depends(get_db),
    foto: UploadFile = File(...),
):
    """Analyze a food photo and return JSON — used by the AJAX confirmation modal."""
    current_user = get_current_user(request, db)
    if current_user:
        set_token_user_id(current_user.id)
    try:
        image_bytes = await foto.read()
        media_type = foto.content_type or "image/jpeg"
        result = claude_analyze_photo(image_bytes, media_type)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)[:100]}, status_code=500)


@router.post("/plan/{plan_id}/comida/{meal_id}/recalcular-ingredientes")
async def recalcular_ingredientes(
    plan_id: int,
    meal_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Recalculate nutritional values given adjusted ingredient quantities."""
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await request.json()
    nombre = (body.get("nombre") or "").strip()
    ingredientes = body.get("ingredientes") or []
    if not ingredientes:
        return JSONResponse({"error": "Sin ingredientes"}, status_code=400)
    set_token_user_id(current_user.id)
    try:
        result = claude_recalculate(nombre, ingredientes)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)[:100]}, status_code=500)


@router.post("/plan/{plan_id}/comida/{meal_id}/confirmar-foto")
async def confirmar_foto_consumida(
    plan_id: int,
    meal_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nombre: str = Form(...),
    calorias: str = Form(default=""),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return RedirectResponse("/plan", status_code=303)

    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    day_num = meal.day_of_week if meal else 0
    if meal:
        already_consumed = meal.consumed
        meal.consumed = True
        meal.actual_name = nombre.strip() or meal.name
        meal.actual_calories = int(calorias) if calorias.strip().isdigit() else None
        if not already_consumed:
            _deduct_from_stock(db, meal, current_user.id)
        db.commit()
    return RedirectResponse(f"/plan/{plan_id}?day={day_num}", status_code=303)


@router.post("/plan/{plan_id}/comida/{meal_id}/receta")
def generar_receta(plan_id: int, meal_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return JSONResponse({"error": "Plan no encontrado"}, status_code=404)

    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    if not meal:
        return JSONResponse({"error": "Comida no encontrada"}, status_code=404)
    if meal.recipe_text:
        try:
            return JSONResponse(json.loads(meal.recipe_text))
        except Exception:
            pass
    set_token_user_id(current_user.id)
    try:
        ingredients = json.loads(meal.ingredients_json or "[]")
        result = claude_generate_recipe(
            meal.name, ingredients,
            MEAL_TYPE_LABELS.get(meal.meal_type, meal.meal_type),
            meal.description or "",
        )
        meal.recipe_text = json.dumps(result)
        db.commit()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)[:100]}, status_code=500)


@router.get("/plan/{plan_id}/comida/{meal_id}/recetario-opciones")
async def recetario_opciones(plan_id: int, meal_id: int, request: Request, db: Session = Depends(get_db)):
    """Return saved meals for the current meal type — used to populate Stock chips (no Claude)."""
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return JSONResponse({"error": "Plan no encontrado"}, status_code=404)

    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    if not meal:
        return JSONResponse({"error": "Comida no encontrada"}, status_code=404)

    from app.models.saved_meal import SavedMeal
    from sqlalchemy import case as sa_case

    exclude_names = [m.name for m in meal_plan.meals if m.day_of_week == meal.day_of_week]

    saved = (
        db.query(SavedMeal)
        .filter(
            SavedMeal.user_id == current_user.id,
            SavedMeal.meal_type == meal.meal_type,
            SavedMeal.is_excluded == False,  # noqa: E712
        )
        .order_by(
            sa_case((SavedMeal.name.notin_(exclude_names), 0), else_=1),
            SavedMeal.rating.desc().nullslast(),
            SavedMeal.times_served.desc(),
        )
        .limit(20)
        .all()
    )

    opciones = [
        {
            "nombre": sm.name,
            "descripcion": sm.description or "",
            "calorias": sm.calories,
            "proteinas_g": sm.protein_g,
            "carbohidratos_g": sm.carbs_g,
            "grasas_g": sm.fat_g,
            "ingredientes": json.loads(sm.ingredients_json or "[]"),
            "from_recetario": True,
        }
        for sm in saved
    ]

    return JSONResponse({"opciones": opciones})


@router.post("/plan/{plan_id}/comida/{meal_id}/sugerir-nombres")
async def sugerir_nombres(
    plan_id: int,
    meal_id: int,
    request: Request,
    db: Session = Depends(get_db),
    keyword: str = Form(...),
):
    """Return 5 dish name suggestions for a keyword — Haiku only, no AI limit consumed."""
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)

    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    if not meal:
        return JSONResponse({"error": "Comida no encontrada"}, status_code=404)

    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    country = getattr(profile, "country", None) or "España/Latinoamérica"

    set_token_user_id(current_user.id)
    try:
        nombres = claude_suggest_names(keyword.strip(), meal.meal_type, country)
        return JSONResponse({"nombres": nombres})
    except Exception as e:
        return JSONResponse({"error": str(e)[:100]}, status_code=500)


@router.post("/plan/{plan_id}/comida/{meal_id}/buscar-plato")
async def buscar_plato(
    plan_id: int,
    meal_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nombre: str = Form(...),
    usar_stock: str = Form(default="no"),
):
    """Search for a dish by name and return meal details as JSON for the UI modal."""
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return JSONResponse({"error": "Plan no encontrado"}, status_code=404)

    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    if not meal:
        return JSONResponse({"error": "Comida no encontrada"}, status_code=404)

    profile = meal_plan.profile
    base_pct = {"desayuno": 0.25, "media_manana": 0.10, "almuerzo": 0.35, "media_tarde": 0.10, "cena": 0.20}
    bmr = calculate_bmr(profile)
    activity_days = get_activity_days_list(profile)
    tdee = calculate_tdee(bmr, len(activity_days))
    target_total = calculate_target_calories(profile, tdee)

    # Adjust calorie target based on which meals are actually enabled
    try:
        enabled = json.loads(profile.enabled_meals) if getattr(profile, "enabled_meals", None) else list(base_pct)
    except (ValueError, TypeError):
        enabled = list(base_pct)
    total_pct = sum(base_pct[m] for m in enabled if m in base_pct) or 1.0
    raw_pct = base_pct.get(meal.meal_type, 0.20)
    target_calories = int(target_total * (raw_pct / total_pct))

    # User's saved meals for that type — pass as avoided list to reduce repetition
    saved_for_type = db.query(SavedMeal.name).filter(
        SavedMeal.user_id == current_user.id,
        SavedMeal.meal_type == meal.meal_type,
        SavedMeal.is_excluded == False,  # noqa: E712
    ).all()
    avoided = [r[0] for r in saved_for_type]

    # Determine pre/post-workout context for this specific meal
    day_sessions = db.query(ActivityDayConfig).filter(
        ActivityDayConfig.profile_id == profile.id,
        ActivityDayConfig.day_of_week == meal.day_of_week,
    ).all()
    workout_context = None
    if day_sessions:
        meal_times = get_effective_meal_times(profile)
        meal_time_str = meal_times.get(meal.meal_type)
        earliest_start = min((s.start_time for s in day_sessions if s.start_time), default=None)
        latest_end = max((s.end_time for s in day_sessions if s.end_time), default=None)
        exercise_types = [s.exercise_type.name for s in day_sessions if s.exercise_type]
        is_pre = bool(meal_time_str and earliest_start and meal_time_str < earliest_start)
        is_post = bool(meal_time_str and latest_end and meal_time_str > latest_end)
        workout_context = {
            "exercise_types": exercise_types,
            "earliest_start": earliest_start,
            "latest_end": latest_end,
            "is_pre_workout": is_pre,
            "is_post_workout": is_post,
        }

    # Stock mode: pick from recetario directly — no Claude, no limit consumed
    if usar_stock == "si":
        exclude_names = [m.name for m in meal_plan.meals if m.day_of_week == meal.day_of_week]
        recetario_meal = meal_from_recetario(db, current_user.id, meal.meal_type, exclude_names)
        if recetario_meal:
            return JSONResponse(recetario_meal)
        return JSONResponse(
            {"error": "No hay recetas guardadas en tu recetario para este tipo de comida."},
            status_code=404,
        )

    # AI modes (sugerir / nombre / capricho): check weekly limit first
    if get_remaining(db, current_user.id, "meal_change") == 0:
        exclude_names = [m.name for m in meal_plan.meals if m.day_of_week == meal.day_of_week]
        fallback = meal_from_recetario(db, current_user.id, meal.meal_type, exclude_names)
        if fallback:
            return JSONResponse(fallback)
        return JSONResponse(
            {"error": "Límite de cambios con IA alcanzado esta semana y no hay recetas guardadas para este tipo de comida."},
            status_code=429,
        )

    set_token_user_id(current_user.id)
    try:
        if usar_stock == "sugerir":
            other_meals = db.query(Meal).filter(
                Meal.meal_plan_id == plan_id,
                Meal.day_of_week == meal.day_of_week,
                Meal.id != meal_id,
            ).all()
            result = claude_single_meal(
                profile=profile,
                meal_type=meal.meal_type,
                day_name=DAYS_OF_WEEK[meal.day_of_week] if meal.day_of_week < len(DAYS_OF_WEEK) else "Lunes",
                target_calories=target_calories,
                current_meal_name=meal.name,
                other_meals=[m.name for m in other_meals],
                avoided_meals=avoided,
                workout_context=workout_context,
            )
        elif usar_stock == "capricho":
            result = claude_cheat_meal(
                nombre=nombre.strip(),
                meal_type=meal.meal_type,
                profile=profile,
            )
        else:
            result = claude_buscar_plato(
                nombre=nombre.strip(),
                meal_type=meal.meal_type,
                target_calories=target_calories,
                stock_items=None,
                profile=profile,
                workout_context=workout_context,
            )
        log_action(db, current_user.id, "meal_change")
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/plan/{plan_id}/comida/{meal_id}/reemplazar")
async def reemplazar_plato(
    plan_id: int,
    meal_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nombre: str = Form(...),
    descripcion: str = Form(default=""),
    calorias: str = Form(default="0"),
    proteinas: str = Form(default="0"),
    carbohidratos: str = Form(default="0"),
    grasas: str = Form(default="0"),
    ingredientes_json: str = Form(default="[]"),
    receta_detallada: str = Form(default=""),
    is_capricho: str = Form(default="0"),
):
    """Replace a meal with a user-selected dish (from the search modal)."""
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return RedirectResponse("/plan", status_code=303)

    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    day_num = meal.day_of_week if meal else 0
    if meal:
        meal.name = nombre.strip()
        meal.description = descripcion.strip()
        try:
            meal.calories = int(float(calorias))
            meal.protein_g = float(proteinas)
            meal.carbs_g = float(carbohidratos)
            meal.fat_g = float(grasas)
        except (ValueError, TypeError):
            pass
        meal.ingredients_json = ingredientes_json or "[]"
        if receta_detallada.strip():
            import json as _j
            meal.recipe_text = _j.dumps({"pasos": receta_detallada.strip().split("\n"), "fuente": "busqueda_personalizada"})
        meal.consumed = False
        meal.actual_calories = None
        meal.actual_name = None
        meal.regen_count = 0
        if is_capricho != "1":
            upsert_saved_meal(db, current_user.id, meal)
        db.commit()

    return RedirectResponse(f"/plan/{plan_id}?success=Comida+reemplazada&day={day_num}", status_code=303)


@router.post("/plan/{plan_id}/copiar")
def copiar_plan(plan_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return RedirectResponse("/plan", status_code=303)

    new_week_start = meal_plan.week_start + timedelta(days=7)
    new_plan = MealPlan(profile_id=meal_plan.profile_id, week_start=new_week_start, status="pending")
    db.add(new_plan)
    db.commit()
    db.refresh(new_plan)
    for m in meal_plan.meals:
        db.add(Meal(
            meal_plan_id=new_plan.id,
            day_of_week=m.day_of_week,
            meal_type=m.meal_type,
            meal_order=m.meal_order,
            name=m.name,
            description=m.description,
            calories=m.calories,
            protein_g=m.protein_g,
            carbs_g=m.carbs_g,
            fat_g=m.fat_g,
            ingredients_json=m.ingredients_json,
        ))
    db.commit()
    return RedirectResponse(f"/plan/{new_plan.id}", status_code=303)


@router.post("/plan/{plan_id}/regenerar")
def regenerar_plan(plan_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return RedirectResponse("/plan", status_code=303)

    if any(m.consumed for m in meal_plan.meals):
        return RedirectResponse(f"/plan/{plan_id}?error=No+se+puede+regenerar:+ya+hay+comidas+marcadas+como+consumidas.", status_code=303)

    if get_remaining(db, current_user.id, "plan_regenerate") == 0:
        msg = _urlquote("Límite de regeneraciones semanales alcanzado (2/2). Se reinicia cada lunes.")
        return RedirectResponse(f"/plan/{plan_id}?error={msg}", status_code=303)

    profile = meal_plan.profile
    # Capture current meal names before deletion (to force variety on regen)
    recently_used = list({m.name for m in meal_plan.meals})

    # Back up current plan before overwriting
    meal_plan.previous_raw_json = meal_plan.raw_json
    for meal in list(meal_plan.meals):
        db.delete(meal)
    db.commit()

    try:
        bmr = calculate_bmr(profile)
        activity_days = get_activity_days_list(profile)
        tdee = calculate_tdee(bmr, len(activity_days))
        target = calculate_target_calories(profile, tdee)

        user_meals = db.query(SavedMeal).filter(
            SavedMeal.user_id == current_user.id,
            SavedMeal.is_excluded == False,  # noqa: E712
        ).all()

        set_token_user_id(current_user.id)
        result = claude_generate(profile, bmr, tdee, target, saved_meals=user_meals or None, recently_used=recently_used, week_start=meal_plan.week_start)
        meal_plan.raw_json = json.dumps(result)
        meal_plan.status = "pending"
        _save_meals_from_response(db, meal_plan.id, result, user_id=current_user.id)
        log_action(db, current_user.id, "plan_regenerate")
        db.commit()
        return RedirectResponse(f"/plan/{plan_id}?success=Plan+regenerado.+Puedes+deshacer+si+prefieres+el+anterior.", status_code=303)

    except Exception as e:
        # Auto-restore previous meals so the plan is never left empty
        if meal_plan.previous_raw_json:
            try:
                prev = json.loads(meal_plan.previous_raw_json)
                _save_meals_from_response(db, meal_plan.id, prev)
                db.commit()
            except Exception:
                pass
        msg = _urlquote(f"Error al regenerar: {str(e)[:120]}")
        return RedirectResponse(f"/plan/{plan_id}?error={msg}", status_code=303)


@router.post("/plan/{plan_id}/deshacer-regenerar")
def deshacer_regenerar(plan_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan or not meal_plan.previous_raw_json:
        return RedirectResponse(f"/plan/{plan_id}?error=No+hay+plan+anterior+guardado.", status_code=303)

    # Restore previous plan
    for meal in list(meal_plan.meals):
        db.delete(meal)
    db.commit()

    try:
        previous = json.loads(meal_plan.previous_raw_json)
        meal_plan.raw_json = meal_plan.previous_raw_json
        meal_plan.previous_raw_json = None
        meal_plan.status = "pending"
        _save_meals_from_response(db, meal_plan.id, previous, user_id=current_user.id)
        db.commit()
        return RedirectResponse(f"/plan/{plan_id}?success=Plan+anterior+restaurado.", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/plan/{plan_id}?error={_urlquote(str(e)[:100])}", status_code=303)


@router.post("/plan/{plan_id}/comida/{meal_id}/eliminar")
def eliminar_comida(plan_id: int, meal_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return RedirectResponse("/plan", status_code=303)

    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    day_num = meal.day_of_week if meal else 0
    if meal:
        db.delete(meal)
        db.commit()
    return RedirectResponse(f"/plan/{plan_id}?day={day_num}", status_code=303)
