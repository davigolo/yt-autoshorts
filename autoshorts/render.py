import json
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
Style: Default,DejaVu Sans,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


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


def write_subtitles(words: list[Word], config: dict, out: Path, words_per_line: int = 3) -> None:
    lines = [ASS_HEADER.format(w=config["video"]["width"], h=config["video"]["height"])]
    for i in range(0, len(words), words_per_line):
        group = words[i:i + words_per_line]
        end = words[i + words_per_line].start if i + words_per_line < len(words) else group[-1].end + 0.3
        text = " ".join(w.text for w in group).upper().replace("{", "").replace("}", "")
        lines.append(f"Dialogue: 0,{_ts(group[0].start)},{_ts(end)},Default,,0,0,0,,{text}\n")
    out.write_text("".join(lines), encoding="utf-8")


def render(clips: list[Path], audio: Path, subtitles: Path, config: dict, workdir: Path, out: Path) -> None:
    w, h, fps = config["video"]["width"], config["video"]["height"], config["video"]["fps"]
    total = duration(audio) + 0.5
    segment = total / len(clips)
    parts = []
    for i, clip in enumerate(clips):
        part = workdir / f"part_{i}.mp4"
        _run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(clip), "-t", f"{segment:.3f}", "-an",
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},setsar=1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(part),
        ])
        parts.append(part)

    concat_list = workdir / "concat.txt"
    concat_list.write_text("".join(f"file '{p.name}'\n" for p in parts))
    joined = workdir / "joined.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(joined)])

    _run([
        "ffmpeg", "-y", "-i", str(joined.resolve()), "-i", str(audio.resolve()),
        "-vf", f"ass={subtitles.name}",
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}",
        "-movflags", "+faststart", str(out.resolve()),
    ], cwd=workdir)
