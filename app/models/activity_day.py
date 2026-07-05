from typing import Optional, TYPE_CHECKING
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, ForeignKey
from app.database import Base

if TYPE_CHECKING:
    from app.models.profile import UserProfile
    from app.models.exercise_type import ExerciseType


class ActivityDayConfig(Base):
    __tablename__ = "activity_day_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("user_profiles.id"), nullable=False, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Lunes ... 6=Domingo
    exercise_type_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("exercise_types.id"), nullable=True)
    start_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # HH:MM
    end_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)    # HH:MM

    profile: Mapped["UserProfile"] = relationship(back_populates="activity_day_configs")
    exercise_type: Mapped[Optional["ExerciseType"]] = relationship("ExerciseType", lazy="joined")
