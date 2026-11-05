import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import requests
from google.genai import types

from autoshorts.script import Scene, generate_json

PEXELS_URL = "https://api.pexels.com/videos/search"
PEXELS_PHOTOS_URL = "https://api.pexels.com/v1/search"
WIKI_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKI_HEADERS = {"User-Agent": "yt-autoshorts/1.0 (https://github.com/davigolo/yt-autoshorts)"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MIN_IMAGE_SIDE = 600
PEXELS_PER_SCENE = 3
HOOK_PEXELS = 6
COMMONS_PER_SCENE = 4

PICK_PROMPT = """Select visuals for a Short explaining one packaging mechanism.
For each scene, choose only from that scene's candidate IDs.
- The exact packaging object or feature must be visible and support the narration.
- A bottle is not evidence of its internal seal; a generic factory does not show a can seam.
- Do not confuse a can's top with its base, a screw cap with a vacuum lid, or glass with plastic.
- Photos, diagrams and videos are valid. Prefer clarity and technical accuracy over motion.
- Return null if no candidate actually shows the required object or feature.
- For scene 0, prefer motion only when it shows the exact feature. A correct still is better than unrelated footage.

Scenes:
{scenes}

Return ONLY JSON: {{"choices": ["selected candidate ID or null, one per scene in order"]}}"""


@dataclass
class Candidate:
    id: str
    scene: int
    kind: str
    thumb_url: str
    url: str
    duration: float = 0.0


class MissingVisualsError(RuntimeError):
    pass


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
        if thumb and original and _image_ok(original["source"], original["width"], original["height"]):
            out.append(Candidate(f"w{index}", index, "image", thumb["source"], thumb["source"]))
    return out


def _commons_candidates(scene: Scene, index: int) -> list[Candidate]:
    data = _get(COMMONS_API, {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{scene.stock} filetype:bitmap", "gsrlimit": 6,
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


def _pexels_candidates(scene: Scene, index: int, min_height: int, used: set[int], limit: int) -> list[Candidate]:
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
        if len(out) >= limit:
            break
    return out


def _pexels_photos(scene: Scene, index: int) -> list[Candidate]:
    data = _get(
        PEXELS_PHOTOS_URL, {"query": scene.stock, "per_page": 6},
        {"Authorization": os.environ["PEXELS_API_KEY"]},
    )
    return [
        Candidate(f"ph{index}_{photo['id']}", index, "image", photo["src"]["medium"], photo["src"]["large2x"])
        for photo in data.get("photos", [])
        if min(photo["width"], photo["height"]) >= MIN_IMAGE_SIDE
    ]


def _collect(scenes: list[Scene], min_height: int, require_matching: bool = False) -> list[list[Candidate]]:
    used: set[int] = set()
    per_scene = []
    for i, scene in enumerate(scenes):
        found: list[Candidate] = []
        for source in (
            lambda: _wiki_candidates(scene, i),
            lambda: _commons_candidates(scene, i),
            lambda: _pexels_photos(scene, i),
            lambda: _pexels_candidates(scene, i, min_height, used, HOOK_PEXELS if i == 0 else PEXELS_PER_SCENE),
        ):
            try:
                found += source()
            except requests.RequestException as e:
                print(f"Búsqueda fallida en escena {i} ({e})")
        if i == 0 and not require_matching and any(c.kind == "video" for c in found):
            found = [c for c in found if c.kind == "video"]
        per_scene.append(found)
    return per_scene


def _thumbnail(candidate: Candidate, workdir: Path) -> bytes | None:
    raw = workdir / f"thumb_{candidate.id}"
    small = workdir / f"thumb_{candidate.id}.jpg"
    if small.exists():
        return small.read_bytes()
    try:
        response = requests.get(candidate.thumb_url, headers=WIKI_HEADERS, timeout=30)
        response.raise_for_status()
        raw.write_bytes(response.content)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-vf", "scale=384:-2", "-frames:v", "1", str(small)],
            check=True,
        )
        return small.read_bytes()
    except (requests.RequestException, subprocess.CalledProcessError) as error:
        print(f"Miniatura no disponible para {candidate.id}: {error}")
        return None


def discover_visuals(searches: list[Scene], config: dict, workdir: Path) -> tuple[list[Candidate], list]:
    candidates = []
    contents: list = ["Available visual inventory (IDs refer to the attached images):"]
    seen: set[str] = set()
    for group in _collect(searches, config["video"]["height"], require_matching=True):
        for candidate in group:
            if candidate.url in seen:
                continue
            seen.add(candidate.url)
            image = _thumbnail(candidate, workdir)
            if image is not None:
                candidates.append(candidate)
                contents.extend([
                    f"Visual {candidate.id} ({candidate.kind}), search: {searches[candidate.scene].stock}",
                    types.Part.from_bytes(data=image, mime_type="image/jpeg"),
                ])
    if not candidates:
        raise MissingVisualsError("No hay imágenes disponibles para construir el guion")
    print(f"Inventario visual: {len(candidates)} imágenes disponibles antes de escribir el guion")
    return candidates, contents


def _pick(
    scenes: list[Scene], per_scene: list[list[Candidate]], models: list[str], workdir: Path,
    require_matching: bool = False,
) -> list[Candidate | None]:
    by_id = {c.id: c for cands in per_scene for c in cands}
    description = "\n".join(
        f'{i}. Narración: "{s.text}" | Debe verse: {s.subject} | Candidatas: '
        + (", ".join(c.id for c in per_scene[i]) or "ninguna")
        for i, s in enumerate(scenes)
    )
    contents: list = [PICK_PROMPT.format(scenes=description)]
    visible_ids: set[str] = set()
    for candidate in by_id.values():
        image = _thumbnail(candidate, workdir)
        if image:
            visible_ids.add(candidate.id)
            contents += [f"Candidata {candidate.id}:", types.Part.from_bytes(data=image, mime_type="image/jpeg")]
    try:
        choices = generate_json(contents, models)
        if isinstance(choices, dict):
            choices = choices.get("choices", [])
        selected = [by_id.get(str(c)) if c else None for c in list(choices)[:len(scenes)]]
        selected += [None] * (len(scenes) - len(selected))
        return [
            candidate
            if candidate and candidate.scene == i and (not require_matching or candidate.id in visible_ids)
            else None
            for i, candidate in enumerate(selected)
        ]
    except Exception as e:
        if require_matching:
            raise RuntimeError("No se pudo validar la correspondencia visual de las escenas") from e
        print(f"Selección visual no disponible ({type(e).__name__}: {e}); se usa la primera candidata")
        first = [cands[0] if cands else None for cands in per_scene]
        first[0] = next((c for c in per_scene[0] if c.kind == "video"), first[0]) if per_scene else None
        return first


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


def gather_visuals(
    scenes: list[Scene], config: dict, workdir: Path, inventory: list[Candidate] | None = None,
) -> list[Path]:
    require_matching = config["video"].get("require_matching_visuals", False)
    if inventory is None:
        per_scene = _collect(scenes, config["video"]["height"], require_matching)
    else:
        require_matching = True
        by_id = {candidate.id: candidate for candidate in inventory}
        per_scene = []
        for i, scene in enumerate(scenes):
            candidate = by_id.get(scene.visual_id)
            if candidate is None:
                raise MissingVisualsError(f"La escena {i + 1} solicita una imagen fuera del inventario")
            per_scene.append([replace(candidate, scene=i, id=f"s{i}_{candidate.id}")])
    chosen = _pick(scenes, per_scene, config["script"]["models"], workdir, require_matching)
    for i, (scene, candidate) in enumerate(zip(scenes, chosen)):
        print(f"Escena {i} [{scene.subject}] -> {candidate.id if candidate else 'sin imagen adecuada'}")
    if require_matching:
        missing = [str(i + 1) for i, candidate in enumerate(chosen) if candidate is None]
        if missing:
            raise MissingVisualsError(f"No hay visuales adecuados para las escenas {', '.join(missing)}; no se genera ni se sube el vídeo")
        return [_download(candidate, workdir) for candidate in chosen]
    filled = _fill_gaps(chosen, per_scene)
    if not any(filled):
        fallback = next((c for cands in per_scene for c in cands), None)
        if fallback is None:
            raise RuntimeError("No se ha encontrado ningún visual para el vídeo")
        filled = [fallback] * len(scenes)
    return [_download(candidate, workdir) for candidate in filled]
