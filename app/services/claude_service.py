import json
import os
import base64
import logging
from contextvars import ContextVar
import anthropic
from app.config import settings

MODEL = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5-20251001"

logger = logging.getLogger(__name__)

_token_user_id: ContextVar[int | None] = ContextVar("token_user_id", default=None)


def set_token_user_id(user_id: int | None) -> None:
    """Set the current user id for token usage tracking. Call from routers before invoking Claude."""
    _token_user_id.set(user_id)


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or settings.anthropic_api_key
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY no está configurada en las variables de entorno")
    return anthropic.Anthropic(api_key=api_key)


def _country(profile) -> str:
    c = getattr(profile, "country", None) if profile else None
    return c or "España/Latinoamérica"


def _log_usage(fn_name: str, message) -> None:
    u = message.usage
    total = u.input_tokens + u.output_tokens
    logger.info("[tokens] %s — input=%d output=%d total=%d", fn_name, u.input_tokens, u.output_tokens, total)
    user_id = _token_user_id.get()
    if user_id:
        try:
            from app.database import SessionLocal
            from app.models.token_usage import TokenUsage
            db = SessionLocal()
            db.add(TokenUsage(
                user_id=user_id,
                function_name=fn_name,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
            ))
            db.commit()
            db.close()
        except Exception as exc:
            logger.warning("[tokens] failed to persist usage: %s", exc)


