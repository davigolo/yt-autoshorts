import json
import os
from dataclasses import dataclass

from google import genai

PROMPT = """Eres guionista de un canal de YouTube Shorts sobre {niche}.
Idioma: {language}. Audiencia: {audience}.

Escribe el guion de UN short nuevo de unos {target_words} palabras (~40-50 segundos narrado).
Reglas:
- Empieza con un gancho potente en la primera frase.
- Datos verídicos y comprobables; nada inventado.
- Texto solo para narrar: sin emojis, sin acotaciones, sin hashtags.
- Termina invitando a seguir el canal en una frase corta.
- NO repitas ninguno de estos temas ya publicados: {history}

Devuelve SOLO JSON con esta forma:
{{
  "topic": "tema en 3-6 palabras",
  "title": "título atractivo de máximo 70 caracteres",
  "description": "descripción de 2-3 frases",
  "tags": ["5 a 10 etiquetas"],
  "narration": "texto completo a narrar",
  "search_terms": ["{clips} términos EN INGLÉS, concretos y visuales, para buscar vídeos de stock, en orden de aparición"]
}}"""


@dataclass
class Script:
    topic: str
    title: str
    description: str
    tags: list[str]
    narration: str
    search_terms: list[str]


def generate_script(config: dict, history: list[str]) -> Script:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = PROMPT.format(
        **config["channel"],
        target_words=config["script"]["target_words"],
        clips=config["video"]["clips"],
        history="; ".join(history[-200:]) or "ninguno",
    )
    response = client.models.generate_content(
        model=config["script"]["model"],
        contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 1.0},
    )
    data = json.loads(response.text)
    return Script(
        topic=data["topic"],
        title=data["title"][:95],
        description=data["description"],
        tags=data["tags"][:15],
        narration=data["narration"],
        search_terms=data["search_terms"],
    )
