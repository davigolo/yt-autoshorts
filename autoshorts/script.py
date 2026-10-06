import json
import os
import random
import time
from dataclasses import dataclass

from google import genai
from google.genai import errors

FORMATS = {
    "dato": (
        "Un único dato sorprendente. Primera frase: una afirmación concreta que plantea el misterio sin resolverlo "
        "(p. ej. 'Todos saben que las pelotas de balonmano son pegajosas, pero casi nadie imagina cuánto.')."
    ),
    "mito": (
        "Mito o verdad. Primera frase: 'Todo el mundo cree que...' o similar, afirmando la creencia popular con "
        "seguridad; después se desmonta con pruebas."
    ),
    "top3": (
        "Cuenta atrás de 3. Primera frase: 'Tres [cosas] que [lo sorprendente]. Número tres: ...' y se entra ya en el "
        "primero sin introducción; del menos al más sorprendente. Rellena 'label' con 'NÚMERO 3', 'NÚMERO 2' y "
        "'NÚMERO 1' en la escena donde empieza cada uno."
    ),
    "que_pasaria": (
        "'¿Qué pasaría si...?' contado por etapas. Primera frase: la pregunta del escenario y, sin pausa, la primera "
        "etapa ('Segundo 1.', 'Día 1.', 'Año 1.'). Cada etapa escala la consecuencia con ciencia real. Rellena 'label' "
        "con la etapa ('SEGUNDO 1', 'DÍA 3', 'AÑO 100') en la escena donde empieza."
    ),
    "historia": (
        "Historia real que arranca en mitad de la acción. Primera frase: alguien haciendo algo concreto "
        "('En 1965, un científico soviético encerró a...', 'Un músico golpeó un gong bajo el agua y...'); el porqué "
        "se revela al final."
    ),
}

PROMPT = """Eres guionista de un canal de YouTube Shorts sobre {niche}.
Idioma: {language}. Audiencia: {audience}.
Formato de hoy: {format_rule}

Escribe el guion de UN short nuevo de {target_words} palabras como máximo (30-40 segundos narrado).
Objetivo: que el espectador NO deslice en el primer segundo, lo vea entero y lo repita.
Reglas:
- La primera frase es el gancho y sigue el formato de hoy: arranca directamente en el tema o en mitad de la acción, sin
  saludos ni introducciones, y abre una pregunta en la mente del espectador.
- PROHIBIDO empezar preguntando al espectador ("¿Sabías que...?", "¿Cuánto crees que...?", "¿Qué es más...?", "Adivina...").
  La única pregunta inicial permitida es la del formato "¿Qué pasaría si...?".
- NUNCA reveles la respuesta, el desenlace o el dato clave en el gancho ni en la primera mitad: da contexto y pistas, sube la tensión y revela la respuesta en el último tercio.
- Frases cortas, ritmo rápido, lenguaje sencillo. Español neutro, entendible igual en España y Latinoamérica (nada de "vosotros" ni modismos locales).
- Datos verídicos y comprobables; nada inventado ni exagerado.
- Texto solo para narrar: sin emojis, sin acotaciones, sin hashtags.
- NO pidas suscripciones ni likes.
- La última frase debe enlazar de forma natural con la primera, para que al repetirse el vídeo parezca continuo.
- NO repitas ninguno de estos temas ya publicados: {history}
- Divide la narración en {scenes} escenas en orden; al unir el "text" de todas las escenas debe salir la narración completa, palabra por palabra.
- Cada escena debe mostrar exactamente lo que se dice en ella. Para personajes históricos, objetos, lugares, animales o fósiles concretos rellena "wiki" con su artículo (p. ej. 'Cleopatra', 'Gjermundbu helmet', 'Tyrannosaurus').
- La primera escena es el gancho: debe enseñar el sujeto del vídeo grande, reconocible y EN MOVIMIENTO desde el primer
  fotograma (algo pasando: un animal atacando, una explosión, alguien haciendo algo). Su "stock" describe esa acción
  (p. ej. 'shark jumping out of water', 'volcano eruption lava') y su "wiki" es null salvo que no exista vídeo posible.

{insights}

Devuelve SOLO JSON con esta forma:
{{
  "topic": "tema en 3-6 palabras",
  "hook_text": "título grande en pantalla durante los primeros segundos, máximo 5 palabras, que nombre el sujeto y genere curiosidad SIN dar la respuesta (p. ej. 'BURRO + YEGUA', 'EL MÉTODO SOVIÉTICO PROHIBIDO'); nunca una pregunta al espectador",
  "title": "título con curiosidad y sin clickbait falso, máximo 60 caracteres",
  "description": "descripción de 2-3 frases que resuma el tema sin revelar la respuesta e incluya de forma natural las palabras clave que alguien buscaría en YouTube",
  "tags": ["8 a 12 etiquetas: tema concreto, nombres propios y búsquedas relacionadas"],
  "playlist": "lista de reproducción del canal a la que pertenece el tema, exactamente una de: {playlists}",
  "hashtags": ["3 a 5 hashtags en español específicos del tema (p. ej. 'tardigrados', 'espacio', 'animalesextremos'), sin el símbolo #, sin espacios"],
  "thumbnail_text": "2-4 palabras impactantes para la miniatura. Debe plantear la pregunta o el misterio, NUNCA la respuesta, la cifra clave ni el desenlace del vídeo (bien: '¿CUÁNTO PESA UNA NUBE?', 'NADIE LO ESPERABA'; mal: 'PESA 100 ELEFANTES')",
  "scenes": [
    {{
      "text": "fragmento EXACTO de la narración que se oye en esta escena (una frase o media)",
      "subject": "en inglés, qué tiene que verse literalmente en pantalla mientras se dice ese fragmento (p. ej. 'Viking iron helmet in a museum')",
      "wiki": "título EXACTO de un artículo de la Wikipedia en inglés cuya foto principal muestre ese sujeto, o null si no existe",
      "stock": "1-4 palabras en inglés para buscar un vídeo de stock que muestre ese sujeto en acción",
      "label": "rótulo grande de 1-3 palabras para la etapa o número que empieza en esta escena, o null"
    }}
  ]
}}"""