def _parse_json(text: str) -> dict:
    """Parse JSON from Claude response, stripping markdown fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = text[text.find("\n") + 1:]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text.strip())


def _workout_meal_section(workout_context: dict | None) -> str:
    """Return a prompt section describing pre/post-workout nutrition constraints."""
    if not workout_context:
        return ""
    et_list = ", ".join(workout_context.get("exercise_types", [])) or "ejercicio"
    et_lower = et_list.lower()

    if workout_context.get("is_pre_workout"):
        start = workout_context.get("earliest_start", "")
        time_ref = f" a las {start}" if start else ""
        if any(x in et_lower for x in ["gym", "pesas", "musculaci", "fuerza"]):
            guideline = "Carbohidratos complejos + proteína (arroz + pollo, pasta + atún). Bajo en grasa y fibra."
        elif any(x in et_lower for x in ["running", "correr", "ciclismo", "bici", "nataci", "nadar"]):
            guideline = "Carbohidratos de fácil digestión (arroz blanco, plátano, pan). Muy bajo en grasa y fibra para evitar molestias gastrointestinales."
        elif any(x in et_lower for x in ["hiit", "funcional", "crossfit", "intervalo"]):
            guideline = "Carbohidratos simples + proteína ligera. Muy bajo en grasa. Fácil y rápido de digerir."
        elif any(x in et_lower for x in ["fútbol", "futbol", "baloncesto", "tenis", "pádel", "padel", "deporte"]):
            guideline = "Carbohidratos + proteína moderada. Energía sostenida para esfuerzo intermitente."
        elif any(x in et_lower for x in ["yoga", "pilates", "flexibilidad"]):
            guideline = "Comida ligera y fácil de digerir. Porciones reducidas. Sin alimentos pesados."
        elif any(x in et_lower for x in ["caminata", "caminar"]):
            guideline = "Comida equilibrada normal, sin ajuste especial necesario."
        else:
            guideline = "Prioriza carbohidratos complejos + proteína moderada. Bajo en grasa."
        return (
            f"\n⚡ NUTRICIÓN PRE-ENTRENAMIENTO: El usuario entrena {et_list}{time_ref}. "
            f"Esta comida debe prepararlo para el entrenamiento: {guideline}\n"
        )

    if workout_context.get("is_post_workout"):
        end = workout_context.get("latest_end", "")
        time_ref = f" (terminó a las {end})" if end else ""
        return (
            f"\n💪 NUTRICIÓN POST-ENTRENAMIENTO: El usuario acaba de terminar {et_list}{time_ref}. "
            "Prioriza proteína de calidad + carbohidratos para recuperación muscular. "
            "Evita exceso de grasa en las primeras horas post-entreno.\n"
        )
    return ""


def _meal_type_context(meal_type: str) -> str:
    """Return qualitative guidance about what a meal type should be."""
    contexts = {
        "desayuno": (
            "TIPO DE COMIDA — Desayuno: primera comida del día, nutritiva y energizante. "
            "Ejemplos: tostadas con huevo, porridge, yogur con fruta, tortilla, batido proteico. "
            "Representa ~25% de las calorías diarias."
        ),
        "media_manana": (
            "TIPO DE COMIDA — Media mañana: SNACK ligero de media mañana. Pequeño y fácil de preparar. "
            "Ejemplos: fruta, yogur, puñado de frutos secos, barrita, tostada pequeña. "
            "NO es una comida principal. Representa ~10% de las calorías diarias."
        ),
        "almuerzo": (
            "TIPO DE COMIDA — Almuerzo: comida principal y más abundante del día. "
            "Ejemplos: pasta, arroz con pollo, potaje, ensalada completa con proteína, plato combinado. "
            "Representa ~35% de las calorías diarias."
        ),
        "media_tarde": (
            "TIPO DE COMIDA — Media tarde: SNACK ligero de tarde. Pequeño y sencillo. "
            "Ejemplos: fruta, yogur, tostada con queso, batido pequeño, frutos secos. "
            "NO es una comida principal ni un plato elaborado. Representa ~10% de las calorías diarias."
        ),
        "cena": (
            "TIPO DE COMIDA — Cena: última comida del día, más ligera que el almuerzo pero completa. "
            "Ejemplos: sopa, crema de verduras, tortilla, ensalada con proteína, pescado al horno. "
            "Preferiblemente fácil de digerir. Representa ~20% de las calorías diarias."
        ),
    }
    ctx = contexts.get(meal_type)
    return f"\n{ctx}\n" if ctx else ""


def generate_meal_plan(profile, bmr: float, tdee: float, target_calories: float, saved_meals: list | None = None) -> dict:
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
    day_configs = getattr(profile, "activity_day_configs", [])
    if day_configs:
        from app.services.nutrition import DAYS_OF_WEEK
        from itertools import groupby
        training_lines = []
        for day_num, day_cfgs in groupby(sorted(day_configs, key=lambda c: c.day_of_week), key=lambda c: c.day_of_week):
            day_cfgs = list(day_cfgs)
            day_name = DAYS_OF_WEEK[day_num]
            session_strs = []
            for cfg in day_cfgs:
                et = cfg.exercise_type
                type_str = f"{et.icon} {et.name}" if et else "Ejercicio"
                if cfg.start_time and cfg.end_time:
                    type_str += f" ({cfg.start_time}–{cfg.end_time})"
                elif cfg.start_time:
                    type_str += f" (desde {cfg.start_time})"
                session_strs.append(type_str)
            training_lines.append(f"  * {day_name}: {' + '.join(session_strs)}")
        lifestyle_lines.append("- Días de entrenamiento:\n" + "\n".join(training_lines))
    elif getattr(profile, "training_time", None):
        t_end = getattr(profile, "training_end", None)
        t_range = f"{profile.training_time}–{t_end}" if t_end else profile.training_time
        lifestyle_lines.append(f"- Entrenamiento: {t_range} (ajusta comidas pre y post entreno)")
    if getattr(profile, "cooking_facilities", None):
        lifestyle_lines.append(f"- Facilidades de cocina: {profile.cooking_facilities}")
    max_repeats = getattr(profile, "max_meal_repeats", 2)
    lifestyle_lines.append(f"- Máximo de veces que puede repetirse una receta de desayuno/almuerzo/cena en la semana: {max_repeats}")
    lifestyle_section = "\n".join(lifestyle_lines)

    # Meal schedule
    from app.services.nutrition import get_effective_meal_times
    all_meal_types = ["desayuno", "media_manana", "almuerzo", "media_tarde", "cena"]
    meal_labels_map = {"desayuno": "Desayuno", "media_manana": "Media mañana",
                       "almuerzo": "Almuerzo", "media_tarde": "Media tarde", "cena": "Cena"}
    base_pcts = {"desayuno": 25, "media_manana": 10, "almuerzo": 35, "media_tarde": 10, "cena": 20}
    snack_types = {"media_manana", "media_tarde"}

    try:
        enabled_meals = json.loads(profile.enabled_meals) if getattr(profile, "enabled_meals", None) else all_meal_types
    except (ValueError, TypeError):
        enabled_meals = all_meal_types

    # Resolve "auto" values so Claude receives concrete times, not the literal string "auto"
    meal_times_dict = get_effective_meal_times(profile)

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

    # Build recetario section
    recetario_section = ""
    has_recetario = False
    if saved_meals:
        from collections import defaultdict
        by_type: dict = defaultdict(list)
        for sm in saved_meals:
            by_type[sm.meal_type].append(sm)
        lines = []
        for mt in ["desayuno", "media_manana", "almuerzo", "media_tarde", "cena"]:
            if mt not in by_type:
                continue
            sorted_meals = sorted(by_type[mt], key=lambda x: (-(x.rating or 0), -x.times_served))
            names = [sm.name for sm in sorted_meals]
            lines.append(f"- {meal_labels_map.get(mt, mt)}: {', '.join(names)}")
        if lines:
            has_recetario = True
            recetario_section = (
                "\nRecetario del usuario (USAR ESTOS PLATOS EN EL PLAN — no inventar otros salvo que falten):\n"
                + "\n".join(lines) + "\n"
            )

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
{recetario_section}
Comidas del día (SOLO estas, en este orden):
{schedule_section}

NUTRICIÓN EN DÍAS DE ENTRENAMIENTO:
Los horarios de entrenamiento y tipos de ejercicio están en "Estilo de vida". Para cada día de entreno:
1. Identifica la comida más cercana ANTES del inicio del entrenamiento (pre-entreno) y la inmediatamente POSTERIOR (post-entreno).
2. Adapta la comida PRE-ENTRENO según el tipo de ejercicio:
   - Gym/Pesas 🏋️: carbohidratos complejos + proteína moderada (arroz + pollo/huevo, pasta + atún). Bajo en grasa y fibra. Porciones que aporten energía sostenida.
   - Running / Ciclismo / Natación 🏃🚴🏊: carbohidratos de rápida digestión (arroz blanco, plátano, pan), muy bajo en grasa y fibra para evitar molestias. Proteína moderada.
   - HIIT / Funcional 🥊: carbohidratos simples + algo de proteína. Muy bajo en grasa y fibra. Ligero y de fácil digestión.
   - Fútbol / Deporte colectivo ⚽: carbohidratos + proteína moderada. Hidratación implícita en alimentos.
   - Yoga / Pilates 🧘: comida ligera, fácil de digerir, porciones reducidas. Sin exceso de proteína ni grasa.
   - Caminata 🚶: comida normal equilibrada, sin ajuste especial.
3. La comida POST-ENTRENO debe priorizar proteína de calidad (para recuperación muscular) + carbohidratos (para recargar glucógeno). Evitar exceso de grasa en la 1ª hora post-entreno.
4. El resto de comidas del día de entreno pueden tener calorías ligeramente superiores al resto de la semana si el objetivo lo permite.

INSTRUCCIONES IMPORTANTES:
- Genera exactamente {n_meals} comida(s) por día (tipos: {enabled_types_str}). No añadas ni quites comidas.
- {"USA EXCLUSIVAMENTE los platos del recetario para cada tipo de comida que tenga entradas. Si para un tipo de comida hay menos platos que días de la semana, puedes repetir o inventar los que falten." if has_recetario else "Desayuno, almuerzo y cena: máximo " + str(max_repeats) + " veces el mismo plato en la semana."}
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
Respeta estrictamente las preferencias alimentarias indicadas.
País del usuario: {_country(profile)} — usa ingredientes, nombres y medidas típicas de ese país. Los nombres de ingredientes deben ser consistentes con el vocabulario local (ej: en México "elote" no "choclo", en Argentina "choclo" no "maíz dulce")."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system="Eres un nutricionista deportivo experto con amplio conocimiento en rendimiento atlético, recuperación muscular, periodización nutricional y planificación de comidas para personas activas. Ajusta los planes considerando el momento del entrenamiento (pre/post-workout). Usa siempre ortografía española correcta con tildes y puntuación. Responde siempre con JSON válido, sin texto adicional ni bloques de código markdown.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("generate_meal_plan", message)
    return _parse_json(message.content[0].text)


def generate_single_meal(
    profile,
    meal_type: str,
    day_name: str,
    target_calories: int,
    current_meal_name: str,
    other_meals: list,
    avoided_meals: list | None = None,
    workout_context: dict | None = None,
) -> dict:
    """Call Claude to regenerate a single meal. Returns a parsed meal dict."""
    import random
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

    avoid_section = ""
    if avoided_meals:
        avoid_section = f"Platos que NO debes sugerir (ya los tiene en su recetario o los ha visto): {', '.join(avoided_meals[:20])}\n"

    # Seed for variety — encourages Claude to explore different culinary directions
    seed_words = ["mediterráneo", "asiático", "latinoamericano", "clásico local", "fusión", "ligero", "proteico", "vegetariano ocasional"]
    direction = random.choice(seed_words)

    workout_section = _workout_meal_section(workout_context)
    meal_context = _meal_type_context(meal_type)

    prompt = f"""Genera UNA SOLA comida de tipo "{meal_label}" para el {day_name}.
{meal_context}
Perfil:
- Dieta: {dietary_label}
- Objetivo calórico para esta comida: ~{target_calories} kcal
{prefs_section}
{workout_section}
Comida actual (genera algo COMPLETAMENTE DIFERENTE, no una variación del mismo plato): {current_meal_name}
{avoid_section}Otras comidas del día (evitar repetir ingredientes principales): {other_meals_str}

