import argparse
import json
import shutil
from datetime import date
from pathlib import Path

import yaml

from autoshorts import facebook
from autoshorts.footage import download_clips, download_images
from autoshorts.insights import build_insights, fetch_performance, format_weights
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

    insights, weights = "", {}
    try:
        performance = fetch_performance(history)
        insights, weights = build_insights(performance), format_weights(performance)
        print(f"Estadísticas: {len(performance)} vídeos con datos, pesos por formato {weights}")
    except Exception as e:
        print(f"Sin estadísticas ({type(e).__name__}: {e}); se genera sin ellas")

    script = generate_script(config, history, insights, weights)
    print(f"Formato: {script.format}\nTema: {script.topic}\nGancho: {script.hook_text}\nTítulo: {script.title}")

    audio = workdir / "voice.mp3"
    words = synthesize(script.narration, config, audio)
    subtitles = workdir / "subs.ass"
    write_subtitles(words, script.hook_text, config, subtitles)

    clips = download_clips(script.search_terms, config, workdir)
    output = workdir / "short.mp4"
    images = download_images(script.wiki_images, workdir)
    print(f"Imágenes de Wikipedia: {sum(1 for i in images if i)}/{len(script.wiki_images)} {script.wiki_images}")
    render(clips, images, audio, subtitles, config, workdir, output, ROOT / "music")
    print(f"Vídeo generado: {output}")

    entry = {"date": date.today().isoformat(), "format": script.format, "topic": script.topic, "title": script.title}
    if not args.no_upload:
        video_id = upload(output, script.title, script.description, script.tags, config)
        entry["video_id"] = video_id
        print(f"Subido: https://youtube.com/shorts/{video_id}")
        if facebook.is_configured():
            try:
                fb_description = f"{script.title}\n\n{script.description}\n\n{config['facebook']['hashtags']}"
                entry["fb_video_id"] = facebook.upload_reel(output, fb_description)
                print(f"Subido a Facebook: {entry['fb_video_id']}")
            except Exception as e:
                print(f"No se pudo subir a Facebook ({type(e).__name__}: {e})")

    history.append(entry)
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
