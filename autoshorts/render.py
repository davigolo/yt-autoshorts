import json
import math
import random
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
Style: Caption,DejaVu Sans,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8,3,2,80,80,620,1
Style: Hook,DejaVu Sans,100,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,24,0,8,90,90,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
HIGHLIGHT = r"{\c&H3FD2FF&\fscx112\fscy112}"
RESET = r"{\r}"
HOOK_SECONDS = 2.8
TAIL_SECONDS = 0.2
MUSIC_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg"}


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


def write_subtitles(words: list[Word], hook_text: str, config: dict, out: Path, words_per_line: int = 3) -> None:
    lines = [ASS_HEADER.format(w=config["video"]["width"], h=config["video"]["height"])]
    lines.append(f"Dialogue: 1,{_ts(0)},{_ts(HOOK_SECONDS)},Hook,,0,0,0,,{_clean(hook_text)}\n")
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


def _plan_segments(clips: list[Path], total: float, target: float) -> list[tuple[Path, float]]:
    count = max(1, math.ceil(total / target))
    uses: dict[Path, int] = {}
    plan = []
    for i in range(count):
        clip = clips[int(i * len(clips) / count)] if len(clips) >= count else clips[i % len(clips)]
        used = uses.get(clip, 0)
        uses[clip] = used + 1
        plan.append((clip, used * target))
    return plan


def _pick_music(music_dir: Path) -> Path | None:
    tracks = [p for p in music_dir.glob("*") if p.suffix.lower() in MUSIC_EXTENSIONS] if music_dir.exists() else []
    return random.choice(tracks) if tracks else None


def render(clips: list[Path], audio: Path, subtitles: Path, config: dict, workdir: Path, out: Path, music_dir: Path) -> None:
    video = config["video"]
    w, h, fps, zoom = video["width"], video["height"], video["fps"], video["zoom"]
    total = duration(audio) + TAIL_SECONDS
    plan = _plan_segments(clips, total, video["segment_seconds"])
    segment = total / len(plan)
    clip_lengths = {clip: duration(clip) for clip in set(clips)}

    parts = []
    for i, (clip, offset) in enumerate(plan):
        start = offset % max(clip_lengths[clip] - segment, 0.01)
        progress = f"t/{segment:.3f}" if i % 2 == 0 else f"(1-t/{segment:.3f})"
        part = workdir / f"part_{i}.mp4"
        _run([
            "ffmpeg", "-y", "-ss", f"{start:.3f}", "-stream_loop", "-1", "-i", str(clip), "-t", f"{segment:.3f}", "-an",
            "-vf", (
                f"setpts=PTS-STARTPTS,fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                f"scale=w='trunc({w}*(1+{zoom}*{progress})/2)*2':h=-2:eval=frame,crop={w}:{h},setsar=1"
            ),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(part),
        ])
        parts.append(part)

    concat_list = workdir / "concat.txt"
    concat_list.write_text("".join(f"file '{p.name}'\n" for p in parts))
    joined = workdir / "joined.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(joined)])

    inputs = ["-i", str(joined.resolve()), "-i", str(audio.resolve())]
    audio_filter = "[1:a]apad[mix]"
    music = _pick_music(music_dir)
    if music:
        print(f"Música: {music.name}")
        inputs += ["-stream_loop", "-1", "-i", str(music.resolve())]
        audio_filter = (
            f"[2:a]volume={config['music']['volume']},afade=t=in:d=1,"
            f"afade=t=out:st={max(total - 1.5, 0):.3f}:d=1.5[m];"
            "[1:a]apad[vo];[vo][m]amix=inputs=2:duration=shortest:normalize=0[mix]"
        )

    _run([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", f"[0:v]ass={subtitles.name}[v];{audio_filter};[mix]loudnorm=I=-14:TP=-1.5:LRA=11[a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}",
        "-movflags", "+faststart", str(out.resolve()),
    ], cwd=workdir)