Dirección culinaria a explorar esta vez: {direction}

IMPORTANTE: Sé creativo. No repitas las opciones más predecibles ni lo que el usuario ya conoce. Sorprende con algo variado y apetecible.

Elige los ingredientes y sus cantidades para que el total se acerque a ~{target_calories} kcal.
CALCULA los valores nutricionales reales basándote en los ingredientes y cantidades que elijas — no copies el objetivo directamente.

Responde ÚNICAMENTE con JSON válido:
{{
  "tipo": "{meal_type}",
  "nombre": "Nombre del plato",
  "descripcion": "Descripción breve de preparación (máx 15 palabras)",
  "calorias": 0,
  "proteinas_g": 0.0,
  "carbohidratos_g": 0.0,
  "grasas_g": 0.0,
  "ingredientes": [
    {{"nombre": "Ingrediente", "cantidad": 100, "unidad": "g"}}
  ]
}}

Reemplaza los 0 con los valores nutricionales calculados de los ingredientes que elijas.
Máximo 5 ingredientes. País del usuario: {_country(profile)} — adapta ingredientes al contexto local.
Indica el estado cuando sea relevante: "garbanzos cocidos", "lentejas crudas", "atún en conserva"."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        temperature=1.0,
        system="Eres un nutricionista y chef creativo. Cada sugerencia debe ser diferente y sorprendente. Usa siempre ortografía española correcta con tildes. Responde siempre con JSON válido, sin texto adicional.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("generate_single_meal", message)
    return _parse_json(message.content[0].text)


