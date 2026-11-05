import json
import os
import random
import time
from dataclasses import dataclass

from google import genai
from google.genai import errors

FORMATS = {
    "dato": (
        "Show one packaging feature, state the problem it solves, then explain its mechanism. "
        "Open with a concrete, surprising statement about the visible object, not a generic curiosity."
    ),
    "mito": (
        "Correct one documented misconception about one packaging feature. Do not invent a popular belief. "
        "Contrast the visible feature with its real purpose using a concrete explanation."
    ),
    "que_pasaria": (
        "Explain what would change if one specific packaging feature were missing. Stay with the same object "
        "and a technically supported consequence; no imaginary disasters or invented experiments."
    ),
}

VISUAL_SEARCH_PROMPT = """Plan a visual search for one packaging-engineering Short.
Editorial brief: {editorial_brief}
Candidate subjects: {topic_seeds}
Excluded topics: {history}

Choose one unused packaging feature that is easy to show in existing photographs.
Prefer visible cardboard layers, folds, bottle ribs, caps or resealable bag profiles.
Avoid rare macro shots, invisible forces and hypothetical damage.
Return three different broad English search queries for this SAME object, each 1-3 words.
These queries retrieve real images BEFORE the script is written; do not write narration yet.
Return ONLY JSON:
{{"topic": "specific object and feature", "searches": [
  {{"subject": "visible object", "stock": "broad object query", "wiki": "English Wikipedia article or null"}}
]}}"""

AVAILABLE_VISUALS_RULE = """
The attached images are the ONLY available visuals. Write the script around what they actually show.
Choose ONE clearly visible packaging feature from this inventory, not a feature you hope to find later.
Each scene MUST include "visual_id" with an exact inventory ID. Reuse a correct image across scenes.
Do not request new images, hidden parts, animations or experiments. The first image must show the feature.
Narration may explain an invisible mechanism over an honest exterior image, but must not claim it is visible.
If no image supports an unused topic within the editorial brief, return
{"rejected": true, "reason": "No suitable unused packaging feature in the available images"}.
"""

PROMPT = """Write for a YouTube Shorts channel about {niche}.
Output language: {language}. Audience: {audience}.
Editorial brief: {editorial_brief}
Today's format: {format_rule}
Candidate subjects, not verified claims: {topic_seeds}

Write ONE new Short with at most {target_words} narrated words (about 30-40 seconds).
Rules:
- Stay within packaging engineering. Explain ONE feature of ONE object, not a list.
- Open immediately with the recognizable object and a concrete visual puzzle.
- No greetings, "did you know", quizzes, requests for likes or subscriptions.
- Give useful information from the beginning. Do not withhold the explanation with filler or artificial suspense.
- Explain the mechanism and its practical consequence. A clear causal explanation is the payoff.
- Use short sentences and neutral Spanish. One brief personal observation is welcome, but never invent experience.
- Never invent measurements, experiments, safety guarantees, statistics, historical claims or sources.
- State qualifications when a design depends on the material, manufacturer or type of packaging.
- Do not repeat these previously published topics, even using a different title: {history}
- Divide the full narration into exactly {scenes} non-empty scenes, in order.
- Every scene must name the precise visible object or feature in English. Use realistic close-ups or diagrams
  that can be found on Wikimedia or stock libraries. Never request imaginary cutaways, fake experiments,
  generic factories, unrelated nature clips or a different packaging mechanism.
- Build the visual plan around readily photographed parts. Several scenes may show the same accurate exterior
  or cross-section while the narration explains it. Do not demand invisible gas, microscopic materials or
  disassembled internal components unless a real, publicly available diagram can show them.
- For an invisible force or hypothetical failure, show an honest exterior view of this same packaging feature.
  Never require a photo of a hypothetical event. Use short object names, not full sentences, for stock queries.
- The first scene must show the exact feature, large and recognizable. Prefer a relevant moving shot,
  but an accurate still image or diagram is better than an unrelated video.
- Use English Wikipedia article titles only when their images actually show that subject; otherwise use null.
- The title, on-screen hook, thumbnail and description must promise only what the narration explains.
- End with the practical meaning of the explanation or a natural loop, not an unrelated teaser.

{insights}

Return ONLY JSON with this shape. Viewer-facing strings must be in {language}:
{{
  "topic": "specific object and feature, 3-6 words",
  "hook_text": "name the object or feature and create curiosity in at most 5 words",
  "title": "specific, accurate and interesting title, at most 60 characters",
  "description": "2-3 sentences summarizing the actual explanation with relevant search terms",
  "tags": ["8-12 specific packaging and mechanism search terms"],
  "playlist": "exactly one of: {playlists}",
  "hashtags": ["3-5 specific hashtags without # or spaces"],
  "thumbnail_text": "2-4 concrete words about the same object and visual puzzle",
  "scenes": [
    {{
      "text": "exact narration for this scene",
      "subject": "precise visible object or feature, in English",
      "wiki": "exact English Wikipedia article title, or null",
      "stock": "1-4 English words describing the exact packaging object or action",
      "label": "optional 1-3 word explanatory label in the output language, or null"
    }}
  ]
}}"""


