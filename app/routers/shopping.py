import json
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.meal_plan import MealPlan
from app.models.profile import UserProfile
from app.models.shopping_list import ShoppingList
from app.models.shopping_item import ShoppingItem
from app.models.food_stock import FoodStock
from app.services.auth_service import get_current_user
from app.services.claude_service import generate_shopping_list as claude_shopping
from app.services import household_service as hs

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _get_user_plan(db: Session, plan_id: int, user_id: int):
    """Get a meal plan belonging to the current user OR a shared household plan."""
    from app.models.household import HouseholdMember
    plan = (
        db.query(MealPlan)
        .join(UserProfile)
        .filter(MealPlan.id == plan_id, UserProfile.user_id == user_id)
        .first()
    )
    if plan:
        return plan
    # Allow access to household's shared plan
    member = db.query(HouseholdMember).filter(HouseholdMember.user_id == user_id).first()
    if member:
        return db.query(MealPlan).filter(
            MealPlan.id == plan_id,
            MealPlan.household_id == member.household_id,
            MealPlan.is_shared == True,
        ).first()
    return None


def _get_user_shopping_list(db: Session, list_id: int, user_id: int):
    """Get a shopping list belonging to this user's plan, or the household's shared list."""
    from app.models.household import HouseholdMember
    sl = (
        db.query(ShoppingList)
        .join(MealPlan)
        .join(UserProfile)
        .filter(ShoppingList.id == list_id, UserProfile.user_id == user_id)
        .first()
    )
    if sl:
        return sl
    member = db.query(HouseholdMember).filter(HouseholdMember.user_id == user_id).first()
    if member:
        return db.query(ShoppingList).filter(
            ShoppingList.id == list_id,
            ShoppingList.household_id == member.household_id,
        ).first()
    return None