def generate_shopping_list(all_ingredients: list, stock_items: list | None = None) -> dict:
    """Call Claude to consolidate and categorize ingredients into a shopping list."""
    if not all_ingredients:
        return {"lista": []}

    stock_section = ""
    if stock_items:
        stock_section = f"""
Stock disponible actualmente (descuenta lo que ya hay en casa):
{json.dumps(stock_items, ensure_ascii=False)}

Reglas de descuento:
- Si el stock cubre completamente la cantidad necesaria, NO incluyas ese ingrediente.
- Si cubre parcialmente (misma unidad), incluye solo la cantidad faltante.
- Si las unidades difieren (ej: stock en "unidades", plan en "g"), incluye igual en la lista.
"""

    prompt = f"""Consolida y categoriza los ingredientes de un plan semanal de comidas para generar la lista de lo que hay que COMPRAR.

NORMALIZACIÓN DE NOMBRES (muy importante):
- Usa siempre el nombre simple y canónico del ingrediente: "pizca de sal" → "Sal", "dientes de ajo" → "Ajo", "hojas de albahaca" → "Albahaca", "tomates cherry" → "Tomate cherry".
- Elimina descriptores de cantidad del nombre: "2 cucharadas de aceite de oliva" → nombre: "Aceite de oliva".
- Unifica variantes del mismo ingrediente: "tomate" y "tomates" → "Tomate"; "pechuga de pollo" y "pollo" (si son el mismo ingrediente) → "Pechuga de pollo".
- Capitaliza la primera letra del nombre, el resto en minúsculas.
- Agrupa ingredientes con el mismo nombre normalizado sumando cantidades (misma unidad) o listando por separado (distintas unidades).
- Escribe todos los textos con correcta ortografía española (tildes, puntuación).
{stock_section}
Ingredientes del plan: {json.dumps(all_ingredients, ensure_ascii=False)}

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

Categorías a usar: Frutas y Verduras, Proteínas, Lácteos y Huevos, Cereales y Legumbres, Aceites y Condimentos, Otros.
Si todos los ingredientes están cubiertos por el stock, devuelve {{"lista": []}}."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=4000,
        system="Eres un asistente de compras. Usa ortografía española correcta con tildes en todos los nombres. Responde siempre con JSON válido, sin texto adicional.",
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
        system="Eres un chef experto. Usa ortografía española correcta con tildes. Responde siempre con JSON válido, sin texto adicional.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("generate_recipe", message)
    return _parse_json(message.content[0].text)


def propose_meal_schedule(profile) -> dict:
    """Ask Claude (Haiku) to propose optimal meal times based on the user's profile."""
    from app.services.nutrition import get_activity_days_list, DAYS_OF_WEEK

    activity_days = get_activity_days_list(profile)
    activity_names = [DAYS_OF_WEEK[d] for d in activity_days]
    if getattr(profile, "training_time", None):
        t_end = getattr(profile, "training_end", None)
        training_info = f"Entrenamiento: {profile.training_time}–{t_end}" if t_end else f"Entrenamiento: {profile.training_time}"
    else:
        training_info = "Sin hora de entrenamiento fija"

    goal_map = {"caloric_deficit": "déficit calórico", "fat_loss": "reducción de grasa corporal"}
    goal_str = goal_map.get(getattr(profile, "goal_type", "caloric_deficit"), "déficit calórico")

    prompt = f"""Propón un horario óptimo de comidas para esta persona activa.

Perfil:
- Edad: {profile.age} años | Género: {"masculino" if profile.gender == "male" else "femenino"}
- Peso: {profile.weight_kg} kg | Altura: {profile.height_cm} cm
- {training_info}
- Días de actividad: {", ".join(activity_names) if activity_names else "ninguno"}
- Objetivo: {goal_str}
- Tipo de dieta: {getattr(profile, "dietary_type", "omnivoro")}

Criterios:
1. Optimiza pre/post-workout si hay hora de entrenamiento
2. Distribuye energía según la actividad a lo largo del día
3. Puedes omitir media mañana o media tarde si no aportan valor
4. Horarios prácticos y sostenibles

Responde ÚNICAMENTE con JSON válido:
{{
  "enabled_meals": ["desayuno", "almuerzo", "cena"],
  "meal_times": {{
    "desayuno": "07:00",
    "almuerzo": "13:30",
    "cena": "20:30"
  }},
  "explicacion": "Explicación breve del criterio (máx 100 palabras)"
}}

Tipos válidos: desayuno, media_manana, almuerzo, media_tarde, cena.
Incluye en enabled_meals y meal_times SOLO las comidas que recomiendas. Formato de hora: HH:MM (24h)."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=600,
        system="Eres un nutricionista deportivo experto. Usa ortografía española correcta con tildes. Responde siempre con JSON válido, sin texto adicional.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("propose_meal_schedule", message)
    return _parse_json(message.content[0].text)


def generate_real_recipe_meal(
    meal_name: str,
    meal_type: str,
    target_calories: int,
    profile=None,
) -> dict:
    """Generate a detailed, traditional recipe after 3+ regenerations.
    Uses a richer prompt to produce step-by-step recipes with exact quantities."""
    from app.models.meal import MEAL_TYPE_LABELS
    meal_label = MEAL_TYPE_LABELS.get(meal_type, meal_type)

    intolerances = ""
    if profile and getattr(profile, "food_intolerances", None):
        intolerances = f"Evitar: {profile.food_intolerances}."

    meal_context = _meal_type_context(meal_type)

    prompt = f"""Eres un chef profesional y nutricionista. Genera una receta real, tradicional y detallada de "{meal_name}" (tipo: {meal_label}).
{meal_context}
{intolerances}
Objetivo calórico: ~{target_calories} kcal.

