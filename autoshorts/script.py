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
- La primera frase es el gancho: impactante, concreta, sin saludos ni introducciones.
- Frases cortas, ritmo rápido, lenguaje sencillo.
- Datos verídicos y comprobables; nada inventado ni exagerado.
- Texto solo para narrar: sin emojis, sin acotaciones, sin hashtags.
- NO pidas suscripciones ni likes.
- La última frase debe enlazar de forma natural con la primera, para que al repetirse el vídeo parezca continuo.
- NO repitas ninguno de estos temas ya publicados: {history}

{insights}

Devuelve SOLO JSON con esta forma:
{{
  "topic": "tema en 3-6 palabras",
  "hook_text": "texto para mostrar en pantalla el primer segundo, máximo 5 palabras, que genere curiosidad",
  "title": "título con curiosidad y sin clickbait falso, máximo 60 caracteres",
  "description": "descripción de 1-2 frases",
  "tags": ["5 a 10 etiquetas"],
  "narration": "texto completo a narrar",
  "search_terms": ["{clips} términos EN INGLÉS, concretos y visuales, para buscar vídeos de stock, en orden de aparición"]
}}"""


@dataclass
class Script:
    topic: str
    format: str
    hook_text: str
    title: str
    description: str
    tags: list[str]
    narration: str
    search_terms: list[str]


RETRYABLE_CODES = {404, 429, 500, 503}


def _generate(client: genai.Client, models: list[str], prompt: str, rounds: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(rounds):
        for model in models:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={"response_mime_type": "application/json", "temperature": 1.0},
                )
                print(f"Guion generado con {model}")
                return response.text
            except errors.APIError as e:
                if e.code not in RETRYABLE_CODES:
                    raise
                print(f"{model} no disponible ({e.code}), probando otro")
                last_error = e
        time.sleep(30 * (attempt + 1))
    raise RuntimeError("Ningún modelo de Gemini disponible") from last_error


def _pick_format(recent_formats: list[str], weights: dict[str, float]) -> str:
    options = [f for f in FORMATS if f not in recent_formats[-2:]] or list(FORMATS)
    return random.choices(options, weights=[weights.get(f, 1.0) for f in options])[0]


def generate_script(config: dict, history: list[dict], insights: str = "", weights: dict[str, float] | None = None) -> Script:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    video_format = _pick_format([h.get("format", "") for h in history], weights or {})
    prompt = PROMPT.format(
        **config["channel"],
        format_rule=FORMATS[video_format],
        insights=insights,
        target_words=config["script"]["target_words"],
        clips=config["video"]["clips"],
        history="; ".join(h["topic"] for h in history[-200:]) or "ninguno",
    )
    data = json.loads(_generate(client, config["script"]["models"], prompt))
    return Script(
        topic=data["topic"],
        format=video_format,
        hook_text=data["hook_text"],
        title=data["title"][:95],
        description=data["description"],
        tags=data["tags"][:15],
        narration=data["narration"],
        search_terms=data["search_terms"],
    )
