import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.profile import UserProfile

ACTIVITY_MULTIPLIERS = [1.2, 1.375, 1.375, 1.55, 1.55, 1.725, 1.725, 1.9]
DAYS_OF_WEEK = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DAYS_SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
DAYS_LETTERS = ["L", "M", "X", "J", "V", "S", "D"]


def calculate_bmr(profile: "UserProfile") -> float:
    """Mifflin-St Jeor formula."""
    base = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * profile.age
    return base + 5 if profile.gender == "male" else base - 161


def get_activity_days_list(profile: "UserProfile") -> list[int]:
    try:
        return json.loads(profile.activity_days or "[]")
    except Exception:
        return []


def calculate_tdee(bmr: float, activity_days_count: int) -> float:
    multiplier = ACTIVITY_MULTIPLIERS[min(activity_days_count, 7)]
    return bmr * multiplier


def calculate_target_calories(profile: "UserProfile", tdee: float) -> float:
    if profile.goal_type == "caloric_deficit":
        return float(profile.target_calories) if profile.target_calories else tdee - 500
    if profile.goal_type == "fat_loss":
        if (
            profile.current_fat_pct is not None
            and profile.target_fat_pct is not None
            and profile.target_days
        ):
            fat_to_lose_kg = profile.weight_kg * (profile.current_fat_pct - profile.target_fat_pct) / 100
            daily_deficit = (fat_to_lose_kg * 7700) / profile.target_days
            return max(tdee - daily_deficit, 1200)
    return tdee