Responde ÚNICAMENTE con JSON válido:
{{
  "tipo": "{meal_type}",
  "nombre": "Nombre exacto del plato",
  "descripcion": "Descripción culinaria precisa (máx 20 palabras)",
  "calorias": {target_calories},
  "proteinas_g": 0.0,
  "carbohidratos_g": 0.0,
  "grasas_g": 0.0,
  "ingredientes": [
    {{"nombre": "Ingrediente", "cantidad": 100, "unidad": "g"}}
  ],
  "receta_detallada": "Paso 1: ...\\nPaso 2: ...\\nPaso 3: ..."
}}

Incluye entre 6-10 ingredientes con cantidades exactas. La receta debe tener al menos 4 pasos detallados de preparación.
País del usuario: {_country(profile)} — usa ingredientes y nombres típicos de ese país."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system="Eres un chef y nutricionista experto. Genera recetas reales con pasos detallados. Usa ortografía española correcta con tildes. Responde SOLO con JSON válido.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("generate_real_recipe_meal", message)
    return _parse_json(message.content[0].text)


def buscar_plato_por_nombre(
    nombre: str,
    meal_type: str,
    target_calories: int,
    stock_items: list | None = None,
    profile=None,
    workout_context: dict | None = None,
) -> dict:
    """Search for a dish by name and return full meal details with recipe.
    If stock_items provided, uses those ingredients preferentially."""
    from app.models.meal import MEAL_TYPE_LABELS
    meal_label = MEAL_TYPE_LABELS.get(meal_type, meal_type)

    is_stock_mode = stock_items is not None
    stock_section = ""
    if stock_items:
        stock_list = ", ".join(f"{s['nombre']} ({s['cantidad']} {s['unidad']})" for s in stock_items[:20])
        stock_section = f"\nIngredientes disponibles en stock: {stock_list}\n"

    intolerances = ""
    if profile and getattr(profile, "food_intolerances", None):
        intolerances = f"Evitar: {profile.food_intolerances}."

    import random
    seed_words = ["mediterráneo", "asiático", "clásico local", "fusión", "ligero", "proteico", "aromático"]
    direction = random.choice(seed_words)

    if is_stock_mode and stock_items:
        intro = f"El usuario tiene los siguientes ingredientes en su stock y quiere preparar su {meal_label} usándolos."
        instruction = f"Crea un plato CREATIVO y VARIADO ({direction}) usando PRINCIPALMENTE los ingredientes del stock listados arriba. Sorprende con algo diferente, no lo más obvio."
    elif is_stock_mode:
        intro = f"El usuario quiere preparar su {meal_label} con ingredientes básicos de despensa."
        instruction = f"Crea un plato nutritivo y CREATIVO ({direction}) con ingredientes comunes de despensa. Propón algo variado y apetecible."
    else:
        intro = f'El usuario busca el plato "{nombre}" para su {meal_label}.'
        instruction = "Genera la receta completa y auténtica de este plato buscándolo en tu conocimiento culinario."

    workout_section = _workout_meal_section(workout_context)
    meal_context = _meal_type_context(meal_type)

    prompt = f"""{intro}
{meal_context}
{intolerances}
{stock_section}
Objetivo calórico orientativo: ~{target_calories} kcal.
{workout_section}
{instruction}

CALCULA los valores nutricionales reales basándote en los ingredientes y cantidades que elijas — no copies el objetivo directamente.

Responde ÚNICAMENTE con JSON válido:
{{
  "tipo": "{meal_type}",
  "nombre": "Nombre del plato",
  "descripcion": "Descripción breve (máx 20 palabras)",
  "calorias": 0,
  "proteinas_g": 0.0,
  "carbohidratos_g": 0.0,
  "grasas_g": 0.0,
  "ingredientes": [
    {{"nombre": "Ingrediente", "cantidad": 100, "unidad": "g"}}
  ],
  "receta_detallada": "Paso 1: ...\\nPaso 2: ...\\nPaso 3: ..."
}}

Reemplaza los 0 con los valores nutricionales reales calculados.
Incluye 5-8 ingredientes con cantidades exactas y al menos 3 pasos de preparación.
País del usuario: {_country(profile)} — usa ingredientes y nombres típicos de ese país."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system="Eres un chef y nutricionista experto. Usa ortografía española correcta con tildes. Responde SOLO con JSON válido.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("buscar_plato_por_nombre", message)
    return _parse_json(message.content[0].text)


def generate_meal_for_recetario(profile, meal_type: str, description: str = "") -> dict:
    """Generate a single recipe for the recetario with AI. Returns a parsed meal dict."""
    from app.models.meal import MEAL_TYPE_LABELS

    dietary_map = {"omnivoro": "omnívoro", "vegetariano": "vegetariano", "vegano": "vegano", "pescetariano": "pescetariano"}
    dietary_label = dietary_map.get(getattr(profile, "dietary_type", "omnivoro"), "omnívoro")
    meal_label = MEAL_TYPE_LABELS.get(meal_type, meal_type)

    prefs_lines = []
    if getattr(profile, "food_intolerances", None):
        prefs_lines.append(f"- Alergias/intolerancias: {profile.food_intolerances}")
    if getattr(profile, "disliked_foods", None):
        prefs_lines.append(f"- Alimentos que NO le gustan: {profile.disliked_foods}")
    if getattr(profile, "preferred_foods", None):
        prefs_lines.append(f"- Alimentos favoritos: {profile.preferred_foods}")
    prefs_section = "\n".join(prefs_lines) if prefs_lines else "Sin restricciones adicionales"

    desc_line = f"Idea o descripción del usuario: {description}" if description else "Crea una receta original y variada."

    prompt = f"""Genera UNA receta de tipo "{meal_label}" para incluir en el recetario personal de un usuario.

