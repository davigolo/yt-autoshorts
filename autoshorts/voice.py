import asyncio
import base64
import os
import time
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import requests

TICKS_PER_SECOND = 10_000_000
ELEVENLABS_API = "https://api.elevenlabs.io/v1"
PUNCTUATION = ".,;:!?¡¿\"'«»“”‘’()[]…—–-"


@dataclass
class Word:
    start: float
    end: float
    text: str


async def _edge_synthesize(text: str, voice: str, rate: str, out: Path) -> list[Word]:
    communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words: list[Word] = []
    with out.open("wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / TICKS_PER_SECOND
                words.append(Word(start, start + chunk["duration"] / TICKS_PER_SECOND, chunk["text"]))
    return words


def _elevenlabs_headers() -> dict[str, str]:
    return {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}


def _elevenlabs_remaining() -> int | None:
    try:
        response = requests.get(f"{ELEVENLABS_API}/user/subscription", headers=_elevenlabs_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()
        return data["character_limit"] - data["character_count"]
    except Exception as e:
        print(f"No se pudo consultar la cuota de ElevenLabs ({e})")
        return None


def _alignment_words(alignment: dict) -> list[Word]:
    words: list[Word] = []
    current, start, end = "", 0.0, 0.0

    def flush() -> None:
        text = current.strip(PUNCTUATION)
        if text:
            words.append(Word(start, end, text))

    for char, char_start, char_end in zip(
        alignment["characters"], alignment["character_start_times_seconds"], alignment["character_end_times_seconds"]
    ):
        if char.isspace():
            flush()
            current = ""
            continue
        if not current:
            start = char_start
        current += char
        end = char_end
    flush()
    return words


def _elevenlabs_synthesize(text: str, voice: dict, out: Path) -> list[Word]:
    for attempt in range(4):
        response = requests.post(
            f"{ELEVENLABS_API}/text-to-speech/{voice['voice_id']}/with-timestamps",
            params={"output_format": "mp3_44100_128"},
            headers=_elevenlabs_headers(),
            json={
                "text": text,
                "model_id": voice["model_id"],
                "language_code": voice["language_code"],
                "voice_settings": {
                    "stability": voice["stability"],
                    "similarity_boost": voice["similarity_boost"],
                    "style": voice["style"],
                    "speed": voice["speed"],
                    "use_speaker_boost": True,
                },
            },
            timeout=180,
        )
        if response.status_code in {429, 500, 502, 503}:
            time.sleep(10 * (attempt + 1))
            continue
        if not response.ok:
            raise RuntimeError(f"ElevenLabs {response.status_code}: {response.text[:500]}")
        data = response.json()
        out.write_bytes(base64.b64decode(data["audio_base64"]))
        return _alignment_words(data["alignment"])
    raise RuntimeError("ElevenLabs no responde")


def _elevenlabs_available(text: str, voice: dict) -> bool:
    if not os.environ.get("ELEVENLABS_API_KEY"):
        print("Sin ELEVENLABS_API_KEY; se usa edge-tts")
        return False
    needed = int(len(text) * voice["credits_per_char"])
    remaining = _elevenlabs_remaining()
    if remaining is not None and remaining < needed + voice["reserve_credits"]:
        print(f"Quedan {remaining} créditos de ElevenLabs (reserva {voice['reserve_credits']}); se usa edge-tts")
        return False
    return True


def synthesize(text: str, config: dict, out: Path) -> list[Word]:
    voice = config["voice"]
    eleven = voice.get("elevenlabs")
    if eleven and _elevenlabs_available(text, eleven):
        try:
            words = _elevenlabs_synthesize(text, eleven, out)
            print(f"Voz: ElevenLabs ({eleven['voice_id']}, {eleven['model_id']})")
            return words
        except Exception as e:
            print(f"ElevenLabs falló ({type(e).__name__}: {e}); se usa edge-tts")
    print(f"Voz: edge-tts ({voice['name']})")
    return asyncio.run(_edge_synthesize(text, voice["name"], voice["rate"], out))
