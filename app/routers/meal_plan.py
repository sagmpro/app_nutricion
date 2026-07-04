import json
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.profile import UserProfile
from app.models.meal_plan import MealPlan
from app.models.meal import Meal, MEAL_TYPE_ORDER, MEAL_TYPE_LABELS, MEAL_TYPES
from app.models.food_stock import FoodStock
from app.services.nutrition import (
    calculate_bmr, calculate_tdee, calculate_target_calories,
    get_activity_days_list, DAYS_OF_WEEK, DAYS_SHORT,
)
from app.services.claude_service import (
    generate_meal_plan as claude_generate,
    generate_single_meal as claude_single_meal,
    analyze_food_photo as claude_analyze_photo,
    generate_recipe as claude_generate_recipe,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _build_days_data(meal_plan: MealPlan) -> list[dict]:
    days = []
    for day_num in range(7):
        day_meals = sorted(
            [m for m in meal_plan.meals if m.day_of_week == day_num],
            key=lambda m: m.meal_order,
        )
        consumed_cals = sum(
            (m.actual_calories or m.calories) for m in day_meals if m.consumed
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
async def generar_plan(request: Request, db: Session = Depends(get_db)):
    profile = db.query(UserProfile).first()
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


@router.post("/plan/{plan_id}/comida/{meal_id}/regenerar")
def regenerar_comida(plan_id: int, meal_id: int, db: Session = Depends(get_db)):
    import json as _json
    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    if not meal:
        return RedirectResponse(f"/plan/{plan_id}", status_code=303)

    meal_plan = meal.meal_plan
    profile = meal_plan.profile

    calorie_pct = {"desayuno": 0.25, "media_manana": 0.10, "almuerzo": 0.35, "media_tarde": 0.10, "cena": 0.20}
    bmr = calculate_bmr(profile)
    activity_days = get_activity_days_list(profile)
    tdee = calculate_tdee(bmr, len(activity_days))
    target_total = calculate_target_calories(profile, tdee)
    target_calories = int(target_total * calorie_pct.get(meal.meal_type, 0.20))

    other_meals = [m.name for m in meal_plan.meals if m.day_of_week == meal.day_of_week and m.id != meal_id]

    try:
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
        db.commit()
    except Exception as e:
        return RedirectResponse(f"/plan/{plan_id}?error=Error+regenerando+comida:+{str(e)[:80]}", status_code=303)

    return RedirectResponse(f"/plan/{plan_id}", status_code=303)


@router.post("/plan/{plan_id}/eliminar")
def eliminar_plan(plan_id: int, db: Session = Depends(get_db)):
    meal_plan = db.query(MealPlan).filter(MealPlan.id == plan_id).first()
    if meal_plan:
        db.delete(meal_plan)
        db.commit()
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/{plan_id}/aprobar")
def aprobar_plan(plan_id: int, db: Session = Depends(get_db)):
    meal_plan = db.query(MealPlan).filter(MealPlan.id == plan_id).first()
    if meal_plan:
        meal_plan.status = "approved"
        db.commit()
    return RedirectResponse(f"/plan/{plan_id}", status_code=303)


def _deduct_from_stock(db: Session, meal: Meal) -> None:
    """Best-effort deduction of meal ingredients from stock when consumed."""
    ingredients = json.loads(meal.ingredients_json or "[]")
    for ing in ingredients:
        name = ing.get("nombre", "").strip()
        quantity = float(ing.get("cantidad", 0))
        unit = ing.get("unidad", "")
        if not name or quantity <= 0:
            continue
        stock_item = db.query(FoodStock).filter(FoodStock.name.ilike(name)).first()
        if stock_item and stock_item.unit == unit:
            stock_item.quantity = max(0.0, stock_item.quantity - quantity)
            if stock_item.quantity == 0:
                db.delete(stock_item)


@router.post("/plan/{plan_id}/comida/{meal_id}/consumir")
def consumir_comida(plan_id: int, meal_id: int, db: Session = Depends(get_db)):
    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    if meal:
        meal.consumed = not meal.consumed
        if not meal.consumed:
            meal.actual_calories = None
            meal.actual_name = None
        else:
            _deduct_from_stock(db, meal)
        db.commit()
    return RedirectResponse(f"/plan/{plan_id}", status_code=303)


@router.post("/plan/{plan_id}/comida/{meal_id}/foto-preview")
async def foto_consumida_preview(plan_id: int, meal_id: int, foto: UploadFile = File(...)):
    """Analyze a food photo and return JSON — used by the AJAX confirmation modal."""
    try:
        image_bytes = await foto.read()
        media_type = foto.content_type or "image/jpeg"
        result = claude_analyze_photo(image_bytes, media_type)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)[:100]}, status_code=500)


@router.post("/plan/{plan_id}/comida/{meal_id}/confirmar-foto")
async def confirmar_foto_consumida(
    plan_id: int,
    meal_id: int,
    db: Session = Depends(get_db),
    nombre: str = Form(...),
    calorias: str = Form(default=""),
):
    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    if meal:
        meal.consumed = True
        meal.actual_name = nombre.strip() or meal.name
        meal.actual_calories = int(calorias) if calorias.strip().isdigit() else None
        db.commit()
    return RedirectResponse(f"/plan/{plan_id}", status_code=303)


@router.post("/plan/{plan_id}/comida/{meal_id}/receta")
def generar_receta(plan_id: int, meal_id: int, db: Session = Depends(get_db)):
    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.meal_plan_id == plan_id).first()
    if not meal:
        return JSONResponse({"error": "Comida no encontrada"}, status_code=404)
    if meal.recipe_text:
        try:
            return JSONResponse(json.loads(meal.recipe_text))
        except Exception:
            pass
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


@router.post("/plan/{plan_id}/copiar")
def copiar_plan(plan_id: int, db: Session = Depends(get_db)):
    meal_plan = db.query(MealPlan).filter(MealPlan.id == plan_id).first()
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