Perfil del usuario:
- Dieta: {dietary_label}
- País: {_country(profile)}
{prefs_section}

{desc_line}

CALCULA los valores nutricionales reales basándote en los ingredientes y cantidades que elijas.

Responde ÚNICAMENTE con JSON válido:
{{
  "nombre": "Nombre del plato",
  "descripcion": "Descripción breve de preparación (máx 15 palabras)",
  "calorias": 0,
  "proteinas_g": 0.0,
  "carbohidratos_g": 0.0,
  "grasas_g": 0.0,
  "ingredientes": [
    {{"nombre": "Ingrediente", "cantidad": 100, "unidad": "g"}}
  ]
}}

Reemplaza los 0 con los valores nutricionales reales calculados.
Incluye 4-7 ingredientes con cantidades realistas. Usa nombres de ingredientes específicos y consistentes con el vocabulario local."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=800,
        system="Eres un chef y nutricionista experto. Responde SOLO con JSON válido, sin texto adicional.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("generate_meal_for_recetario", message)
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


def generate_cheat_meal(nombre: str, meal_type: str, profile=None) -> dict:
    """Generate nutritional info for any dish without calorie or meal-type restrictions.
    Used for the 'capricho' mode where the user logs what they actually ate."""
    intolerances = ""
    if profile and getattr(profile, "food_intolerances", None):
        intolerances = f"Nota alérgica: {profile.food_intolerances}.\n"

    prompt = f"""El usuario ha comido "{nombre}" y quiere registrar los valores nutricionales reales.
{intolerances}
Genera los valores nutricionales de UNA PORCIÓN TÍPICA de "{nombre}" tal como se sirve normalmente.
NO adaptes las calorías a ningún objetivo dietético — usa los valores reales del plato estándar.

Responde ÚNICAMENTE con JSON válido:
{{
  "tipo": "{meal_type}",
  "nombre": "Nombre del plato",
  "descripcion": "Descripción breve (máx 15 palabras)",
  "calorias": 0,
  "proteinas_g": 0.0,
  "carbohidratos_g": 0.0,
  "grasas_g": 0.0,
  "ingredientes": [
    {{"nombre": "Ingrediente", "cantidad": 100, "unidad": "g"}}
  ]
}}

Calcula los valores reales para una porción estándar. Incluye 4-8 ingredientes.
País del usuario: {_country(profile)} — usa ingredientes y nombres típicos de ese país."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=800,
        system="Eres un nutricionista experto. Usa ortografía española correcta con tildes. Responde SOLO con JSON válido.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("generate_cheat_meal", message)
    return _parse_json(message.content[0].text)


def generate_goal_description(profile, user_description: str) -> str:
    """Refine the user's free-text goal into a clear, actionable objective for meal plan generation."""
    profile_ctx = ""
    if profile:
        try:
            from app.services.nutrition import calculate_bmr, calculate_tdee, get_activity_days_list
            bmr = calculate_bmr(profile)
            n_days = len(get_activity_days_list(profile))
            tdee = calculate_tdee(bmr, n_days)
            profile_ctx = (
                f"\nDatos del usuario: {profile.age} años, {profile.gender}, "
                f"{profile.weight_kg} kg, {profile.height_cm} cm. "
                f"TMB {round(bmr)} kcal, TDEE {round(tdee)} kcal, {n_days} días/semana de entrenamiento."
            )
        except Exception:
            pass

    prompt = (
        f"El usuario quiere personalizar su objetivo nutricional y ha escrito:\n\n"
        f"\"{user_description}\"\n"
        f"{profile_ctx}\n\n"
        "Transforma esto en una descripción concisa (2-4 frases) y precisa para generar su plan de comidas personalizado. "
        "Incluye: objetivo principal, contexto relevante (eventos, plazos, limitaciones) y cualquier preferencia mencionada. "
        "Responde SOLO con la descripción mejorada, sin introducción ni explicaciones."
    )
    client = _get_client()
    message = client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=350,
        system="Eres nutricionista. Conviertes descripciones informales de objetivos en texto claro y útil para generar planes alimenticios personalizados. Usa siempre ortografía española correcta con tildes y puntuación.",
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage("generate_goal_description", message)
    return message.content[0].text.strip()
