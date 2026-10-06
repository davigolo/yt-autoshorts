import json
import random
import re
import subprocess
from pathlib import Path

from autoshorts.voice import Word

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Anton,180,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,1,0,1,9,4,2,70,70,560,1
Style: Hook,Anton,170,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,1,0,1,10,5,8,70,70,300,1
Style: Label,Anton,200,&H003FD2FF,&H003FD2FF,&H00000000,&H80000000,0,0,0,0,100,100,1,0,1,10,5,8,70,70,600,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
HIGHLIGHT = r"{\c&H3FD2FF&\fscx112\fscy112}"
RESET = r"{\r}"
HOOK_SECONDS = 2.8
HOOK_ZOOM = 2.5
FONTS_DIR = Path(__file__).parent.parent / "fonts"
TAIL_SECONDS = 0.2
SAMPLE_RATE = 48000
MUSIC_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _run(args: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(args, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falló: {' '.join(args)}\n{result.stderr[-2000:]}")


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def _ts(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(text: str) -> str:
    return text.upper().replace("{", "").replace("}", "").replace("\\", "")


def write_subtitles(
    words: list[Word], hook_text: str, scene_texts: list[str], labels: list[str | None], config: dict, out: Path,
    words_per_line: int = 2,
) -> None:
    lines = [ASS_HEADER.format(w=config["video"]["width"], h=config["video"]["height"])]
    lines.append(f"Dialogue: 1,{_ts(0)},{_ts(HOOK_SECONDS)},Hook,,0,0,0,,{_clean(hook_text)}\n")
    starts = _scene_starts(words, scene_texts)
    ends = starts[1:] + [words[-1].end + TAIL_SECONDS if words else 0.0]
    for label, start, end in zip(labels, starts, ends):
        if label and end > start:
            lines.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Label,,0,0,0,,{_clean(label)}\n")
    for i in range(0, len(words), words_per_line):
        group = words[i:i + words_per_line]
        group_end = words[i + words_per_line].start if i + words_per_line < len(words) else group[-1].end + TAIL_SECONDS
        for j, word in enumerate(group):
            end = group[j + 1].start if j + 1 < len(group) else group_end
            text = " ".join(
                f"{HIGHLIGHT}{_clean(w.text)}{RESET}" if k == j else _clean(w.text)
                for k, w in enumerate(group)
            )
            lines.append(f"Dialogue: 0,{_ts(word.start)},{_ts(end)},Caption,,0,0,0,,{text}\n")
    out.write_text("".join(lines), encoding="utf-8")


def _scene_starts(words: list[Word], scene_texts: list[str]) -> list[float]:
    counts = [len(re.findall(r"\w+", text)) for text in scene_texts]
    total = sum(counts) or 1
    starts, cumulative = [], 0
    for count in counts:
        index = min(round(cumulative / total * len(words)), len(words) - 1)
        starts.append(words[index].start if cumulative and words else 0.0)
        cumulative += count
    return starts


def _plan(visuals: list[Path], starts: list[float], total: float, target: float) -> list[tuple[Path, float, float, float]]:
    plan = []
    bounds = starts[1:] + [total]
    for visual, start, end in zip(visuals, starts, bounds):
        if end - start <= 0.05:
            continue
        pieces = max(1, round((end - start) / target))
        step = (end - start) / pieces
        for k in range(pieces):
            plan.append((visual, start + k * step, start + (k + 1) * step, k * step))
    return plan


def _segment_filter(source: Path, w: int, h: int, fps: int, zoom: float, progress: str) -> str:
    kenburns = f"scale=w='trunc({w}*(1+{zoom}*{progress})/2)*2':h=-2:eval=frame,crop={w}:{h},setsar=1"
    if source.suffix.lower() in IMAGE_EXTENSIONS:
        return (
            f"[0:v]fps={fps},split[a][b];"
            f"[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=40:2,eq=brightness=-0.2[bg];"
            f"[b]scale={round(w * 1.5 / 2) * 2}:-2,crop='min(iw,{w})':'min(ih,{h})'[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{kenburns}[v]"
        )
    return (
        f"[0:v]setpts=PTS-STARTPTS,fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"{kenburns}[v]"
    )


def _pick_music(music_dir: Path) -> Path | None:
    tracks = [p for p in music_dir.glob("*") if p.suffix.lower() in MUSIC_EXTENSIONS] if music_dir.exists() else []
    return random.choice(tracks) if tracks else None


def render(
    visuals: list[Path], words: list[Word], scene_texts: list[str], audio: Path, subtitles: Path,
    config: dict, workdir: Path, out: Path, music_dir: Path,
) -> None:
    video = config["video"]
    w, h, fps, zoom = video["width"], video["height"], video["fps"], video["zoom"]
    total = duration(audio) + TAIL_SECONDS
    plan = _plan(visuals, _scene_starts(words, scene_texts), total, video["segment_seconds"])
    clip_lengths = {v: duration(v) for v in set(visuals) if v.suffix.lower() not in IMAGE_EXTENSIONS}

    parts = []
    for i, (visual, start, end, offset) in enumerate(plan):
        frames = round(end * fps) - round(start * fps)
        if frames <= 0:
            continue
        length = end - start
        progress = f"t/{length:.3f}" if i % 2 == 0 else f"(1-t/{length:.3f})"
        segment_zoom = zoom * HOOK_ZOOM if i == 0 else zoom
        if visual in clip_lengths:
            seek = offset % max(clip_lengths[visual] - length, 0.01)
            source = ["-ss", f"{seek:.3f}", "-stream_loop", "-1", "-i", str(visual)]
        else:
            source = ["-loop", "1", "-i", str(visual)]
        part = workdir / f"part_{i}.mp4"
        _run([
            "ffmpeg", "-y", *source, "-frames:v", str(frames), "-an",
            "-filter_complex", _segment_filter(visual, w, h, fps, segment_zoom, progress), "-map", "[v]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(part),
        ])
        parts.append(part)

    concat_list = workdir / "concat.txt"
    concat_list.write_text("".join(f"file '{p.name}'\n" for p in parts))
    joined = workdir / "joined.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(joined)])

    voice = workdir / "voice_norm.wav"
    _run([
        "ffmpeg", "-y", "-i", str(audio), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-ar", str(SAMPLE_RATE), "-ac", "2", str(voice),
    ])

    mixed = workdir / "mix.wav"
    music = _pick_music(music_dir)
    if music:
        print(f"Música: {music.name}")
        _run([
            "ffmpeg", "-y", "-i", str(voice), "-i", str(music),
            "-filter_complex", (
                f"[1:a]aresample={SAMPLE_RATE},apad=whole_dur={total:.3f},atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
                f"volume={config['music']['volume']},afade=t=in:d=1,afade=t=out:st={max(total - 1.5, 0):.3f}:d=1.5[m];"
                f"[0:a]apad=whole_dur={total:.3f}[vo];"
                "[vo][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89[a]"
            ),
            "-map", "[a]", "-ar", str(SAMPLE_RATE), str(mixed),
        ])
    else:
        _run(["ffmpeg", "-y", "-i", str(voice), "-af", f"apad=whole_dur={total:.3f}", str(mixed)])

    _run([
        "ffmpeg", "-y", "-i", str(joined.resolve()), "-i", str(mixed.resolve()),
        "-filter_complex", f"[0:v]ass={subtitles.name}:fontsdir={FONTS_DIR.resolve()},tpad=stop_mode=clone:stop_duration=1[v]",
        "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}",
        "-movflags", "+faststart", str(out.resolve()),
    ], cwd=workdir)
