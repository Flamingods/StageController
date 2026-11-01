"""Pillar LED sequence format (see docs/pillar-led-contract.md §3)."""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

PIXEL_COUNT = 100
MAX_STEPS = 64
MIN_DURATION_MS = 50
MAX_DURATION_MS = 60000

EffectName = Literal["off", "solid", "rainbow", "comet", "fill", "sparkle", "pulse", "band", "fade", "snake", "stripes"]
Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
DurationMs = Annotated[int, Field(ge=MIN_DURATION_MS, le=MAX_DURATION_MS)]
TimingMs = Annotated[int, Field(ge=0, le=MAX_DURATION_MS)]
Level = Annotated[int, Field(ge=0, le=255)]


class EffectStep(BaseModel):
    kind: Literal["effect"]
    effect: EffectName
    duration_ms: DurationMs
    brightness: Level = 255
    direction: Literal["up", "down", "bounce"] = "up"
    speed: Annotated[float, Field(ge=0.25, le=4.0)] = 1.0
    colors: Annotated[list[Color], Field(max_length=3)] = []


class Pixel(BaseModel):
    color: Color
    brightness: Level = 255
    # Used only by the "custom" transition
    fade_ms: TimingMs = 0
    delay_ms: TimingMs = 0


class Transition(BaseModel):
    type: Literal["cut", "crossfade", "wipe", "custom"] = "cut"
    ms: TimingMs = 0
    direction: Literal["up", "down"] = "up"


class FrameStep(BaseModel):
    kind: Literal["frame"]
    duration_ms: DurationMs
    transition: Transition = Transition()
    pixels: Annotated[list[Pixel], Field(min_length=PIXEL_COUNT, max_length=PIXEL_COUNT)]


Step = Annotated[Union[EffectStep, FrameStep], Field(discriminator="kind")]


class Sequence(BaseModel):
    loop: bool = False
    steps: Annotated[list[Step], Field(min_length=1, max_length=MAX_STEPS)]

    @model_validator(mode="after")
    def check_frame_timing(self):
        for n, step in enumerate(self.steps, start=1):
            if not isinstance(step, FrameStep):
                continue
            t = step.transition
            if t.type in ("crossfade", "wipe") and t.ms > step.duration_ms:
                raise ValueError(
                    f"Step {n}: {t.type} time ({t.ms} ms) is longer than the step ({step.duration_ms} ms)"
                )
            if t.type == "custom":
                for i, px in enumerate(step.pixels):
                    total = px.delay_ms + px.fade_ms
                    if total > step.duration_ms:
                        raise ValueError(
                            f"Step {n}: LED {i + 1} delay + fade ({total} ms) is longer than "
                            f"the step ({step.duration_ms} ms)"
                        )
        return self
