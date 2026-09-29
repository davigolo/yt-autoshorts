import os
from pathlib import Path

import requests

PEXELS_URL = "https://api.pexels.com/videos/search"
FALLBACK_TERMS = ["nature", "abstract background", "city timelapse", "ocean", "space", "forest"]


def _best_file(video: dict, min_height: int) -> str | None:
    files = [f for f in video["video_files"] if f.get("height") and f["height"] >= f.get("width", 0)]
    if not files:
        return None
    good = [f for f in files if f["height"] >= min_height] or files
    return min(good, key=lambda f: f["height"])["link"]


def _search(term: str, min_height: int, used: set[int], limit: int) -> list[str]:
    response = requests.get(
        PEXELS_URL,
        headers={"Authorization": os.environ["PEXELS_API_KEY"]},
        params={"query": term, "orientation": "portrait", "per_page": 15, "size": "medium"},
        timeout=30,
    )
    response.raise_for_status()
    links: list[str] = []
    for video in response.json().get("videos", []):
        if len(links) >= limit:
            break
        if video["id"] in used or not 3 <= video["duration"] <= 60:
            continue
        link = _best_file(video, min_height)
        if link:
            used.add(video["id"])
            links.append(link)
    return links


def download_clips(terms: list[str], config: dict, workdir: Path) -> list[Path]:
    min_height = config["video"]["height"]
    used: set[int] = set()
    clips: list[Path] = []
    per_term = config["video"]["clips_per_term"]
    for i, term in enumerate(terms):
        links = _search(term, min_height, used, per_term) or _search(FALLBACK_TERMS[i % len(FALLBACK_TERMS)], min_height, used, 1)
        for j, link in enumerate(links):
            path = workdir / f"clip_{i}_{j}.mp4"
            with requests.get(link, stream=True, timeout=120) as r:
                r.raise_for_status()
                with path.open("wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            clips.append(path)
    if not clips:
        raise RuntimeError("No se ha podido descargar ningún clip de Pexels")
    return clips
