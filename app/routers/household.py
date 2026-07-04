from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.household import Household, HouseholdMember
from app.models.user import User
from app.models.food_stock import FoodStock
from app.models.meal_plan import MealPlan
from app.models.profile import UserProfile
from app.models.shopping_list import ShoppingList
from app.services.auth_service import get_current_user
from app.services import household_service as hs

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/hogar")
def hogar_index(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    member = hs.get_member(current_user.id, db)
    household = None
    members = []
    stock_count = 0
    shopping_list = None
    shared_plan = None

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

        # Latest household shopping list (from any member's plan)
        household_profile_ids = [
            m.user.profile.id
            for m in members
            if m.user and m.user.profile
        ]
        if household_profile_ids:
            shopping_list = (
                db.query(ShoppingList)
                .filter(ShoppingList.household_id == member.household_id)
                .order_by(ShoppingList.created_at.desc())
                .first()
            )

    return templates.TemplateResponse(request, "household/index.html", {
        "current_user": current_user,
        "member": member,
        "household": household,
        "members": members,
        "stock_count": stock_count,
        "shopping_list": shopping_list,
        "shared_plan": shared_plan,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


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
