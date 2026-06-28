from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Float, DateTime, func
from app.database import Base


class FoodStock(Base):
    __tablename__ = "food_stock"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(50), default="unidades")
    category: Mapped[str] = mapped_column(String(100), default="Otros")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

STOCK_CATEGORIES = [
    "Frutas y Verduras",
    "Proteínas",
    "Lácteos y Huevos",
    "Cereales y Legumbres",
    "Aceites y Condimentos",
    "Otros",
]
