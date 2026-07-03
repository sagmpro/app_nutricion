import json
import os
import logging
import anthropic
from app.config import settings

MODEL = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5-20251001"

logger = logging.getLogger(__name__)


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or settings.anthropic_api_key
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY no está configurada en las variables de entorno")
    return anthropic.Anthropic(api_key=api_key)


def _log_usage(fn_name: str, message) -> None:
    u = message.usage
    logger.info("[tokens] %s — input=%d output=%d total=%d", fn_name, u.input_tokens, u.output_tokens, u.input_tokens + u.output_tokens)


def _parse_json(text: str) -> dict:
    """Parse JSON from Claude response, stripping markdown fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = text[text.find("\n") + 1:]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text.strip())


def generate_meal_plan(profile, bmr: float, tdee: float, target_calories: float) -> dict:
    """Call Claude to generate a 7-day meal plan. Returns parsed JSON dict."""
    from app.services.nutrition import get_activity_days_list, DAYS_OF_WEEK

    activity_days = get_activity_days_list(profile)
    activity_names = [DAYS_OF_WEEK[d] for d in activity_days]

    goal_desc = (
        f"Déficit calórico: {target_calories:.0f} kcal/día"
        if profile.goal_type == "caloric_deficit"
        else (
            f"Reducir grasa corporal de {profile.current_fat_pct}% a {profile.target_fat_pct}% "
            f"en {profile.target_days} días ({target_calories:.0f} kcal/día)"
        )
    )

    dietary_map = {"omnivoro": "omnívoro", "vegetariano": "vegetariano", "vegano": "vegano", "pescetariano": "pescetariano"}
    dietary_label = dietary_map.get(getattr(profile, "dietary_type", "omnivoro"), "omnívoro")

    prefs_lines = []
    if getattr(profile, "food_intolerances", None):
        prefs_lines.append(f"- Alergias/intolerancias: {profile.food_intolerances}")
    if getattr(profile, "disliked_foods", None):
        prefs_lines.append(f"- Alimentos que NO le gustan (excluir): {profile.disliked_foods}")
    if getattr(profile, "preferred_foods", None):
        prefs_lines.append(f"- Alimentos favoritos (incluir cuando sea posible): {profile.preferred_foods}")
    prefs_section = "\n".join(prefs_lines) if prefs_lines else "- Sin restricciones adicionales"

    prompt = f"""Genera un plan de alimentación para una semana completa (lunes a domingo).

Datos de la persona:
- Peso: {profile.weight_kg} kg | Altura: {profile.height_cm} cm | Edad: {profile.age} años
- Género: {"masculino" if profile.gender == "male" else "femenino"}
- Tipo de dieta: {dietary_label}
- TMB: {bmr:.0f} kcal | TDEE: {tdee:.0f} kcal/día
- Objetivo: {goal_desc}
- Días de actividad física: {", ".join(activity_names) if activity_names else "ninguno"}

Preferencias alimentarias:
{prefs_section}

Distribución calórica por comida:
- Desayuno: ~25% | Media mañana: ~10% | Almuerzo: ~35% | Media tarde: ~10% | Cena: ~20%

INSTRUCCIONES IMPORTANTES para reducir tokens:
- Desayuno, almuerzo y cena: 7 recetas distintas (una por día), variadas.
- Media mañana y media tarde (snacks): usa SOLO 3-4 opciones diferentes que se repiten a lo largo de la semana. No inventes 7 snacks distintos.
- Descripciones breves (máx 15 palabras).
- Ingredientes: máximo 5 por comida.

Responde ÚNICAMENTE con un JSON válido (sin markdown, sin texto adicional):
{{
  "plan": [
    {{
      "dia": "Lunes",
      "dia_numero": 0,
      "comidas": [
        {{
          "tipo": "desayuno",
          "nombre": "Nombre del plato",
          "descripcion": "Descripción breve",
          "calorias": 450,
          "proteinas_g": 25,
          "carbohidratos_g": 55,
          "grasas_g": 12,
          "ingredientes": [
            {{"nombre": "Avena", "cantidad": 80, "unidad": "g"}},
            {{"nombre": "Leche", "cantidad": 200, "unidad": "ml"}}
          ]
        }}
      ],
      "total_calorias": 1800,
      "total_proteinas_g": 140,
      "total_carbohidratos_g": 180,
      "total_grasas_g": 60
    }}
  ]
}}

