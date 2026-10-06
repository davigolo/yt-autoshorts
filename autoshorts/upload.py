import os
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from autoshorts.playlists import add_to_playlist

MANAGE_SCOPES = {
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
}
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


def _credentials() -> Credentials:
    return Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )


def can_manage_videos(credentials: Credentials) -> bool:
    try:
        if not credentials.valid:
            credentials.refresh(Request())
        response = requests.get(TOKENINFO_URL, params={"access_token": credentials.token}, timeout=30)
        response.raise_for_status()
        return bool(MANAGE_SCOPES & set(response.json().get("scope", "").split()))
    except Exception as e:
        print(f"No se pudieron comprobar los permisos del token ({type(e).__name__}: {e})")
        return False


def upload(
    video: Path, thumbnail: Path | None, title: str, description: str, tags: list[str], playlist: str | None, config: dict,
) -> tuple[str, str]:
    credentials = _credentials()
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    settings = config["upload"]
    privacy = settings["privacy"]
    manage = can_manage_videos(credentials)
    if privacy == "unlisted" and not manage:
        print(
            "AVISO: el token de YouTube no tiene el scope youtube.force-ssl, así que no se podría pasar a público más tarde. "
            "Se sube en público. Ejecuta scripts/get_token.py y actualiza los secrets para activar la subida en oculto."
        )
        privacy = "public"
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": settings["category_id"],
            "defaultLanguage": settings["language"],
            "defaultAudioLanguage": settings["language"],
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": settings["contains_synthetic_media"],
            "publicStatsViewable": True,
        },
    }
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video), mimetype="video/mp4", chunksize=-1, resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    video_id = response["id"]
    if thumbnail:
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail), mimetype="image/jpeg")).execute()
            print("Miniatura personalizada subida")
        except HttpError as e:
            print(f"No se pudo poner la miniatura: {e}")
    playlist_settings = config.get("playlists", {}).get(playlist or "")
    if playlist_settings and manage:
        add_to_playlist(youtube, video_id, playlist_settings["title"], playlist_settings["description"])
    return video_id, privacy