@router.get("/compras")
def compras_index(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    household_id = hs.get_household_id(current_user.id, db)

    # Prefer the household shopping list if in one
    if household_id:
        latest = (
            db.query(ShoppingList)
            .filter(ShoppingList.household_id == household_id)
            .order_by(ShoppingList.created_at.desc())
            .first()
        )
        if latest:
            return RedirectResponse(f"/compras/{latest.id}", status_code=303)

    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not profile:
        return RedirectResponse("/plan", status_code=303)

    latest = (
        db.query(ShoppingList)
        .join(MealPlan)
        .filter(MealPlan.profile_id == profile.id)
        .order_by(ShoppingList.created_at.desc())
        .first()
    )
    if latest:
        return RedirectResponse(f"/compras/{latest.id}", status_code=303)
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/{plan_id}/lista-compras")
def generar_lista(plan_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    meal_plan = _get_user_plan(db, plan_id, current_user.id)
    if not meal_plan:
        return RedirectResponse(f"/plan/{plan_id}", status_code=303)

    if meal_plan.shopping_list:
        db.delete(meal_plan.shopping_list)
        db.commit()

    household_id = hs.get_household_id(current_user.id, db)
    shopping_list = ShoppingList(meal_plan_id=plan_id, household_id=household_id)
    db.add(shopping_list)
    db.commit()
    db.refresh(shopping_list)

    try:
        all_ingredients = []
        for meal in meal_plan.meals:
            all_ingredients.extend(json.loads(meal.ingredients_json or "[]"))

        stock_items = [
            {"nombre": s.name, "cantidad": s.quantity, "unidad": s.unit}
            for s in db.query(FoodStock).filter(hs.stock_filter(current_user.id, db)).all()
        ]
        result = claude_shopping(all_ingredients, stock_items)

        for category_group in result.get("lista", []):
            category = category_group.get("categoria", "Otros")
            for item in category_group.get("items", []):
                db.add(ShoppingItem(
                    shopping_list_id=shopping_list.id,
                    name=item.get("nombre", ""),
                    quantity=float(item.get("cantidad", 0)),
                    unit=item.get("unidad", "unidades"),
                    category=category,
                    checked=False,
                ))

        db.commit()
        return RedirectResponse(f"/compras/{shopping_list.id}", status_code=303)

    except Exception as e:
        db.delete(shopping_list)
        db.commit()
        return RedirectResponse(f"/plan/{plan_id}?error=Error+generando+lista:+{str(e)[:80]}", status_code=303)


@router.get("/compras/{list_id}")
def ver_lista(request: Request, list_id: int, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    shopping_list = _get_user_shopping_list(db, list_id, current_user.id)
    if not shopping_list:
        return RedirectResponse("/compras", status_code=303)

    categories: dict[str, list] = {}
    for item in shopping_list.items:
        categories.setdefault(item.category, []).append(item)

    stock_map = {
        s.name.lower(): s
        for s in db.query(FoodStock).filter(hs.stock_filter(current_user.id, db)).all()
    }
    total = len(shopping_list.items)
    checked = sum(1 for i in shopping_list.items if i.checked)

    household_id = hs.get_household_id(current_user.id, db)

    # Collect all shopping lists visible to this user
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if household_id:
        all_lists = (
            db.query(ShoppingList)
            .filter(ShoppingList.household_id == household_id)
            .order_by(ShoppingList.created_at.desc())
            .all()
        )
    elif profile:
        all_lists = (
            db.query(ShoppingList)
            .join(MealPlan)
            .filter(MealPlan.profile_id == profile.id)
            .order_by(ShoppingList.created_at.desc())
            .all()
        )
    else:
        all_lists = []

    return templates.TemplateResponse(request, "shopping/list.html", {
        "shopping_list": shopping_list,
        "categories": categories,
        "stock_map": stock_map,
        "total": total,
        "checked": checked,
        "all_lists": all_lists,
        "success": request.query_params.get("success"),
        "current_user": current_user,
        "is_household": bool(household_id),
    })


@router.post("/compras/items/{item_id}/cantidad")
async def actualizar_cantidad(item_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    item = db.query(ShoppingItem).filter(ShoppingItem.id == item_id).first()
    if item:
        shopping_list = _get_user_shopping_list(db, item.shopping_list_id, current_user.id)
        if shopping_list:
            try:
                item.quantity = max(0.0, float(form.get("quantity", item.quantity)))
                db.commit()
            except (ValueError, TypeError):
                pass
    return RedirectResponse(f"/compras/{item.shopping_list_id}", status_code=303)


@router.post("/compras/items/{item_id}/toggle")
def toggle_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    item = db.query(ShoppingItem).filter(ShoppingItem.id == item_id).first()
    if item:
        shopping_list = _get_user_shopping_list(db, item.shopping_list_id, current_user.id)
        if shopping_list:
            item.checked = not item.checked
            db.commit()
            return RedirectResponse(f"/compras/{item.shopping_list_id}", status_code=303)
    return RedirectResponse("/compras", status_code=303)


@router.post("/compras/{list_id}/al-stock")
def mover_al_stock(list_id: int, request: Request, db: Session = Depends(get_db)):
    """Add checked shopping items to shared stock and remove them from the list."""
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    shopping_list = _get_user_shopping_list(db, list_id, current_user.id)
    if not shopping_list:
        return RedirectResponse("/compras", status_code=303)

    kwargs = hs.new_stock_kwargs(current_user.id, db)
    moved = 0
    for item in list(shopping_list.items):
        if not item.checked:
            continue
        existing = (
            db.query(FoodStock)
            .filter(FoodStock.name.ilike(item.name), hs.stock_filter(current_user.id, db))
            .first()
        )
        if existing and existing.unit == item.unit:
            existing.quantity += item.quantity
        elif existing:
            existing.quantity = item.quantity
            existing.unit = item.unit
        else:
            db.add(FoodStock(
                name=item.name,
                quantity=item.quantity,
                unit=item.unit,
                category=item.category,
                **kwargs,
            ))
        db.delete(item)
        moved += 1

    db.commit()
    return RedirectResponse(f"/compras/{list_id}?success={moved}+productos+anadidos+al+stock", status_code=303)


@router.post("/compras/{list_id}/sincronizar-stock")
def sincronizar_stock(list_id: int, request: Request, db: Session = Depends(get_db)):
    """Pre-check items already covered by household/personal stock."""
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    shopping_list = _get_user_shopping_list(db, list_id, current_user.id)
    if not shopping_list:
        return RedirectResponse("/compras", status_code=303)

    stock_map = {
        s.name.lower(): s
        for s in db.query(FoodStock).filter(hs.stock_filter(current_user.id, db)).all()
    }
    for item in shopping_list.items:
        stock = stock_map.get(item.name.lower())
        if stock and stock.unit == item.unit and stock.quantity >= item.quantity:
            item.checked = True

    db.commit()
    return RedirectResponse(f"/compras/{list_id}", status_code=303)
