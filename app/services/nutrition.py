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


def calculate_auto_meal_times(training_time: "str | None") -> dict:
    defaults = {"desayuno": "07:00", "media_manana": "10:30", "almuerzo": "13:30", "media_tarde": "17:00", "cena": "20:30"}
    if not training_time:
        return defaults
    try:
        h, m = map(int, training_time.split(":"))
    except Exception:
        return defaults
    tr = h * 60 + m

    def fmt(mins: int) -> str:
        mins = max(300, min(1380, round(mins / 15) * 15))
        return f"{mins // 60:02d}:{mins % 60:02d}"

    if tr < 720:
        return {"desayuno": fmt(tr - 90), "media_manana": fmt(tr + 45), "almuerzo": fmt(tr + 195), "media_tarde": fmt(tr + 375), "cena": fmt(tr + 555)}
    if tr < 1080:
        return {"desayuno": "07:00", "media_manana": "10:30", "almuerzo": fmt(tr - 90), "media_tarde": fmt(tr + 45), "cena": fmt(tr + 210)}
    return {"desayuno": "07:00", "media_manana": "10:30", "almuerzo": "13:30", "media_tarde": fmt(tr - 90), "cena": fmt(tr + 45)}


def get_effective_meal_times(profile: "UserProfile") -> dict:
    """Returns display times for all meals, resolving 'auto' values based on training_time."""
    try:
        stored = json.loads(profile.meal_times) if profile and profile.meal_times else {}
    except Exception:
        stored = {}
    auto_times = calculate_auto_meal_times(profile.training_time if profile else None)
    result = {}
    for meal in ["desayuno", "media_manana", "almuerzo", "media_tarde", "cena"]:
        val = stored.get(meal, "")
        if val == "auto":
            result[meal] = auto_times[meal]
        elif val:
            result[meal] = val
    return result


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
