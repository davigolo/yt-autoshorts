import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import requests
from google.genai import types

from autoshorts.script import Scene, generate_json

PEXELS_URL = "https://api.pexels.com/videos/search"
WIKI_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKI_HEADERS = {"User-Agent": "yt-autoshorts/1.0 (https://github.com/davigolo/yt-autoshorts)"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MIN_IMAGE_SIDE = 600
PEXELS_PER_SCENE = 3
COMMONS_PER_SCENE = 2

PICK_PROMPT = """Eres editor de vídeo de un short de curiosidades. Para cada escena tienes varias imágenes candidatas
(miniaturas de fotos o de vídeos de stock). Elige para cada escena la candidata que mejor muestre lo que se dice en
la narración de esa escena o el sujeto indicado.
- Valen fotos, cuadros, ilustraciones históricas, grabados, diagramas, retratos o vídeos, siempre que representen
  lo narrado o el personaje, objeto, lugar o fenómeno que se menciona.
- Entre varias válidas, prefiere la más clara y llamativa, y un vídeo si muestra de verdad lo narrado.
- Responde null SOLO si ninguna candidata tiene relación con lo narrado (por ejemplo, una calle cualquiera, una
  persona disfrazada o un objeto distinto al que se nombra).

Escenas:
{scenes}

Devuelve SOLO JSON: {{"choices": [id de la candidata elegida o null, una por escena y en orden]}}"""


@dataclass
class Candidate:
    id: str
    scene: int
    kind: str
    thumb_url: str
    url: str
    duration: float = 0.0


def _get(url: str, params: dict, headers: dict | None = None) -> dict:
    response = requests.get(url, params=params, headers=headers or WIKI_HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def _image_ok(url: str, width: int, height: int) -> bool:
    return Path(url.split("?")[0]).suffix.lower() in IMAGE_EXTENSIONS and min(width, height) >= MIN_IMAGE_SIDE


def _wiki_candidates(scene: Scene, index: int) -> list[Candidate]:
    if not scene.wiki:
        return []
    data = _get(WIKI_API, {
        "action": "query", "format": "json", "titles": scene.wiki, "redirects": 1,
        "prop": "pageimages", "piprop": "thumbnail|original", "pithumbsize": 1600,
    })
    out = []
    for page in data.get("query", {}).get("pages", {}).values():
        thumb, original = page.get("thumbnail"), page.get("original")
        if thumb and original and _image_ok(original["source"], thumb["width"], thumb["height"]):
            out.append(Candidate(f"w{index}", index, "image", thumb["source"], thumb["source"]))
    return out


def _commons_candidates(scene: Scene, index: int) -> list[Candidate]:
    data = _get(COMMONS_API, {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{scene.subject} filetype:bitmap", "gsrlimit": 6,
        "prop": "imageinfo", "iiprop": "url|size", "iiurlwidth": 1600,
    })
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    out = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("thumburl") and _image_ok(info["url"], info.get("width", 0), info.get("height", 0)):
            out.append(Candidate(f"c{index}_{len(out)}", index, "image", info["thumburl"], info["thumburl"]))
        if len(out) >= COMMONS_PER_SCENE:
            break
    return out


def _best_file(video: dict, min_height: int) -> str | None:
    files = [f for f in video["video_files"] if f.get("height") and f["height"] >= f.get("width", 0)]
    if not files:
        return None
    good = [f for f in files if f["height"] >= min_height] or files
    return min(good, key=lambda f: f["height"])["link"]


def _pexels_candidates(scene: Scene, index: int, min_height: int, used: set[int]) -> list[Candidate]:
    data = _get(
        PEXELS_URL,
        {"query": scene.stock, "orientation": "portrait", "per_page": 15, "size": "medium"},
        {"Authorization": os.environ["PEXELS_API_KEY"]},
    )
    out = []
    for video in data.get("videos", []):
        if video["id"] in used or not 3 <= video["duration"] <= 60:
            continue
        link = _best_file(video, min_height)
        if link and video.get("image"):
            used.add(video["id"])
            out.append(Candidate(f"p{index}_{len(out)}", index, "video", video["image"], link, video["duration"]))
        if len(out) >= PEXELS_PER_SCENE:
            break
    return out


def _collect(scenes: list[Scene], min_height: int) -> list[list[Candidate]]:
    used: set[int] = set()
    per_scene = []
    for i, scene in enumerate(scenes):
        found: list[Candidate] = []
        for source in (
            lambda: _wiki_candidates(scene, i),
            lambda: _commons_candidates(scene, i),
            lambda: _pexels_candidates(scene, i, min_height, used),
        ):
            try:
                found += source()
            except requests.RequestException as e:
                print(f"Búsqueda fallida en escena {i} ({e})")
        per_scene.append(found)
    return per_scene


def _thumbnail(candidate: Candidate, workdir: Path) -> bytes | None:
    raw = workdir / f"thumb_{candidate.id}"
    small = workdir / f"thumb_{candidate.id}.jpg"
    try:
        response = requests.get(candidate.thumb_url, headers=WIKI_HEADERS, timeout=30)
        response.raise_for_status()
        raw.write_bytes(response.content)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-vf", "scale=384:-2", "-frames:v", "1", str(small)],
            check=True,
        )
        return small.read_bytes()
    except (requests.RequestException, subprocess.CalledProcessError):
        return None


def _pick(scenes: list[Scene], per_scene: list[list[Candidate]], models: list[str], workdir: Path) -> list[Candidate | None]:
    by_id = {c.id: c for cands in per_scene for c in cands}
    description = "\n".join(
        f'{i}. Narración: "{s.text}" | Debe verse: {s.subject} | Candidatas: '
        + (", ".join(c.id for c in per_scene[i]) or "ninguna")
        for i, s in enumerate(scenes)
    )
    contents: list = [PICK_PROMPT.format(scenes=description)]
    for candidate in by_id.values():
        image = _thumbnail(candidate, workdir)
        if image:
            contents += [f"Candidata {candidate.id}:", types.Part.from_bytes(data=image, mime_type="image/jpeg")]
    try:
        choices = generate_json(contents, models)
        if isinstance(choices, dict):
            choices = choices.get("choices", [])
        return [by_id.get(str(c)) if c else None for c in list(choices)[:len(scenes)]] + [None] * (len(scenes) - len(choices))
    except Exception as e:
        print(f"Selección visual no disponible ({type(e).__name__}: {e}); se usa la primera candidata")
        return [cands[0] if cands else None for cands in per_scene]


def _fill_gaps(chosen: list[Candidate | None], per_scene: list[list[Candidate]]) -> list[Candidate | None]:
    chosen = [c or next((x for x in per_scene[i] if x.id.startswith("w")), None) for i, c in enumerate(chosen)]
    filled = list(chosen)
    for i, candidate in enumerate(chosen):
        if candidate is None:
            neighbours = [chosen[j] for j in sorted(range(len(chosen)), key=lambda j: abs(j - i)) if chosen[j]]
            filled[i] = neighbours[0] if neighbours else None
    return filled


def _download(candidate: Candidate, workdir: Path) -> Path:
    suffix = ".mp4" if candidate.kind == "video" else Path(candidate.url.split("?")[0]).suffix.lower()
    path = workdir / f"visual_{candidate.id}{suffix}"
    if not path.exists():
        with requests.get(candidate.url, headers=WIKI_HEADERS, stream=True, timeout=120) as r:
            r.raise_for_status()
            with path.open("wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    return path


def gather_visuals(scenes: list[Scene], config: dict, workdir: Path) -> list[Path]:
    per_scene = _collect(scenes, config["video"]["height"])
    chosen = _pick(scenes, per_scene, config["script"]["models"], workdir)
    for i, (scene, candidate) in enumerate(zip(scenes, chosen)):
        print(f"Escena {i} [{scene.subject}] -> {candidate.id if candidate else 'sin imagen adecuada'}")
    filled = _fill_gaps(chosen, per_scene)
    if not any(filled):
        fallback = next((c for cands in per_scene for c in cands), None)
        if fallback is None:
            raise RuntimeError("No se ha encontrado ningún visual para el vídeo")
        filled = [fallback] * len(scenes)
    return [_download(candidate, workdir) for candidate in filled]