Incluye los 7 días con exactamente 5 comidas cada uno (tipos: desayuno, media_manana, almuerzo, media_tarde, cena).
Respeta estrictamente las preferencias alimentarias indicadas. Comidas típicas de España/Latinoamérica."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system="Eres un nutricionista experto. Responde siempre con JSON válido, sin texto adicional ni bloques de código markdown.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("generate_meal_plan", message)
    return _parse_json(message.content[0].text)


def generate_single_meal(profile, meal_type: str, day_name: str, target_calories: int, current_meal_name: str, other_meals: list) -> dict:
    """Call Claude to regenerate a single meal. Returns a parsed meal dict."""
    from app.models.meal import MEAL_TYPE_LABELS

    dietary_map = {"omnivoro": "omnívoro", "vegetariano": "vegetariano", "vegano": "vegano", "pescetariano": "pescetariano"}
    dietary_label = dietary_map.get(getattr(profile, "dietary_type", "omnivoro"), "omnívoro")

    prefs_lines = []
    if getattr(profile, "food_intolerances", None):
        prefs_lines.append(f"- Alergias/intolerancias: {profile.food_intolerances}")
    if getattr(profile, "disliked_foods", None):
        prefs_lines.append(f"- Alimentos que NO le gustan: {profile.disliked_foods}")
    if getattr(profile, "preferred_foods", None):
        prefs_lines.append(f"- Alimentos favoritos: {profile.preferred_foods}")
    prefs_section = "\n".join(prefs_lines) if prefs_lines else "Sin restricciones adicionales"

    other_meals_str = ", ".join(other_meals) if other_meals else "ninguna"
    meal_label = MEAL_TYPE_LABELS.get(meal_type, meal_type)

    prompt = f"""Genera UNA SOLA comida de tipo "{meal_label}" para el {day_name}.

Perfil:
- Dieta: {dietary_label}
- Objetivo calórico para esta comida: ~{target_calories} kcal
{prefs_section}

Comida actual (generar algo DIFERENTE): {current_meal_name}
Otras comidas del día (para evitar repetir ingredientes): {other_meals_str}

Responde ÚNICAMENTE con JSON válido:
{{
  "tipo": "{meal_type}",
  "nombre": "Nombre del plato",
  "descripcion": "Descripción breve de preparación (máx 15 palabras)",
  "calorias": {target_calories},
  "proteinas_g": 25,
  "carbohidratos_g": 40,
  "grasas_g": 10,
  "ingredientes": [
    {{"nombre": "Ingrediente", "cantidad": 100, "unidad": "g"}}
  ]
}}

Máximo 5 ingredientes. Cocina típica de España/Latinoamérica."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system="Eres un nutricionista experto. Responde siempre con JSON válido, sin texto adicional.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("generate_single_meal", message)
    return _parse_json(message.content[0].text)


def generate_shopping_list(all_ingredients: list) -> dict:
    """Call Claude to consolidate and categorize ingredients into a shopping list."""
    if not all_ingredients:
        return {"lista": []}

    prompt = f"""Consolida y categoriza los siguientes ingredientes de un plan semanal de comidas.
Agrupa ingredientes iguales sumando sus cantidades (misma unidad) o listando por separado (distintas unidades).
Normaliza nombres (ej: "tomates" → "Tomate").

Ingredientes: {json.dumps(all_ingredients, ensure_ascii=False)}

Responde ÚNICAMENTE con JSON válido:
{{
  "lista": [
    {{
      "categoria": "Frutas y Verduras",
      "items": [
        {{"nombre": "Tomate", "cantidad": 500, "unidad": "g"}},
        {{"nombre": "Lechuga", "cantidad": 2, "unidad": "unidades"}}
      ]
    }}
  ]
}}

Categorías a usar: Frutas y Verduras, Proteínas, Lácteos y Huevos, Cereales y Legumbres, Aceites y Condimentos, Otros."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=4000,
        system="Eres un asistente de compras. Responde siempre con JSON válido, sin texto adicional.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("generate_shopping_list", message)
    return _parse_json(message.content[0].text)
