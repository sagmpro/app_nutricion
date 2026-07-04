from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.food_stock import FoodStock, STOCK_CATEGORIES
from app.services.auth_service import get_current_user
from app.services.claude_service import identify_stock_photo as claude_identify_photo
from app.services import household_service as hs

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/stock")
def stock_list(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    items = (
        db.query(FoodStock)
        .filter(hs.stock_filter(current_user.id, db))
        .order_by(FoodStock.category, FoodStock.name)
        .all()
    )

    categories: dict[str, list] = {}
    for item in items:
        categories.setdefault(item.category, []).append(item)

    return templates.TemplateResponse(request, "stock/list.html", {
        "categories": categories,
        "all_items": items,
        "stock_categories": STOCK_CATEGORIES,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
        "current_user": current_user,
        "household": hs.get_member(current_user.id, db),
    })


@router.post("/stock/nuevo")
def stock_nuevo(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    quantity: float = Form(...),
    unit: str = Form(...),
    category: str = Form(...),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    existing = (
        db.query(FoodStock)
        .filter(FoodStock.name.ilike(name), hs.stock_filter(current_user.id, db))
        .first()
    )
    kwargs = hs.new_stock_kwargs(current_user.id, db)
    if existing:
        if existing.unit == unit:
            existing.quantity += quantity
        else:
            existing.quantity = quantity
            existing.unit = unit
        existing.updated_at = datetime.now()
    else:
        db.add(FoodStock(name=name, quantity=quantity, unit=unit, category=category, **kwargs))
    db.commit()
    return RedirectResponse("/stock?success=Item+agregado", status_code=303)


@router.post("/stock/{item_id}/editar")
def stock_editar(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    quantity: float = Form(...),
    unit: str = Form(...),
    category: str = Form(...),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    item = db.query(FoodStock).filter(
        FoodStock.id == item_id, hs.stock_filter(current_user.id, db)
    ).first()
    if item:
        item.name = name
        item.quantity = quantity
        item.unit = unit
        item.category = category
        item.updated_at = datetime.now()
        db.commit()
    return RedirectResponse("/stock?success=Item+actualizado", status_code=303)


@router.post("/stock/{item_id}/eliminar")
def stock_eliminar(item_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    item = db.query(FoodStock).filter(
        FoodStock.id == item_id, hs.stock_filter(current_user.id, db)
    ).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse("/stock", status_code=303)


@router.post("/stock/editar-todos")
async def stock_editar_todos(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    count = int(form.get("count", 0))
    updated = 0
    for i in range(count):
        id_str = form.get(f"id_{i}")
        if not id_str:
            continue
        name = (form.get(f"name_{i}") or "").strip()
        if not name:
            continue
        try:
            item_id = int(id_str)
            quantity = float(form.get(f"quantity_{i}") or 0)
        except ValueError:
            continue
        unit = (form.get(f"unit_{i}") or "").strip()
        category = (form.get(f"category_{i}") or "Otros").strip()
        item = db.query(FoodStock).filter(
            FoodStock.id == item_id, hs.stock_filter(current_user.id, db)
        ).first()
        if item:
            item.name = name
            item.quantity = quantity
            item.unit = unit
            item.category = category
            item.updated_at = datetime.now()
            updated += 1
    db.commit()
    return RedirectResponse(f"/stock?success={updated}+ingrediente(s)+actualizados", status_code=303)


@router.post("/stock/eliminar-varios")
async def stock_eliminar_varios(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    ids = form.getlist("delete_ids")
    count = 0
    for id_str in ids:
        try:
            item = db.query(FoodStock).filter(
                FoodStock.id == int(id_str),
                hs.stock_filter(current_user.id, db),
            ).first()
            if item:
                db.delete(item)
                count += 1
        except (ValueError, TypeError):
            pass
    db.commit()
    return RedirectResponse(f"/stock?success={count}+ingrediente(s)+eliminados", status_code=303)


@router.post("/stock/desde-foto")
async def stock_desde_foto(request: Request, db: Session = Depends(get_db), foto: UploadFile = File(...)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    try:
        image_bytes = await foto.read()
        media_type = foto.content_type or "image/jpeg"
        result = claude_identify_photo(image_bytes, media_type)
        items = result.get("items", [])
        if not items:
            return RedirectResponse("/stock?error=Claude+no+pudo+identificar+ingredientes+en+la+foto", status_code=303)
        return templates.TemplateResponse(request, "stock/review_foto.html", {
            "items": items,
            "stock_categories": STOCK_CATEGORIES,
            "current_user": current_user,
        })
    except Exception as e:
        return RedirectResponse(f"/stock?error=Error+analizando+foto:+{str(e)[:60]}", status_code=303)


@router.post("/stock/confirmar-foto")
async def stock_confirmar_foto(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    count = int(form.get("count", 0))
    includes = set(form.getlist("include"))
    kwargs = hs.new_stock_kwargs(current_user.id, db)

    added = 0
    for i in range(count):
        if str(i) not in includes:
            continue
        name = (form.get(f"name_{i}") or "").strip()
        if not name:
            continue
        try:
            quantity = float(form.get(f"quantity_{i}") or 1)
        except ValueError:
            quantity = 1.0
        unit = (form.get(f"unit_{i}") or "unidades").strip()
        category = form.get(f"category_{i}") or "Otros"

        existing = (
            db.query(FoodStock)
            .filter(FoodStock.name.ilike(name), hs.stock_filter(current_user.id, db))
            .first()
        )
        if existing:
            if existing.unit == unit:
                existing.quantity += quantity
            else:
                existing.quantity = quantity
                existing.unit = unit
            existing.updated_at = datetime.now()
        else:
            db.add(FoodStock(name=name, quantity=quantity, unit=unit, category=category, **kwargs))
        added += 1

    db.commit()
    return RedirectResponse(f"/stock?success={added}+ingrediente(s)+anadidos+al+stock", status_code=303)
