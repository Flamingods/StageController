from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.features.buttons import router as buttons
from app.features.pillar import service
from app.features.pillar.compiler import bake_frame
from app.features.pillar.poles import pole_sequence, poles, rise
from app.features.pillar.router import router as pillar_router
from app.features.player import router as player_router
from app.features.show import events, tunables
from app.features.show.schemas import Pole, Poles, ShowEvent, ThunderInfo

PINK = "#%02X%02X%02X" % tunables.palette("pink")


def lit_at(step, t_ms: int) -> list[bool]:
    """Pixels fully at a non-black target by t (the ESP's frame rule: hold until delay, then fade)."""
    return [(p.r or p.g or p.b) > 0 and t_ms >= p.delay_ms + p.fade_ms for p in bake_frame(step)]


def thunder_event(rival_pct: int, phase="cooldown") -> ShowEvent:
    rival = Pole(pct=rival_pct, color="blue", mode="solid") if phase == "cooldown" else \
        Pole(pct=100, color="blue", mode="pulse", ms=500)
    return ShowEvent(timestamp=datetime.now(), state="playing", game="thunder",
                     poles=Poles(L=Pole(pct=100, color="lime", mode="solid"), R=rival),
                     thunder=ThunderInfo(phase=phase, performer="L", pct=rival_pct))


@pytest.fixture(autouse=True)
def fresh():
    poles.reset()
    service.preview.clear()


def test_launch_fill_lights_the_bottom_third():
    step = pole_sequence(events.launch_pole(1)).steps[0]
    lit = lit_at(step, 0)
    assert lit[:33] == [True] * 33 and not any(lit[33:])
    assert bake_frame(step)[0].r == int(PINK[1:3], 16)


def test_rise_climbs_from_pct_to_the_top_over_the_remaining_cooldown():
    seq = rise(0, PINK, 20000)
    climb = seq.steps[1]
    assert sum(lit_at(climb, 10000 + 150)) == pytest.approx(50, abs=1)
    assert all(lit_at(climb, 20000 + 150))
    started = rise(40, PINK, 12000).steps[1]
    assert lit_at(started, 0)[:40] == [True] * 40 and not lit_at(started, 0)[40]


def test_thunder_per_percent_events_keep_one_preview_until_the_phase_changes():
    poles.apply(thunder_event(1))
    first = poles.current_id(2)
    for pct in range(2, 60):
        poles.apply(thunder_event(pct))
    assert poles.current_id(2) == first  # the rise runs on the ESP, not restarted every percent
    poles.apply(thunder_event(100, phase="ready"))
    assert poles.current_id(2) != first


def test_idle_hands_the_pillars_back_to_their_own_slots():
    poles.apply(events.launching({"L": events.launch_pole(1)}))
    assert poles.current_id(1) and poles.current_id(2)  # L lit, R explicitly off
    poles.apply(events.idle())
    assert poles.current_id(1) == 0 and poles.current_id(2) == 0


def test_replay_gives_the_same_look_a_new_id():
    poles.apply(events.launching({"L": events.launch_pole(2)}))
    before, data = poles.current_id(1), poles.binary(1)
    poles.replay("L")
    assert poles.current_id(1) > before
    assert poles.binary(1)[16:] == data[16:]  # same steps; only the header (id, crc) is new


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    class FakePlayer:
        def get_state(self):
            return {"current_song": None}

    monkeypatch.setattr(player_router, "player", FakePlayer())
    app = FastAPI()
    for r in (pillar_router, player_router.router, buttons.router):
        app.include_router(r, prefix="/api")
    app.dependency_overrides[get_db] = db
    return TestClient(app)  # requests come from "testclient"


def test_each_pillar_polls_and_fetches_its_own_pole(client):
    poles.apply(events.launching({"L": events.launch_pole(3)}))
    poll = client.get("/api/player/state?client=pillar&pillar_id=1&running_version=0").json()
    assert poll["pillar_preview_id"] == poles.current_id(1)
    assert client.get("/api/pillar/preview.bin").content == poles.binary(1)
    client.get("/api/player/state?client=pillar&pillar_id=2&running_version=0")  # same address, now pillar 2
    assert client.get("/api/pillar/preview.bin").content == poles.binary(2)


def test_the_editor_preview_wins_over_the_show(client):
    poles.apply(events.launching({"L": events.launch_pole(1)}))
    draft = {"loop": True, "steps": [{"kind": "effect", "effect": "solid", "duration_ms": 500, "colors": ["#123456"]}]}
    editor_id = client.post("/api/pillar/preview", json=draft).json()["preview_id"]
    poll = client.get("/api/player/state?client=pillar&pillar_id=1").json()
    assert poll["pillar_preview_id"] == editor_id


def test_a_pillar_press_is_side_aware(client, monkeypatch):
    from app.features.show import service as show
    seen = []

    async def on_press(action, side, *a, **k):
        seen.append((action, side))
        return {"status": "ok"}

    monkeypatch.setattr(show.director, "on_press", on_press)
    client.post("/api/buttons/press/claps?pillar_id=1")
    client.post("/api/buttons/press/start?pillar_id=2")
    assert seen == [("claps", "L"), ("start", "R")]
