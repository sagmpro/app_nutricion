import json
import os
import anthropic
from app.config import settings

MODEL = "claude-sonnet-4-6"


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or settings.anthropic_api_key
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY no está configurada en las variables de entorno")
    return anthropic.Anthropic(api_key=api_key)


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

    prompt = f"""Genera un plan de alimentación para una semana completa (lunes a domingo).

Datos de la persona:
- Peso: {profile.weight_kg} kg | Altura: {profile.height_cm} cm | Edad: {profile.age} años
- Género: {"masculino" if profile.gender == "male" else "femenino"}
- TMB: {bmr:.0f} kcal | TDEE: {tdee:.0f} kcal/día
- Objetivo: {goal_desc}
- Días de actividad física: {", ".join(activity_names) if activity_names else "ninguno"}

Distribución calórica por comida:
- Desayuno: ~25% | Media mañana: ~10% | Almuerzo: ~35% | Media tarde: ~10% | Cena: ~20%

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
          "descripcion": "Descripción breve de preparación",
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
Comidas variadas, equilibradas y típicas de España/Latinoamérica."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system="Eres un nutricionista experto. Responde siempre con JSON válido, sin texto adicional ni bloques de código markdown.",
        messages=[{"role": "user", "content": prompt}],
    )
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
        model=MODEL,
        max_tokens=4000,
        system="Eres un asistente de compras. Responde siempre con JSON válido, sin texto adicional.",
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(message.content[0].text)
