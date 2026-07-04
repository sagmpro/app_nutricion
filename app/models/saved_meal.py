from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, Text, Boolean, DateTime, ForeignKey
from app.database import Base


UNHEALTHY_KEYWORDS = {
    "frito", "fritado", "empanizado", "rebozado", "azúcar", "azucar",
    "mantequilla", "crema", "nata", "embutido", "tocino", "salchicha",
    "chorizo", "panceta", "chicharron", "chicharrón", "manteca",
    "aceite de palma", "sirope", "jarabe", "gaseosa",
}
HEALTHY_KEYWORDS = {
    "verdura", "vegetal", "ensalada", "espinaca", "brócoli", "brocoli",
    "zanahoria", "tomate", "pepino", "lechuga", "fruta", "manzana",
    "plátano", "avena", "quinoa", "quinua", "legumbre", "lenteja",
    "garbanzo", "frijol", "pollo", "pavo", "pescado", "salmón", "salmon",
    "atún", "atun", "clara", "yogur", "kéfir", "integral",
}


def classify_health(ingredients_json: str) -> Optional[bool]:
    """Simple ingredient-based healthiness classification."""
    import json
    try:
        ings = json.loads(ingredients_json or "[]")
    except Exception:
        return None
    text = " ".join(i.get("nombre", "").lower() for i in ings)
    unhealthy_hits = sum(1 for k in UNHEALTHY_KEYWORDS if k in text)
    healthy_hits = sum(1 for k in HEALTHY_KEYWORDS if k in text)
    if unhealthy_hits >= 2:
        return False
    if healthy_hits >= 2:
        return True
    return None


def upsert_saved_meal(db, user_id: int, meal) -> None:
    """Save or update a meal in the user's recipe repository."""
    from datetime import datetime as _dt
    existing = db.query(SavedMeal).filter(
        SavedMeal.user_id == user_id,
        SavedMeal.name == meal.name,
        SavedMeal.meal_type == meal.meal_type,
    ).first()
    if existing:
        existing.times_served += 1
        existing.last_served_at = _dt.utcnow()
        if not existing.ingredients_json or existing.ingredients_json == "[]":
            existing.ingredients_json = meal.ingredients_json or "[]"
        if not existing.recipe_text and meal.recipe_text:
            existing.recipe_text = meal.recipe_text
        if existing.is_healthy is None:
            existing.is_healthy = classify_health(existing.ingredients_json)
    else:
        health = classify_health(meal.ingredients_json or "[]")
        db.add(SavedMeal(
            user_id=user_id,
            name=meal.name,
            meal_type=meal.meal_type,
            description=meal.description,
            calories=meal.calories or 0,
            protein_g=meal.protein_g or 0.0,
            carbs_g=meal.carbs_g or 0.0,
            fat_g=meal.fat_g or 0.0,
            ingredients_json=meal.ingredients_json or "[]",
            recipe_text=meal.recipe_text,
            is_healthy=health,
            last_served_at=_dt.utcnow(),
        ))


class SavedMeal(Base):
    __tablename__ = "saved_meals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    meal_type: Mapped[str] = mapped_column(String(20))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    calories: Mapped[int] = mapped_column(Integer, default=0)
    protein_g: Mapped[float] = mapped_column(Float, default=0.0)
    carbs_g: Mapped[float] = mapped_column(Float, default=0.0)
    fat_g: Mapped[float] = mapped_column(Float, default=0.0)
    ingredients_json: Mapped[str] = mapped_column(Text, default="[]")
    recipe_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_healthy: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    times_served: Mapped[int] = mapped_column(Integer, default=1)
    last_served_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
