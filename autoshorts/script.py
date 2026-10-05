import json
import os
import random
import time
from dataclasses import dataclass

from google import genai
from google.genai import errors

FORMATS = {
    "dato": "Un único dato sorprendente explicado de forma rápida y visual.",
    "mito": "Formato 'mito o verdad': plantea una creencia popular y revela si es cierta.",
    "top3": "Formato 'top 3': tres datos muy breves y encadenados sobre un mismo tema, del menos al más sorprendente.",
    "que_pasaria": "Formato '¿qué pasaría si...?': un escenario hipotético explicado con ciencia real.",
    "reto": "Formato reto: plantea una pregunta al espectador, deja un instante para pensar y revela la respuesta.",
}

PROMPT = """Eres guionista de un canal de YouTube Shorts sobre {niche}.
Idioma: {language}. Audiencia: {audience}.
Formato de hoy: {format_rule}

Escribe el guion de UN short nuevo de {target_words} palabras como máximo (25-35 segundos narrado).
Objetivo: que el espectador lo vea entero y lo repita.
Reglas:
- La primera frase es el gancho: impactante, concreta, sin saludos ni introducciones. Debe abrir una pregunta en la mente del espectador.
- NUNCA reveles la respuesta, el desenlace o el dato clave en el gancho ni en la primera mitad: da contexto y pistas, sube la tensión y revela la respuesta en el último tercio.
- Frases cortas, ritmo rápido, lenguaje sencillo. Español neutro, entendible igual en España y Latinoamérica (nada de "vosotros" ni modismos locales).
- Datos verídicos y comprobables; nada inventado ni exagerado.
- Texto solo para narrar: sin emojis, sin acotaciones, sin hashtags.
- NO pidas suscripciones ni likes.
- La última frase debe enlazar de forma natural con la primera, para que al repetirse el vídeo parezca continuo.
- NO repitas ninguno de estos temas ya publicados: {history}
- Divide la narración en {scenes} escenas en orden; al unir el "text" de todas las escenas debe salir la narración completa, palabra por palabra.
- Cada escena debe mostrar exactamente lo que se dice en ella. Para personajes históricos, objetos, lugares, animales o fósiles concretos rellena "wiki" con su artículo (p. ej. 'Cleopatra', 'Gjermundbu helmet', 'Tyrannosaurus'). La primera escena es el gancho y debe enseñar el sujeto del vídeo de forma reconocible.

{insights}

Devuelve SOLO JSON con esta forma:
{{
  "topic": "tema en 3-6 palabras",
  "hook_text": "texto para mostrar en pantalla el primer segundo, máximo 5 palabras, que genere curiosidad SIN dar la respuesta",
  "title": "título con curiosidad y sin clickbait falso, máximo 60 caracteres",
  "description": "descripción de 1-2 frases",
  "tags": ["5 a 10 etiquetas"],
  "scenes": [
    {{
      "text": "fragmento EXACTO de la narración que se oye en esta escena (una frase o media)",
      "subject": "en inglés, qué tiene que verse literalmente en pantalla mientras se dice ese fragmento (p. ej. 'Viking iron helmet in a museum')",
      "wiki": "título EXACTO de un artículo de la Wikipedia en inglés cuya foto principal muestre ese sujeto, o null si no existe",
      "stock": "1-3 palabras en inglés para buscar un vídeo de stock que muestre ese sujeto"
    }}
  ]
}}"""


FACT_CHECK_PROMPT = """Eres verificador de datos de un canal de divulgación. Revisa este guion de un short en {language}.
Busca cualquier afirmación falsa, imprecisa, exagerada o sensacionalista (por ejemplo, decir que un animal "puede vivir
en el espacio" cuando solo sobrevive un tiempo en estado latente, cifras redondeadas de más, mitos presentados como
hechos o fechas dudosas). Corrígelas con la versión exacta y comprobable, manteniendo el tono, la longitud, el gancho
sin revelar la respuesta y la misma estructura de escenas. Aplica el mismo rigor a "title", "hook_text" y "description":
si prometen algo que el vídeo no cumple o exageran, ajústalos. Si todo es correcto, devuélvelo igual.

Guion:
{script}

Devuelve SOLO JSON con exactamente la misma forma que el guion recibido y un campo extra
"corrections": ["lista breve de lo que has cambiado y por qué; vacía si nada"]."""


@dataclass
class Scene:
    text: str
    subject: str
    wiki: str | None
    stock: str


@dataclass
class Script:
    topic: str
    format: str
    hook_text: str
    title: str
    description: str
    tags: list[str]
    scenes: list[Scene]

    @property
    def narration(self) -> str:
        return " ".join(scene.text.strip() for scene in self.scenes)


RETRYABLE_CODES = {404, 429, 500, 503}


def generate_json(contents, models: list[str], rounds: int = 5) -> dict | list:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    last_error: Exception | None = None
    for attempt in range(rounds):
        for model in models:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config={"response_mime_type": "application/json", "temperature": 1.0},
                )
                data, _ = json.JSONDecoder().raw_decode(response.text.strip())
                print(f"Respuesta generada con {model}")
                return data
            except errors.APIError as e:
                if e.code not in RETRYABLE_CODES:
                    raise
                print(f"{model} no disponible ({e.code}), probando otro")
                last_error = e
            except (json.JSONDecodeError, TypeError) as e:
                print(f"{model} devolvió JSON inválido ({e}), probando otro")
                last_error = e
        time.sleep(30 * (attempt + 1))
    raise RuntimeError("Ningún modelo de Gemini disponible") from last_error


def _pick_format(recent_formats: list[str], weights: dict[str, float]) -> str:
    options = [f for f in FORMATS if f not in recent_formats[-2:]] or list(FORMATS)
    return random.choices(options, weights=[weights.get(f, 1.0) for f in options])[0]


def _fact_check(data: dict, config: dict) -> dict:
    try:
        checked = generate_json(
            FACT_CHECK_PROMPT.format(language=config["channel"]["language"], script=json.dumps(data, ensure_ascii=False)),
            config["script"]["models"],
        )
        if isinstance(checked, list):
            checked = checked[0]
        if not checked.get("scenes") or not all(s.get("text") for s in checked["scenes"]):
            raise ValueError("verificación sin escenas")
    except Exception as e:
        print(f"Verificación de datos no disponible ({type(e).__name__}: {e}); se usa el guion original")
        return data
    for correction in checked.get("corrections") or []:
        print(f"Corrección: {correction}")
    return {**data, **{k: checked[k] for k in ("title", "hook_text", "description", "scenes") if checked.get(k)}}


def generate_script(config: dict, history: list[dict], insights: str = "", weights: dict[str, float] | None = None) -> Script:
    video_format = _pick_format([h.get("format", "") for h in history], weights or {})
    prompt = PROMPT.format(
        **config["channel"],
        format_rule=FORMATS[video_format],
        insights=insights,
        target_words=config["script"]["target_words"],
        scenes=config["video"]["scenes"],
        history="; ".join(h["topic"] for h in history[-200:]) or "ninguno",
    )
    data = generate_json(prompt, config["script"]["models"])
    if isinstance(data, list):
        data = data[0]
    data = _fact_check(data, config)
    return Script(
        topic=data["topic"],
        format=video_format,
        hook_text=data["hook_text"],
        title=data["title"][:95],
        description=data["description"],
        tags=data["tags"][:15],
        scenes=[
            Scene(text=s["text"], subject=s["subject"], wiki=s.get("wiki") or None, stock=s["stock"])
            for s in data["scenes"] if s.get("text", "").strip()
        ],
    )
