from typing import TYPE_CHECKING, Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, Text, ForeignKey
from app.database import Base

if TYPE_CHECKING:
    from app.models.meal_plan import MealPlan

MEAL_TYPES = ["desayuno", "media_manana", "almuerzo", "media_tarde", "cena"]
MEAL_TYPE_ORDER = {t: i for i, t in enumerate(MEAL_TYPES)}
MEAL_TYPE_LABELS = {
    "desayuno": "Desayuno",
    "media_manana": "Media Mañana",
    "almuerzo": "Almuerzo",
    "media_tarde": "Media Tarde",
    "cena": "Cena",
}


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_plan_id: Mapped[int] = mapped_column(ForeignKey("meal_plans.id"), index=True)
    day_of_week: Mapped[int] = mapped_column(Integer)
    meal_type: Mapped[str] = mapped_column(String(20))
    meal_order: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    calories: Mapped[int] = mapped_column(Integer, default=0)
    protein_g: Mapped[float] = mapped_column(Float, default=0.0)
    carbs_g: Mapped[float] = mapped_column(Float, default=0.0)
    fat_g: Mapped[float] = mapped_column(Float, default=0.0)
    ingredients_json: Mapped[str] = mapped_column(Text, default="[]")

    # Consumption tracking
    consumed: Mapped[bool] = mapped_column(default=False)
    actual_calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actual_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    recipe_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Regeneration tracking: after 3+ regens, use detailed real-recipe prompt
    regen_count: Mapped[int] = mapped_column(Integer, default=0)

    meal_plan: Mapped["MealPlan"] = relationship(back_populates="meals")
