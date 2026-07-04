from datetime import date, datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Boolean, Integer, String, Date, DateTime, Text, ForeignKey, func
from app.database import Base

if TYPE_CHECKING:
    from app.models.profile import UserProfile
    from app.models.meal import Meal
    from app.models.shopping_list import ShoppingList


class MealPlan(Base):
    __tablename__ = "meal_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    week_start: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    household_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("households.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    profile: Mapped["UserProfile"] = relationship(back_populates="meal_plans")
    meals: Mapped[list["Meal"]] = relationship(
        back_populates="meal_plan",
        cascade="all, delete-orphan",
        order_by="Meal.day_of_week, Meal.meal_order",
    )
    shopping_list: Mapped[Optional["ShoppingList"]] = relationship(
        back_populates="meal_plan", uselist=False, cascade="all, delete-orphan"
    )
