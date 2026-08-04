"""Helpers for household (shared living) scoping of stock, shopping and meal plans."""
import json
from typing import Optional
from sqlalchemy.orm import Session
from app.models.household import Household, HouseholdMember
from app.models.food_stock import FoodStock


def get_member(user_id: int, db: Session) -> Optional[HouseholdMember]:
    """Return the HouseholdMember record for a user, or None if not in any household."""
    return db.query(HouseholdMember).filter(HouseholdMember.user_id == user_id).first()


def get_household_id(user_id: int, db: Session) -> Optional[int]:
    """Return household_id for a user, or None."""
    m = get_member(user_id, db)
    return m.household_id if m else None


def stock_filter(user_id: int, db: Session):
    """Return the SQLAlchemy filter to scope FoodStock queries for a user."""
    hid = get_household_id(user_id, db)
    if hid:
        return FoodStock.household_id == hid
    return FoodStock.user_id == user_id


def new_stock_kwargs(user_id: int, db: Session) -> dict:
    """Return the FK kwargs to set when inserting a new FoodStock item."""
    hid = get_household_id(user_id, db)
    if hid:
        return {"user_id": user_id, "household_id": hid}
    return {"user_id": user_id, "household_id": None}


def migrate_stock_to_household(user_id: int, household_id: int, db: Session) -> int:
    """Move a user's personal stock to the household. Returns number of items moved."""
    items = db.query(FoodStock).filter(
        FoodStock.user_id == user_id, FoodStock.household_id.is_(None)
    ).all()
    for item in items:
        item.household_id = household_id
    db.commit()
    return len(items)


def get_shared_meal_types(household_id: int, db: Session) -> list[str]:
    """Return the list of meal types shared across all household members."""
    hh = db.query(Household).filter(Household.id == household_id).first()
    if not hh:
        return ["almuerzo"]
    try:
        types = json.loads(hh.shared_meal_types or '["almuerzo"]')
        return types if isinstance(types, list) else ["almuerzo"]
    except Exception:
        return ["almuerzo"]


def get_household_total_pax(household_id: int, db: Session) -> float:
    """Return the sum of all household members' pax values."""
    from app.models.profile import UserProfile
    members = db.query(HouseholdMember).filter(
        HouseholdMember.household_id == household_id
    ).all()
    user_ids = [m.user_id for m in members]
    profiles = db.query(UserProfile).filter(UserProfile.user_id.in_(user_ids)).all()
    return sum(getattr(p, "pax", 1.0) or 1.0 for p in profiles) or 1.0


def get_member_pax_info(household_id: int, db: Session) -> list[dict]:
    """Return list of {user_id, email, display_name, short_name, pax, role} for all household members."""
    from app.models.profile import UserProfile
    members = db.query(HouseholdMember).filter(
        HouseholdMember.household_id == household_id
    ).all()
    result = []
    for m in members:
        profile = db.query(UserProfile).filter(UserProfile.user_id == m.user_id).first()
        email = m.user.email if m.user else "?"
        dn = m.display_name or ""
        short_name = dn if dn else email.split("@")[0]
        result.append({
            "user_id": m.user_id,
            "email": email,
            "display_name": dn,
            "short_name": short_name,
            "pax": getattr(profile, "pax", 1.0) if profile else 1.0,
            "role": m.role,
        })
    return result


def get_plan_acceptance_status(household_id: int, shared_plan, db: Session) -> dict:
    """Return {accepted: [short_names], pending: [short_names]} for non-owner members.

    A member is considered to have 'accepted' (copied) the plan if they have a personal
    MealPlan with the same week_start as the shared plan.
    """
    from app.models.profile import UserProfile
    from app.models.meal_plan import MealPlan

    if not shared_plan:
        return {"accepted": [], "pending": []}

    members = db.query(HouseholdMember).filter(
        HouseholdMember.household_id == household_id
    ).all()

    # Find the owner's user_id
    owner_user_id = shared_plan.profile.user_id if shared_plan.profile else None

    accepted = []
    pending = []
    for m in members:
        if m.user_id == owner_user_id:
            continue  # skip the plan owner
        profile = db.query(UserProfile).filter(UserProfile.user_id == m.user_id).first()
        dn = m.display_name or ""
        short_name = dn if dn else (m.user.email.split("@")[0] if m.user else "?")
        if profile:
            has_copy = db.query(MealPlan).filter(
                MealPlan.profile_id == profile.id,
                MealPlan.week_start == shared_plan.week_start,
            ).first() is not None
        else:
            has_copy = False
        (accepted if has_copy else pending).append(short_name)

    return {"accepted": accepted, "pending": pending}


def migrate_stock_to_personal(user_id: int, db: Session) -> int:
    """Detach a user's stock items from the household when they leave. Returns count."""
    items = db.query(FoodStock).filter(FoodStock.user_id == user_id).all()
    for item in items:
        item.household_id = None
    db.commit()
    return len(items)
