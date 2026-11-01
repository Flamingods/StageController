"""The ESP's built-in sequences (StagePillar lib/pillar/pillar_player.cpp is the source of truth).

A slot with no saved plan plays these; the editor shows them as each slot's starting point.
"""

SLOTS = ("idle", "start", "claps", "special", "skip", "stop")


def _effect(effect: str, duration_ms: int, colors: list[str] | None = None,
            direction: str = "up", speed: float = 1.0) -> dict:
    return {"kind": "effect", "effect": effect, "duration_ms": duration_ms, "brightness": 255,
            "direction": direction, "speed": speed, "colors": colors or []}


DEFAULT_SEQUENCES: dict[str, dict] = {
    # Rainbow segments with dark gaps flowing up; 256 LEDs of shift × 80 ms, so the loop seam is invisible
    "idle": {"loop": True, "steps": [_effect("stripes", 20480)]},
    "start": {"loop": True, "steps": [
        _effect("comet", 2100, ["#FF00C0", "#00E5FF", "#FFB000"], direction="bounce", speed=1.5)]},
    "claps": {"loop": False, "steps": [_effect("sparkle", 1200, ["#FFFFFF"])]},
    "special": {"loop": False, "steps": [_effect("pulse", 1500, ["#0000FF", "#8000FF", "#FF00C0"])]},
    "skip": {"loop": False, "steps": [_effect("band", 500, ["#00FFFF"])]},
    "stop": {"loop": False, "steps": [_effect("fade", 1500, ["#FF0000", "#280000"])]},
}
