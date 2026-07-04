from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, DateTime, ForeignKey, func
from app.database import Base

if TYPE_CHECKING:
    from app.models.meal_plan import MealPlan
    from app.models.shopping_item import ShoppingItem


class ShoppingList(Base):
    __tablename__ = "shopping_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_plan_id: Mapped[int] = mapped_column(ForeignKey("meal_plans.id"), unique=True)
    household_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("households.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    meal_plan: Mapped["MealPlan"] = relationship(back_populates="shopping_list")
    items: Mapped[list["ShoppingItem"]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
        order_by="ShoppingItem.category, ShoppingItem.name",
    )
