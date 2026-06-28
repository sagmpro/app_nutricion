from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.food_stock import FoodStock, STOCK_CATEGORIES

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/stock")
def stock_list(request: Request, db: Session = Depends(get_db)):
    items = db.query(FoodStock).order_by(FoodStock.category, FoodStock.name).all()

    categories: dict[str, list] = {}
    for item in items:
        categories.setdefault(item.category, []).append(item)

    return templates.TemplateResponse(request, "stock/list.html", {
        "categories": categories,
        "all_items": items,
        "stock_categories": STOCK_CATEGORIES,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/stock/nuevo")
def stock_nuevo(
    db: Session = Depends(get_db),
    name: str = Form(...),
    quantity: float = Form(...),
    unit: str = Form(...),
    category: str = Form(...),
):
    existing = db.query(FoodStock).filter(FoodStock.name.ilike(name)).first()
    if existing:
        if existing.unit == unit:
            existing.quantity += quantity
        else:
            existing.quantity = quantity
            existing.unit = unit
        existing.updated_at = datetime.now()
    else:
        db.add(FoodStock(name=name, quantity=quantity, unit=unit, category=category))
    db.commit()
    return RedirectResponse("/stock?success=Item+agregado", status_code=303)


@router.post("/stock/{item_id}/editar")
def stock_editar(
    item_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    quantity: float = Form(...),
    unit: str = Form(...),
    category: str = Form(...),
):
    item = db.query(FoodStock).filter(FoodStock.id == item_id).first()
    if item:
        item.name = name
        item.quantity = quantity
        item.unit = unit
        item.category = category
        item.updated_at = datetime.now()
        db.commit()
    return RedirectResponse("/stock?success=Item+actualizado", status_code=303)


@router.post("/stock/{item_id}/eliminar")
def stock_eliminar(item_id: int, db: Session = Depends(get_db)):
    item = db.query(FoodStock).filter(FoodStock.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse("/stock", status_code=303)
