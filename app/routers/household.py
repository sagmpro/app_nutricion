import json
import unicodedata
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.household import Household, HouseholdMember
from app.models.user import User
from app.models.food_stock import FoodStock
from app.models.meal import MEAL_TYPE_LABELS
from app.models.meal_plan import MealPlan
from app.models.profile import UserProfile
from app.models.shopping_list import ShoppingList
from app.services.auth_service import get_current_user
from app.services import household_service as hs


def _norm(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name.lower().strip())
    return " ".join("".join(c for c in nfkd if not unicodedata.combining(c)).split())

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/hogar")
def hogar_index(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    tab = request.query_params.get("tab", "cocina")
    member = hs.get_member(current_user.id, db)
    household = None
    members = []
    stock_count = 0
    shopping_list = None
    shared_plan = None
    shared_meal_types: list[str] = ["almuerzo"]
    member_pax_info: list[dict] = []
    total_pax: float = 1.0
    cocina_days: list[dict] = []

    if member:
        household = db.query(Household).filter(Household.id == member.household_id).first()
        members = (
            db.query(HouseholdMember)
            .filter(HouseholdMember.household_id == member.household_id)
            .all()
        )
        stock_count = db.query(FoodStock).filter(
            FoodStock.household_id == member.household_id
        ).count()

        # Latest shared plan
        shared_plan = (
            db.query(MealPlan)
            .filter(MealPlan.household_id == member.household_id, MealPlan.is_shared == True)
            .order_by(MealPlan.created_at.desc())
            .first()
        )

        shopping_list = (
            db.query(ShoppingList)
            .filter(ShoppingList.household_id == member.household_id)
            .order_by(ShoppingList.created_at.desc())
            .first()
        )

        shared_meal_types = hs.get_shared_meal_types(member.household_id, db)
        member_pax_info = hs.get_member_pax_info(member.household_id, db)
        total_pax = hs.get_household_total_pax(member.household_id, db)

        # Build Cocina tab data: shared meals from the active shared plan
        if shared_plan:
            days_map: dict[int, list] = {}
            DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            for meal in shared_plan.meals:
                if meal.meal_type not in shared_meal_types:
                    continue
                d = meal.day_of_week
                if d not in days_map:
                    days_map[d] = []
                # Scale ingredients × total_pax for display
                raw_ings = json.loads(meal.ingredients_json or "[]")
                scaled_ings = []
                for ing in raw_ings:
                    if isinstance(ing, dict) and "cantidad" in ing:
                        qty = round(float(ing["cantidad"]) * total_pax, 2)
                        scaled_ings.append({**ing, "cantidad": qty})
                    else:
                        scaled_ings.append(ing)
                days_map[d].append({
                    "id": meal.id,
                    "plan_id": shared_plan.id,
                    "name": meal.name,
                    "description": meal.description or "",
                    "meal_type": meal.meal_type,
                    "meal_type_label": MEAL_TYPE_LABELS.get(meal.meal_type, meal.meal_type),
                    "calories": meal.calories,
                    "protein_g": meal.protein_g,
                    "carbs_g": meal.carbs_g,
                    "fat_g": meal.fat_g,
                    "consumed": meal.consumed,
                    "has_recipe": bool(meal.recipe_text),
                    "ingredients": scaled_ings,
                })
            for day_num in sorted(days_map):
                cocina_days.append({
                    "day_num": day_num,
                    "day_name": DAY_NAMES[day_num] if 0 <= day_num <= 6 else f"Día {day_num}",
                    "meals": days_map[day_num],
                })

    # True if the current user is the one who shared the active plan
    is_plan_owner = bool(
        shared_plan and shared_plan.profile and shared_plan.profile.user_id == current_user.id
    ) if shared_plan else False

    return templates.TemplateResponse(request, "household/index.html", {
        "current_user": current_user,
        "member": member,
        "household": household,
        "members": members,
        "stock_count": stock_count,
        "shopping_list": shopping_list,
        "shared_plan": shared_plan,
        "is_plan_owner": is_plan_owner,
        "tab": tab,
        "shared_meal_types": shared_meal_types,
        "all_meal_types": ["desayuno", "media_manana", "almuerzo", "media_tarde", "cena"],
        "meal_type_labels": MEAL_TYPE_LABELS,
        "member_pax_info": member_pax_info,
        "total_pax": total_pax,
        "cocina_days": cocina_days,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.get("/hogar/plan-popup")
def plan_popup_data(request: Request, db: Session = Depends(get_db)):
    """Lightweight JSON endpoint: returns shared plan info if the current user is a non-owner invitee."""
    current_user = get_current_user(request, db)
    if not current_user:
        return {"show": False}

    member = hs.get_member(current_user.id, db)
    if not member:
        return {"show": False}

    shared_plan = (
        db.query(MealPlan)
        .filter(MealPlan.household_id == member.household_id, MealPlan.is_shared == True)
        .order_by(MealPlan.created_at.desc())
        .first()
    )
    if not shared_plan:
        return {"show": False}

    # Only show popup if the current user is NOT the plan owner
    is_owner = shared_plan.profile and shared_plan.profile.user_id == current_user.id
    if is_owner:
        return {"show": False}

    household = db.query(Household).filter(Household.id == member.household_id).first()
    return {
        "show": True,
        "plan_id": shared_plan.id,
        "household_name": household.name if household else "Hogar",
        "week_start": shared_plan.week_start.strftime("%d/%m/%Y"),
    }


@router.post("/hogar/crear")
def crear_hogar(
    request: Request,
    db: Session = Depends(get_db),
    nombre: str = Form(...),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    existing = hs.get_member(current_user.id, db)
    if existing:
        return RedirectResponse("/hogar?error=Ya+perteneces+a+un+hogar", status_code=303)

    household = Household(name=nombre.strip() or "Mi Hogar", created_by=current_user.id)
    db.add(household)
    db.commit()
    db.refresh(household)

    member = HouseholdMember(household_id=household.id, user_id=current_user.id, role="owner")
    db.add(member)
    db.commit()

    moved = hs.migrate_stock_to_household(current_user.id, household.id, db)
    return RedirectResponse(
        f"/hogar?success=Hogar+creado.+{moved}+items+de+stock+transferidos", status_code=303
    )


@router.post("/hogar/invitar")
def invitar_miembro(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    member = hs.get_member(current_user.id, db)
    if not member:
        return RedirectResponse("/hogar?error=No+perteneces+a+un+hogar", status_code=303)

    target = db.query(User).filter(User.email == email.strip().lower()).first()
    if not target:
        return RedirectResponse("/hogar?error=Usuario+no+encontrado.+Debe+estar+registrado+primero", status_code=303)

    already = hs.get_member(target.id, db)
    if already:
        return RedirectResponse("/hogar?error=Ese+usuario+ya+pertenece+a+un+hogar", status_code=303)

    new_member = HouseholdMember(
        household_id=member.household_id,
        user_id=target.id,
        role="member",
    )
    db.add(new_member)
    db.commit()

    moved = hs.migrate_stock_to_household(target.id, member.household_id, db)
    return RedirectResponse(
        f"/hogar?success={target.email}+agregado+al+hogar.+{moved}+items+de+stock+transferidos",
        status_code=303,
    )


@router.post("/hogar/expulsar/{user_id}")
def expulsar_miembro(user_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    my_member = hs.get_member(current_user.id, db)
    if not my_member or my_member.role != "owner":
        return RedirectResponse("/hogar?error=Solo+el+dueno+puede+expulsar+miembros", status_code=303)

    if user_id == current_user.id:
        return RedirectResponse("/hogar?error=No+puedes+expulsarte+a+ti+mismo", status_code=303)

    target_member = db.query(HouseholdMember).filter(
        HouseholdMember.user_id == user_id,
        HouseholdMember.household_id == my_member.household_id,
    ).first()
    if target_member:
        hs.migrate_stock_to_personal(user_id, db)
        db.delete(target_member)
        db.commit()

    return RedirectResponse("/hogar?success=Miembro+eliminado+del+hogar", status_code=303)


@router.post("/hogar/salir")
def salir_hogar(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    member = hs.get_member(current_user.id, db)
    if not member:
        return RedirectResponse("/hogar", status_code=303)

    household_id = member.household_id
    is_owner = member.role == "owner"

    hs.migrate_stock_to_personal(current_user.id, db)
    db.delete(member)
    db.commit()

    # If owner left and no one else, delete the household
    if is_owner:
        remaining = db.query(HouseholdMember).filter(
            HouseholdMember.household_id == household_id
        ).count()
        if remaining == 0:
            db.query(Household).filter(Household.id == household_id).delete()
            db.commit()
        else:
            # Transfer ownership to the next member
            next_member = db.query(HouseholdMember).filter(
                HouseholdMember.household_id == household_id
            ).first()
            if next_member:
                next_member.role = "owner"
                db.commit()

    return RedirectResponse("/hogar?success=Saliste+del+hogar", status_code=303)


@router.get("/hogar/unirse/{token}")
def ver_invitacion_hogar(token: str, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(f"/login?next=/hogar/unirse/{token}", status_code=303)

    household = db.query(Household).filter(Household.invite_token == token).first()
    if not household:
        return RedirectResponse("/hogar?error=Enlace+de+invitacion+invalido", status_code=303)

    already = hs.get_member(current_user.id, db)
    if already:
        if already.household_id == household.id:
            return RedirectResponse("/hogar?success=Ya+eres+miembro+de+este+hogar", status_code=303)
        return RedirectResponse("/hogar?error=Ya+perteneces+a+otro+hogar.+Salí+primero.", status_code=303)

    return templates.TemplateResponse(request, "household/join.html", {
        "current_user": current_user,
        "household": household,
        "token": token,
        "member_count": len(household.members),
    })


@router.post("/hogar/unirse/{token}")
def unirse_hogar(token: str, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    household = db.query(Household).filter(Household.invite_token == token).first()
    if not household:
        return RedirectResponse("/hogar?error=Enlace+invalido", status_code=303)

    already = hs.get_member(current_user.id, db)
    if already:
        return RedirectResponse("/hogar?error=Ya+perteneces+a+un+hogar", status_code=303)

    new_member = HouseholdMember(household_id=household.id, user_id=current_user.id, role="member")
    db.add(new_member)
    db.commit()

    moved = hs.migrate_stock_to_household(current_user.id, household.id, db)
    return RedirectResponse(
        f"/hogar?success=Te+uniste+a+{household.name}.+{moved}+items+de+stock+transferidos",
        status_code=303,
    )


@router.post("/hogar/regenerar-link")
def regenerar_link(request: Request, db: Session = Depends(get_db)):
    """Generate a new invite token (invalidates old one)."""
    import uuid
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    member = hs.get_member(current_user.id, db)
    if not member or member.role != "owner":
        return RedirectResponse("/hogar?error=Solo+el+dueno+puede+regenerar+el+link", status_code=303)

    household = db.query(Household).filter(Household.id == member.household_id).first()
    if household:
        household.invite_token = uuid.uuid4().hex
        db.commit()

    return RedirectResponse("/hogar?success=Nuevo+link+de+invitacion+generado", status_code=303)


@router.post("/hogar/plan-compartido/{plan_id}/toggle")
def toggle_plan_compartido(plan_id: int, request: Request, db: Session = Depends(get_db)):
    """Mark/unmark a meal plan as the household's shared plan."""
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    member = hs.get_member(current_user.id, db)
    if not member:
        return RedirectResponse(f"/plan/{plan_id}?error=No+perteneces+a+un+hogar", status_code=303)

    plan = (
        db.query(MealPlan)
        .join(UserProfile)
        .filter(MealPlan.id == plan_id, UserProfile.user_id == current_user.id)
        .first()
    )
    if not plan:
        return RedirectResponse("/plan", status_code=303)

    if plan.is_shared:
        plan.is_shared = False
        plan.household_id = None
        db.commit()
        return RedirectResponse(f"/plan/{plan_id}?success=Plan+ya+no+es+compartido", status_code=303)
    else:
        # Unshare any previous shared plan for this household
        db.query(MealPlan).filter(
            MealPlan.household_id == member.household_id, MealPlan.is_shared == True
        ).update({"is_shared": False, "household_id": None})

        plan.is_shared = True
        plan.household_id = member.household_id
        db.commit()
        return RedirectResponse(f"/plan/{plan_id}?success=Plan+compartido+con+el+hogar", status_code=303)


@router.post("/hogar/plan-compartido/{plan_id}/copiar")
def copiar_plan_compartido(plan_id: int, request: Request, db: Session = Depends(get_db)):
    """Copy the household's shared plan to the current user's own profile."""
    from datetime import timedelta
    from app.models.meal import Meal

    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    member = hs.get_member(current_user.id, db)
    if not member:
        return RedirectResponse("/plan", status_code=303)

    shared_plan = db.query(MealPlan).filter(
        MealPlan.id == plan_id,
        MealPlan.household_id == member.household_id,
        MealPlan.is_shared == True,
    ).first()
    if not shared_plan:
        return RedirectResponse("/hogar?error=Plan+no+encontrado", status_code=303)

    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not profile:
        return RedirectResponse("/perfil?error=Completa+tu+perfil+primero", status_code=303)

    new_plan = MealPlan(
        profile_id=profile.id,
        week_start=shared_plan.week_start,
        status="approved",
        is_shared=False,
    )
    db.add(new_plan)
    db.commit()
    db.refresh(new_plan)

    for m in shared_plan.meals:
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

    return RedirectResponse(f"/plan/{new_plan.id}?success=Plan+copiado+a+tu+perfil", status_code=303)


@router.post("/hogar/configuracion")
async def guardar_configuracion(request: Request, db: Session = Depends(get_db)):
    """Save household shared_meal_types setting."""
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    member = hs.get_member(current_user.id, db)
    if not member:
        return RedirectResponse("/hogar?error=No+perteneces+a+un+hogar", status_code=303)

    household = db.query(Household).filter(Household.id == member.household_id).first()
    if not household:
        return RedirectResponse("/hogar", status_code=303)

    form_data = await request.form()
    all_types = ["desayuno", "media_manana", "almuerzo", "media_tarde", "cena"]
    selected = [t for t in all_types if form_data.get(f"shared_{t}") == "1"]
    household.shared_meal_types = json.dumps(selected if selected else [])
    db.commit()

    return RedirectResponse("/hogar?tab=config&success=Configuración+guardada", status_code=303)


@router.post("/hogar/miembro/display-name")
def actualizar_display_name(
    request: Request,
    db: Session = Depends(get_db),
    nombre: str = Form(default=""),
    target_user_id: int = Form(default=0),
):
    """Update a member's display name.
    Owners can update any member; others can only update themselves.
    """
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    my_member = hs.get_member(current_user.id, db)
    if not my_member:
        return RedirectResponse("/hogar?error=No+perteneces+a+un+hogar", status_code=303)

    # Determine which member to update
    uid = target_user_id if target_user_id else current_user.id
    if uid != current_user.id and my_member.role != "owner":
        return RedirectResponse("/hogar?tab=hogar&error=Solo+el+dueño+puede+renombrar+otros+miembros", status_code=303)

    target_member = db.query(HouseholdMember).filter(
        HouseholdMember.user_id == uid,
        HouseholdMember.household_id == my_member.household_id,
    ).first()
    if not target_member:
        return RedirectResponse("/hogar?tab=hogar&error=Miembro+no+encontrado", status_code=303)

    target_member.display_name = nombre.strip()[:80] or None
    db.commit()
    return RedirectResponse("/hogar?tab=hogar&success=Nombre+actualizado", status_code=303)


@router.post("/hogar/cocina/comida/{meal_id}/consumir")
def marcar_cocinado(meal_id: int, request: Request, db: Session = Depends(get_db)):
    """Mark a shared meal as cooked and deduct scaled ingredients from household stock."""
    from app.models.meal import Meal

    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    member = hs.get_member(current_user.id, db)
    if not member:
        return RedirectResponse("/hogar?error=No+perteneces+a+un+hogar", status_code=303)

    # Only allow access to meals in the household's shared plan
    meal = (
        db.query(Meal)
        .join(MealPlan)
        .filter(
            Meal.id == meal_id,
            MealPlan.household_id == member.household_id,
            MealPlan.is_shared == True,
        )
        .first()
    )
    if not meal:
        return RedirectResponse("/hogar?tab=cocina&error=Comida+no+encontrada", status_code=303)

    # Get total household pax for scaling
    total_pax = hs.get_household_total_pax(member.household_id, db)

    # Deduct scaled ingredients from shared stock (best effort)
    raw_ings = json.loads(meal.ingredients_json or "[]")
    stock_rows = db.query(FoodStock).filter(
        FoodStock.household_id == member.household_id
    ).all()
    stock_by_norm = {_norm(s.name): s for s in stock_rows}

    # Normalize units for lenient matching
    _UNIT_ALIASES: dict[str, str] = {
        "gramos": "g", "gr": "g", "gram": "g",
        "mililitros": "ml", "mililitro": "ml",
        "litros": "l", "litro": "l",
        "kilogramos": "kg", "kilo": "kg", "kilos": "kg",
        "unidades": "u", "unidad": "u", "und": "u", "piezas": "u", "pieza": "u",
        "cucharadas": "cda", "cucharada": "cda",
        "cucharaditas": "cdita", "cucharadita": "cdita",
    }

    def _norm_unit(u: str) -> str:
        u = u.lower().strip()
        return _UNIT_ALIASES.get(u, u)

    deducted = 0
    for ing in raw_ings:
        if not isinstance(ing, dict):
            continue
        nombre = ing.get("nombre", "")
        cantidad = float(ing.get("cantidad", 0)) * total_pax
        unidad = _norm_unit(ing.get("unidad", ""))
        norm_name = _norm(nombre)

        # Try exact name match first, then prefix match
        stock_item = stock_by_norm.get(norm_name)
        if not stock_item:
            for k, v in stock_by_norm.items():
                if norm_name.startswith(k) or k.startswith(norm_name):
                    stock_item = v
                    break

        if stock_item:
            stock_unit = _norm_unit(stock_item.unit)
            if stock_unit == unidad:
                # Same unit — deduct precisely
                stock_item.quantity = max(0.0, stock_item.quantity - cantidad)
                deducted += 1
            elif stock_item.quantity > 0:
                # Different units but item exists — deduct proportionally
                # (best-effort: assume recipe cantidad covers one meal)
                stock_item.quantity = max(0.0, stock_item.quantity - 1)
                deducted += 1

    # Mark as consumed
    meal.consumed = True
    db.commit()

    msg = f"Marcado+como+cocinado.+{deducted}+ingrediente(s)+descontados+de+la+despensa."
    return RedirectResponse(f"/hogar?tab=cocina&success={msg}", status_code=303)


@router.post("/hogar/cocina/comida/{meal_id}/desmarcar")
def desmarcar_cocinado(meal_id: int, request: Request, db: Session = Depends(get_db)):
    """Unmark a shared meal as cooked."""
    from app.models.meal import Meal

    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    member = hs.get_member(current_user.id, db)
    if not member:
        return RedirectResponse("/hogar?tab=cocina", status_code=303)

    meal = (
        db.query(Meal)
        .join(MealPlan)
        .filter(
            Meal.id == meal_id,
            MealPlan.household_id == member.household_id,
            MealPlan.is_shared == True,
        )
        .first()
    )
    if meal:
        meal.consumed = False
        db.commit()

    return RedirectResponse("/hogar?tab=cocina", status_code=303)
