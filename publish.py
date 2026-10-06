import argparse
import json
from pathlib import Path

import yaml
from googleapiclient.discovery import build

from autoshorts.publish import fetch_statuses, pending, publish_due
from autoshorts.upload import _credentials, can_manage_videos

ROOT = Path(__file__).parent
HISTORY = ROOT / "history.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Pasa a público los shorts que llevan el tiempo configurado en oculto")
    parser.add_argument("--dry-run", action="store_true", help="Muestra qué se publicaría sin cambiar nada")
    args = parser.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    credentials = _credentials()
    if not can_manage_videos(credentials):
        print("AVISO: el token de YouTube no tiene el scope youtube.force-ssl; no se puede cambiar la visibilidad. "
              "Ejecuta scripts/get_token.py y actualiza los secrets.")
        return
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    entries = pending(history)
    statuses = fetch_statuses(youtube, [e["video_id"] for e in entries])
    overrides = {"selfDeclaredMadeForKids": False, "containsSyntheticMedia": config["upload"]["contains_synthetic_media"]}
    published = publish_due(youtube, entries, statuses, config["publish"]["after_hours"], overrides, dry_run=args.dry_run)
    print(f"{published} vídeo(s) publicados")


if __name__ == "__main__":
    main()
