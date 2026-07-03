import json
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.meal_plan import MealPlan
from app.models.shopping_list import ShoppingList
from app.models.shopping_item import ShoppingItem
from app.models.food_stock import FoodStock
from app.services.claude_service import generate_shopping_list as claude_shopping

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/compras")
def compras_index(db: Session = Depends(get_db)):
    latest = db.query(ShoppingList).order_by(ShoppingList.created_at.desc()).first()
    if latest:
        return RedirectResponse(f"/compras/{latest.id}", status_code=303)
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/{plan_id}/lista-compras")
def generar_lista(plan_id: int, db: Session = Depends(get_db)):
    meal_plan = db.query(MealPlan).filter(MealPlan.id == plan_id).first()
    if not meal_plan:
        return RedirectResponse(f"/plan/{plan_id}", status_code=303)

    if meal_plan.shopping_list:
        db.delete(meal_plan.shopping_list)
        db.commit()

    shopping_list = ShoppingList(meal_plan_id=plan_id)
    db.add(shopping_list)
    db.commit()
    db.refresh(shopping_list)

    try:
        all_ingredients = []
        for meal in meal_plan.meals:
            all_ingredients.extend(json.loads(meal.ingredients_json or "[]"))

        result = claude_shopping(all_ingredients)

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
    shopping_list = db.query(ShoppingList).filter(ShoppingList.id == list_id).first()
    if not shopping_list:
        return RedirectResponse("/compras", status_code=303)

    categories: dict[str, list] = {}
    for item in shopping_list.items:
        categories.setdefault(item.category, []).append(item)

    stock_map = {s.name.lower(): s for s in db.query(FoodStock).all()}
    total = len(shopping_list.items)
    checked = sum(1 for i in shopping_list.items if i.checked)
    all_lists = db.query(ShoppingList).order_by(ShoppingList.created_at.desc()).all()

    return templates.TemplateResponse(request, "shopping/list.html", {
        "shopping_list": shopping_list,
        "categories": categories,
        "stock_map": stock_map,
        "total": total,
        "checked": checked,
        "all_lists": all_lists,
        "success": request.query_params.get("success"),
    })


@router.post("/compras/items/{item_id}/toggle")
def toggle_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(ShoppingItem).filter(ShoppingItem.id == item_id).first()
    if item:
        item.checked = not item.checked
        db.commit()
        return RedirectResponse(f"/compras/{item.shopping_list_id}", status_code=303)
    return RedirectResponse("/compras", status_code=303)


@router.post("/compras/{list_id}/al-stock")
def mover_al_stock(list_id: int, db: Session = Depends(get_db)):
    """Add checked items to stock and remove them from the shopping list."""
    shopping_list = db.query(ShoppingList).filter(ShoppingList.id == list_id).first()
    if not shopping_list:
        return RedirectResponse("/compras", status_code=303)

    moved = 0
    for item in list(shopping_list.items):
        if not item.checked:
            continue
        existing = db.query(FoodStock).filter(FoodStock.name.ilike(item.name)).first()
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
            ))
        db.delete(item)
        moved += 1

    db.commit()
    return RedirectResponse(f"/compras/{list_id}?success={moved}+productos+añadidos+al+stock", status_code=303)


@router.post("/compras/{list_id}/sincronizar-stock")
def sincronizar_stock(list_id: int, db: Session = Depends(get_db)):
    """Pre-check items that are already covered by stock."""
    shopping_list = db.query(ShoppingList).filter(ShoppingList.id == list_id).first()
    if not shopping_list:
        return RedirectResponse("/compras", status_code=303)

    stock_map = {s.name.lower(): s for s in db.query(FoodStock).all()}
    for item in shopping_list.items:
        stock = stock_map.get(item.name.lower())
        if stock and stock.unit == item.unit and stock.quantity >= item.quantity:
            item.checked = True

    db.commit()
    return RedirectResponse(f"/compras/{list_id}", status_code=303)
