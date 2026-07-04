import json
import os
import base64
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

    lifestyle_lines = []
    if getattr(profile, "training_time", None):
        lifestyle_lines.append(f"- Hora de entrenamiento: {profile.training_time} (sugiere comidas apropiadas antes/después)")
    if getattr(profile, "cooking_facilities", None):
        lifestyle_lines.append(f"- Facilidades de cocina: {profile.cooking_facilities}")
    max_repeats = getattr(profile, "max_meal_repeats", 2)
    lifestyle_lines.append(f"- Máximo de veces que puede repetirse una receta de desayuno/almuerzo/cena en la semana: {max_repeats}")
    lifestyle_section = "\n".join(lifestyle_lines)

    # Meal schedule
    all_meal_types = ["desayuno", "media_manana", "almuerzo", "media_tarde", "cena"]
    meal_labels_map = {"desayuno": "Desayuno", "media_manana": "Media mañana",
                       "almuerzo": "Almuerzo", "media_tarde": "Media tarde", "cena": "Cena"}
    base_pcts = {"desayuno": 25, "media_manana": 10, "almuerzo": 35, "media_tarde": 10, "cena": 20}
    snack_types = {"media_manana", "media_tarde"}

    try:
        enabled_meals = json.loads(profile.enabled_meals) if getattr(profile, "enabled_meals", None) else all_meal_types
    except (ValueError, TypeError):
        enabled_meals = all_meal_types
    try:
        meal_times_dict = json.loads(profile.meal_times) if getattr(profile, "meal_times", None) else {}
    except (ValueError, TypeError):
        meal_times_dict = {}

    total_pct = sum(base_pcts[m] for m in enabled_meals) or 100
    schedule_lines = []
    for m in enabled_meals:
        pct = round(base_pcts[m] / total_pct * 100)
        time_str = f" a las {meal_times_dict[m]}" if m in meal_times_dict else ""
        schedule_lines.append(f"- {meal_labels_map[m]}{time_str}: ~{pct}% de las calorías diarias")
    schedule_section = "\n".join(schedule_lines)

    enabled_types_str = ", ".join(enabled_meals)
    n_meals = len(enabled_meals)
    enabled_snacks = [m for m in enabled_meals if m in snack_types]
    snack_note = (f"- Snacks ({', '.join(meal_labels_map[s] for s in enabled_snacks)}): usa SOLO 3-4 opciones distintas que se repiten a lo largo de la semana."
                  if enabled_snacks else "")

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

Estilo de vida:
{lifestyle_section}

Comidas del día (SOLO estas, en este orden):
{schedule_section}

INSTRUCCIONES IMPORTANTES:
- Genera exactamente {n_meals} comida(s) por día (tipos: {enabled_types_str}). No añadas ni quites comidas.
- Desayuno, almuerzo y cena: 7 recetas distintas (una por día), variadas.
{snack_note}
- Descripciones breves (máx 15 palabras).
- Ingredientes: máximo 5 por comida.
- CONSISTENCIA DE INGREDIENTES: usa nombres exactos y consistentes en todo el plan. Si un ingrediente puede estar crudo o cocido, elige UNO y mantenlo así toda la semana (ej: usa siempre "garbanzos cocidos" o siempre "garbanzos crudos", nunca ambos). Especifica el estado cuando sea relevante: "lentejas crudas", "garbanzos cocidos en conserva", "pechuga de pollo", "atún en conserva".

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

Incluye los 7 días con exactamente {n_meals} comida(s) cada uno (tipos: {enabled_types_str}).
Respeta estrictamente las preferencias alimentarias indicadas. Comidas típicas de España/Latinoamérica."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system="Eres un nutricionista deportivo experto con amplio conocimiento en rendimiento atlético, recuperación muscular, periodización nutricional y planificación de comidas para personas activas. Ajusta los planes considerando el momento del entrenamiento (pre/post-workout). Responde siempre con JSON válido, sin texto adicional ni bloques de código markdown.",
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

Máximo 5 ingredientes. Cocina típica de España/Latinoamérica.
Usa nombres de ingredientes específicos y consistentes: indica el estado cuando sea relevante (ej: "garbanzos cocidos", "lentejas crudas", "atún en conserva")."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system="Eres un nutricionista deportivo experto. Responde siempre con JSON válido, sin texto adicional.",
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


def analyze_food_photo(image_bytes: bytes, media_type: str) -> dict:
    """Analyze a food photo or nutrition label and estimate calories/macros."""
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
            {"type": "text", "text": """Analiza esta imagen. Puede ser una foto de comida o una etiqueta nutricional.
Estima las calorías y macronutrientes.
Responde ÚNICAMENTE con JSON válido:
{"nombre": "Nombre del alimento", "calorias": 350, "proteinas_g": 25, "carbohidratos_g": 40, "grasas_g": 10}"""},
        ]}],
    )
    _log_usage("analyze_food_photo", message)
    return _parse_json(message.content[0].text)


def generate_recipe(meal_name: str, ingredients: list, meal_type: str, description: str = "") -> dict:
    """Generate step-by-step cooking instructions for a meal. Uses Haiku to save tokens."""
    ing_str = ", ".join(
        f"{i['nombre']} ({i['cantidad']} {i['unidad']})" for i in ingredients
    ) if ingredients else "ingredientes del plato"

    prompt = f"""Genera una receta paso a paso para: {meal_name}
Tipo: {meal_type}{f' | {description}' if description else ''}
Ingredientes: {ing_str}

Responde ÚNICAMENTE con JSON válido:
{{"pasos": ["Paso 1...", "Paso 2..."], "tiempo_prep": 10, "tiempo_coccion": 20, "porciones": 1}}

Máximo 8 pasos concisos. Cocina española/latinoamericana."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=800,
        system="Eres un chef experto. Responde siempre con JSON válido, sin texto adicional.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("generate_recipe", message)
    return _parse_json(message.content[0].text)


def identify_stock_photo(image_bytes: bytes, media_type: str) -> dict:
    """Identify food items in a photo and return them as stock items."""
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
            {"type": "text", "text": """Identifica todos los alimentos o ingredientes visibles en esta imagen.
Estima cantidades aproximadas para cada uno.
Responde ÚNICAMENTE con JSON válido:
{"items": [{"nombre": "Tomate", "cantidad": 3, "unidad": "unidades", "categoria": "Frutas y Verduras"}]}
Categorías: Frutas y Verduras, Proteínas, Lácteos y Huevos, Cereales y Legumbres, Aceites y Condimentos, Otros"""},
        ]}],
    )
    _log_usage("identify_stock_photo", message)
    return _parse_json(message.content[0].text)
