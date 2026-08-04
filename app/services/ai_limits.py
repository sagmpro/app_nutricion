"""AI usage limits per user.

Limits:
  plan_generate:   6 per calendar month  (resets on 1st of month)
  plan_regenerate: 2 per calendar week   (resets every Monday)
  meal_change:     3 per calendar week   (resets every Monday)
"""
from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session

from app.models.ai_action_log import AIActionLog

LIMITS: dict[str, dict] = {
    "plan_generate":   {"count": 6, "period": "month"},
    "plan_regenerate": {"count": 2, "period": "week"},
    "meal_change":     {"count": 10, "period": "week"},
}


# ── Period helpers ────────────────────────────────────────────────────────────

def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _period_start(action: str, today: date) -> datetime:
    cfg = LIMITS[action]
    if cfg["period"] == "week":
        return datetime.combine(_week_start(today), datetime.min.time())
    return datetime.combine(_month_start(today), datetime.min.time())


# ── Core counters ─────────────────────────────────────────────────────────────

def get_used(db: Session, user_id: int, action: str, today: date | None = None) -> int:
    today = today or date.today()
    since = _period_start(action, today)
    return (
        db.query(AIActionLog)
        .filter(
            AIActionLog.user_id == user_id,
            AIActionLog.action == action,
            AIActionLog.created_at >= since,
        )
        .count()
    )


def get_remaining(db: Session, user_id: int, action: str, today: date | None = None) -> int:
    return max(0, LIMITS[action]["count"] - get_used(db, user_id, action, today))


def log_action(db: Session, user_id: int, action: str) -> None:
    db.add(AIActionLog(user_id=user_id, action=action))
    db.commit()


def get_all_limits(db: Session, user_id: int) -> dict:
    """Return a dict with used/limit/remaining for all actions — passed to templates."""
    today = date.today()
    result = {}
    for action, cfg in LIMITS.items():
        used = get_used(db, user_id, action, today)
        limit = cfg["count"]
        remaining = max(0, limit - used)
        result[action] = {
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "exhausted": remaining == 0,
            "period": cfg["period"],
        }
    return result


# ── Recetario fallbacks (no Claude) ──────────────────────────────────────────

def plan_from_recetario(db: Session, user_id: int, profile, week_start: date) -> dict:
    """Build a full meal-plan dict from saved meals — used when plan_generate limit is hit."""
    from app.models.saved_meal import SavedMeal

    DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    all_types = ["desayuno", "media_manana", "almuerzo", "media_tarde", "cena"]
    try:
        enabled: list[str] = json.loads(profile.enabled_meals) if getattr(profile, "enabled_meals", None) else all_types
    except Exception:
        enabled = all_types

    saved = (
        db.query(SavedMeal)
        .filter(SavedMeal.user_id == user_id, SavedMeal.is_excluded == False)  # noqa: E712
        .all()
    )

    by_type: dict[str, list] = {}
    for sm in saved:
        if sm.meal_type in enabled:
            by_type.setdefault(sm.meal_type, []).append(sm)
    for lst in by_type.values():
        random.shuffle(lst)

    start_weekday = week_start.weekday()
    n_days = 7 - start_weekday
    plan_days = []

    for i in range(n_days):
        day_num = start_weekday + i
        comidas = []
        total_cal = total_prot = total_carbs = total_fat = 0.0

        for meal_type in enabled:
            pool = by_type.get(meal_type, [])
            if not pool:
                continue
            sm = pool[i % len(pool)]
            comidas.append({
                "tipo": meal_type,
                "nombre": sm.name,
                "descripcion": sm.description or "",
                "calorias": sm.calories,
                "proteinas_g": sm.protein_g,
                "carbohidratos_g": sm.carbs_g,
                "grasas_g": sm.fat_g,
                "ingredientes": json.loads(sm.ingredients_json or "[]"),
            })
            total_cal += sm.calories
            total_prot += sm.protein_g
            total_carbs += sm.carbs_g
            total_fat += sm.fat_g

        plan_days.append({
            "dia": DIAS_ES[day_num],
            "dia_numero": day_num,
            "comidas": comidas,
            "total_calorias": round(total_cal),
            "total_proteinas_g": round(total_prot, 1),
            "total_carbohidratos_g": round(total_carbs, 1),
            "total_grasas_g": round(total_fat, 1),
        })

    return {"plan": plan_days}


def meal_from_recetario(
    db: Session,
    user_id: int,
    meal_type: str,
    exclude_names: list[str] | None = None,
) -> dict | None:
    """Return a saved meal of the given type, preferring ones not already in the plan."""
    from app.models.saved_meal import SavedMeal
    from sqlalchemy import case

    exclude = set(exclude_names or [])
    saved = (
        db.query(SavedMeal)
        .filter(
            SavedMeal.user_id == user_id,
            SavedMeal.meal_type == meal_type,
            SavedMeal.is_excluded == False,  # noqa: E712
        )
        .order_by(
            case((SavedMeal.name.notin_(exclude), 0), else_=1),  # not-in-plan first
            SavedMeal.rating.desc().nullslast(),
            SavedMeal.times_served.desc(),
        )
        .first()
    )
    if not saved:
        return None
    return {
        "nombre": saved.name,
        "descripcion": saved.description or "",
        "calorias": saved.calories,
        "proteinas_g": saved.protein_g,
        "carbohidratos_g": saved.carbs_g,
        "grasas_g": saved.fat_g,
        "ingredientes": json.loads(saved.ingredients_json or "[]"),
        "from_recetario": True,
    }
