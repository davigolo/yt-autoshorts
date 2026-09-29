import asyncio
from dataclasses import dataclass
from pathlib import Path

import edge_tts

TICKS_PER_SECOND = 10_000_000


@dataclass
class Word:
    start: float
    end: float
    text: str


async def _synthesize(text: str, voice: str, rate: str, out: Path) -> list[Word]:
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


def synthesize(text: str, config: dict, out: Path) -> list[Word]:
    return asyncio.run(_synthesize(text, config["voice"]["name"], config["voice"]["rate"], out))
