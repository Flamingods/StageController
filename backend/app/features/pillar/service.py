import threading
import time

from sqlalchemy.orm import Session

from .compiler import compile_sequence
from .models import PillarMeta, PillarPlan
from .schemas import Sequence

PREVIEW_TTL_S = 60


def get_version(db: Session) -> int:
    meta = db.get(PillarMeta, 1)
    return meta.plans_version if meta else 0


def _bump_version(db: Session) -> int:
    meta = db.get(PillarMeta, 1)
    if meta is None:
        meta = PillarMeta(id=1, plans_version=0)
        db.add(meta)
    meta.plans_version += 1
    return meta.plans_version


def list_plans(db: Session, slots: tuple[str, ...]) -> dict[str, dict | None]:
    saved = {p.slot: p.data for p in db.query(PillarPlan).all()}
    return {slot: saved.get(slot) for slot in slots}


def save_plan(db: Session, slot: str, sequence: Sequence) -> int:
    plan = db.get(PillarPlan, slot)
    data = sequence.model_dump()
    if plan:
        plan.data = data
    else:
        db.add(PillarPlan(slot=slot, data=data))
    version = _bump_version(db)
    db.commit()
    return version


def reset_plan(db: Session, slot: str) -> int:
    plan = db.get(PillarPlan, slot)
    if plan:
        db.delete(plan)
    version = _bump_version(db)
    db.commit()
    return version


def plan_binary(db: Session, slot: str) -> bytes | None:
    plan = db.get(PillarPlan, slot)
    if not plan:
        return None
    return compile_sequence(Sequence.model_validate(plan.data), get_version(db))


class PreviewState:
    """The unsaved draft playing on the pillar. Kept in memory; ids never repeat within a run."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last_id = 0
        self._clear()

    def _clear(self):
        self._id = 0
        self._data: bytes | None = None
        self._expires_at = 0.0

    def clear(self):
        with self._lock:
            self._clear()

    def start(self, sequence: Sequence) -> int:
        with self._lock:
            self._last_id += 1
            self._id = self._last_id
            self._data = compile_sequence(sequence, self._id)
            self._expires_at = time.monotonic() + PREVIEW_TTL_S
            return self._id

    def _expire(self):
        if self._id and time.monotonic() >= self._expires_at:
            self._clear()

    def current_id(self) -> int:
        with self._lock:
            self._expire()
            return self._id

    def binary(self) -> bytes | None:
        with self._lock:
            self._expire()
            return self._data


class PillarStatus:
    """Per side (L/R): when that pillar last polled the player state and which plans version it runs."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._sides: dict[str, tuple[float, int | None]] = {}

    def record_poll(self, side: str, running_version: int | None):
        self._sides[side] = (time.monotonic(), running_version)

    def snapshot(self) -> dict:
        """Only sides that have polled; the editor shows the others as "not seen"."""
        now = time.monotonic()
        return {
            side: {"seen_s_ago": now - seen_at, "running_version": version}
            for side, (seen_at, version) in sorted(self._sides.items())
        }


preview = PreviewState()
pillar_status = PillarStatus()
