import argparse
import json
import shutil
from datetime import date
from pathlib import Path

import yaml

from autoshorts import facebook, instagram, tiktok
from autoshorts.footage import gather_visuals
from autoshorts.insights import build_insights, fetch_performance, format_weights
from autoshorts.render import render, write_subtitles
from autoshorts.script import generate_script
from autoshorts.thumbnail import create_thumbnail, hashtags
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

    visuals = gather_visuals(script.scenes, config, workdir)
    output = workdir / "short.mp4"
    render(visuals, words, [scene.text for scene in script.scenes], audio, subtitles, config, workdir, output, ROOT / "music")
    print(f"Vídeo generado: {output}")
    thumbnail = None
    try:
        thumbnail = create_thumbnail(visuals[0], script.thumbnail_text, workdir, workdir / "thumbnail.jpg")
        print(f"Miniatura: {thumbnail} ({script.thumbnail_text})")
    except Exception as e:
        print(f"No se pudo generar la miniatura ({type(e).__name__}: {e})")
    yt_description = f"{script.description}\n\n{hashtags(script.hashtags, config['upload']['hashtags'])}"
    print(f"Descripción:\n{yt_description}")

    entry = {"date": date.today().isoformat(), "format": script.format, "topic": script.topic, "title": script.title}
    if not args.no_upload:
        video_id = upload(output, thumbnail, script.title, yt_description, script.tags, config)
        entry["video_id"] = video_id
        print(f"Subido: https://youtube.com/shorts/{video_id}")
        if facebook.is_configured():
            try:
                fb_description = f"{script.title}\n\n{script.description}\n\n{hashtags(script.hashtags, config['facebook']['hashtags'])}"
                entry["fb_video_id"] = facebook.upload_reel(output, fb_description)
                print(f"Subido a Facebook: {entry['fb_video_id']}")
            except Exception as e:
                print(f"No se pudo subir a Facebook ({type(e).__name__}: {e})")
        social_caption = f"{script.title}\n\n{script.description}"
        if instagram.is_configured():
            try:
                ig_caption = f"{social_caption}\n\n{hashtags(script.hashtags, config['instagram']['hashtags'])}"
                entry["ig_media_id"] = instagram.upload_reel(output, ig_caption)
                print(f"Subido a Instagram: {entry['ig_media_id']}")
            except Exception as e:
                print(f"No se pudo subir a Instagram ({type(e).__name__}: {e})")
        if tiktok.is_configured():
            try:
                tt_caption = f"{social_caption}\n\n{hashtags(script.hashtags, config['tiktok']['hashtags'])}"
                entry["tiktok_publish_id"], status = tiktok.upload_video(output, tt_caption)
                print(f"Subido a TikTok: {entry['tiktok_publish_id']} [{status}]")
            except Exception as e:
                print(f"No se pudo subir a TikTok ({type(e).__name__}: {e})")

    history.append(entry)
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
