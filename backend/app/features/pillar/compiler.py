"""Compile a pillar sequence into the ESP's PLP1 binary (docs/pillar-led-contract.md §4–5).

Every frame transition is baked into per-pixel delay/fade and brightness into the colour,
so the ESP only implements one rule: hold until delay_ms, then fade linearly over fade_ms.
"""
import struct
import zlib
from dataclasses import dataclass

from .schemas import FrameStep, Sequence

MAGIC = b"PLP1"
HEADER = struct.Struct("<4sIBBHI")
EFFECT = struct.Struct("<BBHBBB9s")
FRAME_HEAD = struct.Struct("<BH")
PIXEL = struct.Struct("<BBBHH")

HEADER_SIZE = HEADER.size                                 # 16
EFFECT_RECORD_SIZE = EFFECT.size                          # 16
FRAME_RECORD_SIZE = FRAME_HEAD.size + 100 * PIXEL.size    # 703
MAX_FILE_SIZE = 48 * 1024

KIND_EFFECT = 1
KIND_FRAME = 2
EFFECT_IDS = {"off": 0, "solid": 1, "rainbow": 2, "comet": 3, "fill": 4,
              "sparkle": 5, "pulse": 6, "band": 7, "fade": 8, "snake": 9, "stripes": 10}
DIRECTION_IDS = {"up": 0, "down": 1, "bounce": 2}
WIPE_EDGE_MAX_MS = 150


@dataclass(frozen=True)
class BakedPixel:
    r: int
    g: int
    b: int
    fade_ms: int
    delay_ms: int


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def bake_frame(step: FrameStep) -> list[BakedPixel]:
    t = step.transition
    duration = step.duration_ms
    count = len(step.pixels)
    baked = []
    for i, px in enumerate(step.pixels):
        if t.type == "custom":
            delay, fade = px.delay_ms, px.fade_ms
        elif t.type == "crossfade":
            delay, fade = 0, t.ms
        elif t.type == "wipe":
            pos = i if t.direction == "up" else count - 1 - i
            delay, fade = pos * t.ms // count, min(WIPE_EDGE_MAX_MS, t.ms // 10)
        else:  # cut
            delay, fade = 0, 0
        if t.type != "custom":
            # Generated timing always fits the step (custom values are validated instead)
            fade = min(fade, max(0, duration - delay))
        r, g, b = (c * px.brightness // 255 for c in _rgb(px.color))
        baked.append(BakedPixel(r, g, b, fade, delay))
    return baked


def _effect_record(step) -> bytes:
    colors = b"".join(bytes(_rgb(c)) for c in step.colors).ljust(9, b"\0")
    speed_x16 = max(4, min(64, round(step.speed * 16)))
    return EFFECT.pack(KIND_EFFECT, EFFECT_IDS[step.effect], step.duration_ms, step.brightness,
                       DIRECTION_IDS[step.direction], speed_x16, colors)


def _frame_record(step: FrameStep) -> bytes:
    pixels = b"".join(PIXEL.pack(p.r, p.g, p.b, p.fade_ms, p.delay_ms) for p in bake_frame(step))
    return FRAME_HEAD.pack(KIND_FRAME, step.duration_ms) + pixels


def compile_sequence(sequence: Sequence, version: int) -> bytes:
    body = b"".join(
        _frame_record(s) if isinstance(s, FrameStep) else _effect_record(s) for s in sequence.steps
    )
    header = HEADER.pack(MAGIC, version, int(sequence.loop), len(sequence.steps), 0, zlib.crc32(body))
    data = header + body
    # 64 frames is ~44 KB, so a validated sequence always fits; guard the ESP anyway
    if len(data) > MAX_FILE_SIZE:
        raise ValueError(f"Compiled sequence is {len(data)} bytes; the pillar accepts at most {MAX_FILE_SIZE}")
    return data
