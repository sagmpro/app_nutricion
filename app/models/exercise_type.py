from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, Integer, ForeignKey
from app.database import Base

DEFAULT_EXERCISE_TYPES = [
    ("Gym / Pesas", "🏋️"),
    ("Running", "🏃"),
    ("Ciclismo", "🚴"),
    ("Natación", "🏊"),
    ("HIIT / Funcional", "🥊"),
    ("Yoga / Pilates", "🧘"),
    ("Fútbol / Deporte", "⚽"),
    ("Caminata", "🚶"),
]


class ExerciseType(Base):
    __tablename__ = "exercise_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str] = mapped_column(String(10), nullable=False, default="🏃")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
