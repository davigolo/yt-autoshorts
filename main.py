import argparse
import json
import shutil
from datetime import date
from pathlib import Path

import yaml

from autoshorts.footage import download_clips
from autoshorts.render import render, write_subtitles
from autoshorts.script import generate_script
from autoshorts.upload import upload
from autoshorts.voice import synthesize

ROOT = Path(__file__).parent
HISTORY = ROOT / "history.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-upload", action="store_true", help="Genera el vídeo sin subirlo")
    args = parser.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []

    workdir = ROOT / "build"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir()

    script = generate_script(config, [h["topic"] for h in history])
    print(f"Tema: {script.topic}\nTítulo: {script.title}")

    audio = workdir / "voice.mp3"
    words = synthesize(script.narration, config, audio)
    subtitles = workdir / "subs.ass"
    write_subtitles(words, config, subtitles)

    clips = download_clips(script.search_terms, config, workdir)
    output = workdir / "short.mp4"
    render(clips, audio, subtitles, config, workdir, output)
    print(f"Vídeo generado: {output}")

    entry = {"date": date.today().isoformat(), "topic": script.topic, "title": script.title}
    if not args.no_upload:
        video_id = upload(output, script.title, script.description, script.tags, config)
        entry["video_id"] = video_id
        print(f"Subido: https://youtube.com/shorts/{video_id}")

    history.append(entry)
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