FACT_CHECK_PROMPT = """Eres verificador de datos de un canal de divulgación. Revisa este guion de un short en {language}.
Busca cualquier afirmación falsa, imprecisa, exagerada o sensacionalista (por ejemplo, decir que un animal "puede vivir
en el espacio" cuando solo sobrevive un tiempo en estado latente, cifras redondeadas de más, mitos presentados como
hechos o fechas dudosas). Corrígelas con la versión exacta y comprobable, manteniendo el tono, la longitud, el gancho
sin revelar la respuesta y la misma estructura de escenas (incluidos "stock" y "label"). Aplica el mismo rigor a "title", "hook_text" y "description":
si prometen algo que el vídeo no cumple o exageran, ajústalos. "hook_text" y "thumbnail_text" NUNCA pueden revelar la
respuesta, la cifra clave ni el desenlace: si lo hacen, reescríbelos como misterio. "hook_text" nunca es una pregunta al espectador. Si todo es correcto, devuélvelo igual.

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
    label: str | None = None


@dataclass
class Script:
    topic: str
    format: str
    hook_text: str
    title: str
    description: str
    tags: list[str]
    scenes: list[Scene]
    hashtags: list[str]
    thumbnail_text: str
    playlist: str | None

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
    return {**data, **{k: checked[k] for k in ("title", "hook_text", "description", "thumbnail_text", "scenes") if checked.get(k)}}


def generate_script(config: dict, history: list[dict], insights: str = "", weights: dict[str, float] | None = None) -> Script:
    video_format = _pick_format([h.get("format", "") for h in history], weights or {})
    playlists = list(config.get("playlists", {}))
    prompt = PROMPT.format(
        **config["channel"],
        format_rule=FORMATS[video_format],
        insights=insights,
        target_words=config["script"]["target_words"],
        scenes=config["video"]["scenes"],
        history="; ".join(h["topic"] for h in history[-200:]) or "ninguno",
        playlists=", ".join(playlists),
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
            Scene(text=s["text"], subject=s["subject"], wiki=s.get("wiki") or None, stock=s["stock"], label=s.get("label") or None)
            for s in data["scenes"] if s.get("text", "").strip()
        ],
        hashtags=[str(h) for h in data.get("hashtags", [])][:5],
        thumbnail_text=data.get("thumbnail_text") or data["hook_text"],
        playlist=data.get("playlist") if data.get("playlist") in playlists else None,
    )