FACT_CHECK_PROMPT = """Review this packaging-engineering Short in {language}.
Editorial brief: {editorial_brief}
Check the technical explanation, material, pressure, sealing, manufacturing and preservation claims.
Remove unsupported numbers, invented tests, false universal claims and misleading safety promises.
Keep one object and one mechanism, at most {target_words} narrated words and exactly {scenes} scenes.
Make the title, hook, description and thumbnail accurate to the actual narration.
Every visual subject and search query must still match its corrected narration.
Rewrite unfilmable visual subjects as honest exterior views of the same packaging feature. Describing internal
pressure does not require a photograph of gas; explaining a hypothetical failure does not require fake damage.
This is a model review, not external source verification: never claim that sources were checked.
If the topic is outside the brief or its central explanation cannot be supported, return
{{"rejected": true, "reason": "specific reason"}} instead of inventing a replacement.

Script:
{script}

Otherwise return ONLY JSON with the same shape and an extra
"corrections": ["brief explanations of corrections, or an empty list"]."""


@dataclass
class Scene:
    text: str
    subject: str
    wiki: str | None
    stock: str
    label: str | None = None
    visual_id: str | None = None


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


def generate_visual_searches(config: dict, history: list[dict]) -> tuple[str, list[Scene]]:
    data = generate_json(
        VISUAL_SEARCH_PROMPT.format(
            editorial_brief=config["channel"]["editorial_brief"],
            topic_seeds="; ".join(config["script"]["topic_seeds"]),
            history="; ".join(h["topic"] for h in history[-200:]) or "none",
        ),
        config["script"]["models"],
    )
    if not isinstance(data, dict) or not isinstance(data.get("topic"), str) or not data["topic"].strip():
        raise ValueError("Plan de búsqueda visual sin tema válido")
    searches = data.get("searches")
    if not isinstance(searches, list) or len(searches) != 3:
        raise ValueError("El plan visual debe contener tres búsquedas")
    scenes = []
    for search in searches:
        if not isinstance(search, dict) or not isinstance(search.get("stock"), str) or not 1 <= len(search["stock"].split()) <= 3:
            raise ValueError("Consulta de búsqueda visual inválida")
        if not isinstance(search.get("subject"), str) or not search["subject"].strip():
            raise ValueError("Búsqueda visual sin objeto válido")
        scenes.append(Scene(text="", subject=search["subject"], stock=search["stock"], wiki=search.get("wiki") or None))
    return data["topic"], scenes


def _fact_check(data: dict, config: dict, visual_contents: list | None = None) -> dict:
    prompt = FACT_CHECK_PROMPT.format(
        language=config["channel"]["language"],
        editorial_brief=config["channel"]["editorial_brief"],
        target_words=config["script"]["target_words"],
        scenes=config["video"]["scenes"],
        script=json.dumps(data, ensure_ascii=False),
    )
    contents = [prompt, AVAILABLE_VISUALS_RULE, *visual_contents] if visual_contents is not None else prompt
    checked = generate_json(
        contents,
        config["script"]["models"],
    )
    if isinstance(checked, list):
        checked = checked[0]
    if checked.get("rejected"):
        raise ValueError(f"Guion rechazado: {checked.get('reason', 'sin explicación')}")
    if not checked.get("scenes") or not all(s.get("text", "").strip() for s in checked["scenes"]):
        raise ValueError("Revisión del guion sin escenas válidas")
    for correction in checked.get("corrections") or []:
        print(f"Corrección: {correction}")
    return {**data, **checked}


def generate_script(
    config: dict, history: list[dict], insights: str = "", weights: dict[str, float] | None = None,
    visual_contents: list | None = None,
) -> Script:
    strategy = config["channel"]["strategy"]
    recent = [h for h in history if h.get("strategy") == strategy]
    video_format = _pick_format([h.get("format", "") for h in recent], weights or {})
    playlists = list(config.get("playlists", {}))
    prompt = PROMPT.format(
        **config["channel"],
        format_rule=FORMATS[video_format],
        insights=insights,
        target_words=config["script"]["target_words"],
        scenes=config["video"]["scenes"],
        topic_seeds="; ".join(config["script"]["topic_seeds"]),
        history="; ".join(h["topic"] for h in history[-200:]) or "ninguno",
        playlists=", ".join(playlists),
    )
    contents = [prompt, AVAILABLE_VISUALS_RULE, *visual_contents] if visual_contents is not None else prompt
    data = generate_json(contents, config["script"]["models"])
    if isinstance(data, list):
        data = data[0]
    if data.get("rejected"):
        raise ValueError(f"Guion rechazado: {data.get('reason', 'sin explicación')}")
    data = _fact_check(data, config, visual_contents)
    if data.get("playlist") not in playlists:
        raise ValueError("El guion no pertenece a una lista de la estrategia actual")
    if len(data["scenes"]) != config["video"]["scenes"]:
        raise ValueError("El guion no tiene el número de escenas configurado")
    if visual_contents is not None and not all(isinstance(s.get("visual_id"), str) and s["visual_id"] for s in data["scenes"]):
        raise ValueError("El guion no asigna una imagen disponible a cada escena")
    narration = " ".join(s["text"].strip() for s in data["scenes"])
    if len(narration.split()) > config["script"]["target_words"]:
        raise ValueError("El guion supera el máximo de palabras configurado")
    return Script(
        topic=data["topic"],
        format=video_format,
        hook_text=data["hook_text"],
        title=data["title"][:95],
        description=data["description"],
        tags=data["tags"][:15],
        scenes=[
            Scene(
                text=s["text"], subject=s["subject"], wiki=s.get("wiki") or None, stock=s["stock"],
                label=s.get("label") or None, visual_id=s.get("visual_id"),
            )
            for s in data["scenes"] if s.get("text", "").strip()
        ],
        hashtags=[str(h) for h in data.get("hashtags", [])][:5],
        thumbnail_text=data.get("thumbnail_text") or data["hook_text"],
        playlist=data.get("playlist") if data.get("playlist") in playlists else None,
    )
