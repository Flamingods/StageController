"""The hub drives the pillar poles (docs/pillar-led-contract.md §9): each show event's pole becomes a
per-pillar preview sequence, which the pillar picks up on its next poll (~1 s) and plays with its
existing renderer. No firmware change: the pillar only knows previews."""
import threading

from app.features.show import tunables
from app.features.show.schemas import Pole, ShowEvent

from .compiler import compile_sequence
from .schemas import PIXEL_COUNT, MAX_DURATION_MS, MIN_DURATION_MS, EffectStep, FrameStep, Pixel, Sequence, Transition

SIDE_BY_PILLAR = {1: "L", 2: "R"}  # fixed: pillar 1 stands left, as seen from the entrance
BLACK = "#000000"
HOLD_MS = MAX_DURATION_MS  # a held look repeats every minute; the loop restart is invisible
EDGE_FADE_MS = 150  # each pixel's fade as a rising/draining edge passes it (the contract's wipe fade)


def _hex(name: str, level_pct: int = 100) -> str:
    r, g, b = tunables.palette(name)
    return "#%02X%02X%02X" % tuple(c * level_pct // 100 for c in (r, g, b))


def _frame(pixels: list[Pixel], duration_ms: int = HOLD_MS, transition: Transition | None = None) -> FrameStep:
    return FrameStep(kind="frame", duration_ms=duration_ms, transition=transition or Transition(), pixels=pixels)


def _fill(pct: int, color: str) -> list[Pixel]:
    lit = PIXEL_COUNT * max(0, min(100, pct)) // 100
    return [Pixel(color=color if i < lit else BLACK) for i in range(PIXEL_COUNT)]


def _custom(targets: list[Pixel], delays: dict[int, int], duration_ms: int) -> FrameStep:
    """A frame whose pixels in `delays` fade to their target at their own time; the rest cut at once."""
    pixels = [p.model_copy(update={"delay_ms": delays[i], "fade_ms": EDGE_FADE_MS} if i in delays else {})
              for i, p in enumerate(targets)]
    return _frame(pixels, duration_ms, Transition(type="custom"))


def rise(pct: int, color: str, remaining_ms: int) -> Sequence:
    """Thunder's rising pole: lit to `pct` now, then pixel by pixel to the top over `remaining_ms`.
    Starts with a cut so the unlit part is black whatever the strip showed before."""
    remaining_ms = max(MIN_DURATION_MS, min(remaining_ms, MAX_DURATION_MS - EDGE_FADE_MS))
    start = PIXEL_COUNT * max(0, min(100, pct)) // 100
    todo = PIXEL_COUNT - start
    delays = {i: (i - start) * remaining_ms // max(1, todo) for i in range(start, PIXEL_COUNT)}
    return Sequence(loop=True, steps=[
        _frame(_fill(pct, color), MIN_DURATION_MS),
        _custom(_fill(100, color), delays, remaining_ms + EDGE_FADE_MS),
        _frame(_fill(100, color)),
    ])


def pole_sequence(pole: Pole) -> Sequence:
    """One pole state as a looping preview (pct is from the bottom, index 0 = bottom)."""
    if pole.mode == "off" or pole.color is None:
        return Sequence(loop=True, steps=[_frame(_fill(0, BLACK))])
    color = _hex(pole.color)
    if pole.mode == "glow":
        return Sequence(loop=True, steps=[_frame(_fill(100, _hex(pole.color, pole.level or 100)))])
    if pole.mode in ("pulse", "blink"):
        # ponytail: the pulse effect lights the whole strip, so pct < 100 pulses full; the show only pulses full poles
        period = pole.ms or 750
        speed = max(0.25, min(4.0, 750 / period))  # the effect's period is 750 ms / speed
        return Sequence(loop=True, steps=[EffectStep(kind="effect", effect="pulse", speed=speed, colors=[color],
                                                     duration_ms=min(MAX_DURATION_MS, max(MIN_DURATION_MS, period * 20)))])
    if pole.mode == "drain":
        ms = max(MIN_DURATION_MS, min(pole.ms or 1000, MAX_DURATION_MS - EDGE_FADE_MS))
        lit = PIXEL_COUNT * max(0, min(100, pole.pct)) // 100
        delays = {i: (lit - 1 - i) * ms // max(1, lit) for i in range(lit)}  # the top goes first
        return Sequence(loop=True, steps=[
            _frame(_fill(pole.pct, color), MIN_DURATION_MS),
            _custom(_fill(0, BLACK), delays, ms + EDGE_FADE_MS),
            _frame(_fill(0, BLACK)),
        ])
    return Sequence(loop=True, steps=[_frame(_fill(pole.pct, color))])


def plan(event: ShowEvent) -> dict[str, tuple[tuple, Sequence] | None]:
    """Per side: (key, sequence) to show, or None = no show look (the pillar's own slots). The key
    changes only when the look does, so thunder's per-percent events do not restart the rise."""
    if event.state == "idle":
        return {"L": None, "R": None}
    out = {}
    for side in ("L", "R"):
        pole = getattr(event.poles, side)
        th = event.thunder
        if th and th.phase == "cooldown" and side != th.performer and pole.mode == "solid":
            remaining = (100 - pole.pct) * tunables.get("cooldownMs") // 100
            out[side] = (("rise", pole.color), rise(pole.pct, _hex(pole.color), remaining))
        else:
            key = tuple(sorted(pole.model_dump().items()))
            out[side] = (key, pole_sequence(pole))
    return out


class PoleState:
    """The show preview per side. Ids share one counter with nothing else on the pillar: the editor's
    own preview takes priority (see the player state and preview.bin routes)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        self._last_id = 1_000_000  # above the editor preview's ids, so the two never collide
        self._sides: dict[str, tuple[tuple, int, bytes, Sequence] | None] = {"L": None, "R": None}  # key, id, file
        self._pillar_by_ip: dict[str, int] = {}

    def apply(self, event: ShowEvent) -> None:
        for side, wanted in plan(event).items():
            with self._lock:
                current = self._sides[side]
                if wanted is None:
                    self._sides[side] = None
                elif current is None or current[0] != wanted[0]:
                    self._publish(side, wanted[0], wanted[1])

    def _publish(self, side: str, key: tuple, sequence: Sequence) -> None:
        self._last_id += 1
        self._sides[side] = (key, self._last_id, compile_sequence(sequence, self._last_id), sequence)

    def replay(self, side: str) -> None:
        """A press on the pillar ends its preview locally: send the same look again under a new id."""
        with self._lock:
            current = self._sides[side]
            if current:
                self._publish(side, current[0], current[3])

    def seen(self, pillar_id: int, ip: str | None) -> None:
        if ip and pillar_id in SIDE_BY_PILLAR:
            with self._lock:
                self._pillar_by_ip[ip] = pillar_id

    def pillar_at(self, ip: str | None) -> int | None:
        return self._pillar_by_ip.get(ip) if ip else None

    def current_id(self, pillar_id: int | None) -> int:
        current = self._sides.get(SIDE_BY_PILLAR.get(pillar_id))
        return current[1] if current else 0

    def binary(self, pillar_id: int | None) -> bytes | None:
        current = self._sides.get(SIDE_BY_PILLAR.get(pillar_id))
        return current[2] if current else None


poles = PoleState()
