"""Helpers for household (shared living) scoping of stock, shopping and meal plans."""
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


def migrate_stock_to_personal(user_id: int, db: Session) -> int:
    """Detach a user's stock items from the household when they leave. Returns count."""
    items = db.query(FoodStock).filter(FoodStock.user_id == user_id).all()
    for item in items:
        item.household_id = None
    db.commit()
    return len(items)
