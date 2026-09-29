import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _credentials() -> Credentials:
    return Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


def upload(video: Path, title: str, description: str, tags: list[str], config: dict) -> str:
    youtube = build("youtube", "v3", credentials=_credentials(), cache_discovery=False)
    body = {
        "snippet": {
            "title": title,
            "description": f"{description}\n\n#shorts",
            "tags": tags,
            "categoryId": config["upload"]["category_id"],
        },
        "status": {
            "privacyStatus": config["upload"]["privacy"],
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": config["upload"]["contains_synthetic_media"],
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
    return response["id"]
