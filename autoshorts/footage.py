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


WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_HEADERS = {"User-Agent": "yt-autoshorts/1.0 (https://github.com/davigolo/yt-autoshorts)"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MIN_IMAGE_SIDE = 600


def _wiki_image(query: str) -> str | None:
    response = requests.get(
        WIKI_API,
        headers=WIKI_HEADERS,
        params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": query, "gsrlimit": 1,
            "prop": "pageimages", "piprop": "thumbnail|original", "pithumbsize": 1600,
        },
        timeout=30,
    )
    response.raise_for_status()
    for page in response.json().get("query", {}).get("pages", {}).values():
        original, thumb = page.get("original"), page.get("thumbnail")
        if not original or not thumb:
            continue
        if Path(original["source"].split("?")[0]).suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if min(thumb["width"], thumb["height"]) >= MIN_IMAGE_SIDE:
            return thumb["source"]
    return None


def download_images(queries: list[str], workdir: Path) -> list[Path | None]:
    images: list[Path | None] = []
    for i, query in enumerate(queries):
        try:
            link = _wiki_image(query)
            if not link:
                images.append(None)
                continue
            path = workdir / f"image_{i}{Path(link.split('?')[0]).suffix.lower()}"
            response = requests.get(link, headers=WIKI_HEADERS, timeout=60)
            response.raise_for_status()
            path.write_bytes(response.content)
            images.append(path)
        except requests.RequestException as e:
            print(f"Sin imagen para '{query}' ({e})")
            images.append(None)
    return images
