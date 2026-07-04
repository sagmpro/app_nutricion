from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
import sqlalchemy as sa
from sqlalchemy import String, Float, Integer, DateTime, func
from app.database import Base

if TYPE_CHECKING:
    from app.models.meal_plan import MealPlan


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="Usuario")
    age: Mapped[int] = mapped_column(Integer, default=30)
    gender: Mapped[str] = mapped_column(String(10), default="male")
    weight_kg: Mapped[float] = mapped_column(Float, default=70.0)
    height_cm: Mapped[float] = mapped_column(Float, default=170.0)

    goal_type: Mapped[str] = mapped_column(String(20), default="caloric_deficit")
    target_calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_fat_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_fat_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # JSON array of ints: [0,2,4] = Mon,Wed,Fri
    activity_days: Mapped[str] = mapped_column(String(50), default="[]")

    # Food preferences
    dietary_type: Mapped[str] = mapped_column(String(20), default="omnivoro")
    food_intolerances: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    disliked_foods: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    preferred_foods: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Lifestyle & cooking
    training_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)    # HH:MM start
    training_end: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)    # HH:MM end
    cooking_facilities: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    max_meal_repeats: Mapped[int] = mapped_column(Integer, default=2)

    # Meal schedule: which meals are enabled and at what time (stored as JSON)
    enabled_meals: Mapped[Optional[str]] = mapped_column(sa.Text(), nullable=True)  # JSON list
    meal_times: Mapped[Optional[str]] = mapped_column(sa.Text(), nullable=True)     # JSON dict

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    meal_plans: Mapped[list["MealPlan"]] = relationship(back_populates="profile")
