from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Float, DateTime, Integer, ForeignKey, func
from app.database import Base


class FoodStock(Base):
    __tablename__ = "food_stock"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(50), default="unidades")
    category: Mapped[str] = mapped_column(String(100), default="Otros")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    household_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("households.id"), nullable=True, index=True)

STOCK_CATEGORIES = [
    "Frutas y Verduras",
    "Proteínas",
    "Lácteos y Huevos",
    "Cereales y Legumbres",
    "Aceites y Condimentos",
    "Otros",
]
