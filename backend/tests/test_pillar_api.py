import struct

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.features.pillar import service
from app.features.pillar.defaults import DEFAULT_SEQUENCES
from app.features.pillar.router import router

SEQ = {"loop": True, "steps": [{"kind": "effect", "effect": "solid", "duration_ms": 500, "colors": ["#123456"]}]}


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

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = db
    service.preview.clear()
    service.pillar_status.reset()
    return TestClient(app)


def version_of(client) -> int:
    return client.get("/api/pillar/plans").json()["version"]


def test_fresh_install_has_no_plans(client):
    body = client.get("/api/pillar/plans").json()
    assert body["version"] == 0
    assert body["slots"] == {s: None for s in DEFAULT_SEQUENCES}


def test_defaults_endpoint_serves_esp_defaults(client):
    assert client.get("/api/pillar/plans/defaults").json() == DEFAULT_SEQUENCES


def test_save_stores_plan_and_bumps_version(client):
    res = client.put("/api/pillar/plans/start", json=SEQ)
    assert res.status_code == 200 and res.json()["version"] == 1
    saved = client.get("/api/pillar/plans").json()["slots"]["start"]
    assert saved["loop"] is True and saved["steps"][0]["colors"] == ["#123456"]


def test_save_rejects_invalid_sequence_without_bumping(client):
    bad = {"steps": [{"kind": "effect", "effect": "lasers", "duration_ms": 500}]}
    assert client.put("/api/pillar/plans/start", json=bad).status_code == 422
    assert version_of(client) == 0


def test_unknown_slot_is_404(client):
    assert client.put("/api/pillar/plans/encore", json=SEQ).status_code == 404
    assert client.get("/api/pillar/plans/encore.bin").status_code == 404


def test_reset_removes_plan_and_bumps_version(client):
    client.put("/api/pillar/plans/claps", json=SEQ)
    res = client.delete("/api/pillar/plans/claps")
    assert res.status_code == 200 and res.json()["version"] == 2
    assert client.get("/api/pillar/plans").json()["slots"]["claps"] is None


def test_bin_for_saved_slot(client):
    client.put("/api/pillar/plans/skip", json=SEQ)
    res = client.get("/api/pillar/plans/skip.bin")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/octet-stream"
    magic, version, loop, count = struct.unpack_from("<4sIBB", res.content)
    assert (magic, version, loop, count) == (b"PLP1", 1, 1, 1)


def test_bin_for_default_slot_is_404(client):
    assert client.get("/api/pillar/plans/idle.bin").status_code == 404


def test_bin_header_carries_current_version(client):
    client.put("/api/pillar/plans/skip", json=SEQ)
    client.put("/api/pillar/plans/stop", json=SEQ)
    _, version = struct.unpack_from("<4sI", client.get("/api/pillar/plans/skip.bin").content)
    assert version == 2


def test_preview_lifecycle(client):
    assert client.get("/api/pillar/preview.bin").status_code == 404
    pid = client.post("/api/pillar/preview", json=SEQ).json()["preview_id"]
    assert pid > 0
    res = client.get("/api/pillar/preview.bin")
    assert res.status_code == 200
    assert struct.unpack_from("<4sI", res.content)[1] == pid
    assert client.post("/api/pillar/preview", json=SEQ).json()["preview_id"] == pid + 1
    client.delete("/api/pillar/preview")
    assert client.get("/api/pillar/preview.bin").status_code == 404
    assert service.preview.current_id() == 0


def test_preview_rejects_invalid(client):
    assert client.post("/api/pillar/preview", json={"steps": []}).status_code == 422
    assert service.preview.current_id() == 0


def test_preview_expires(client, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: now[0])
    client.post("/api/pillar/preview", json=SEQ)
    now[0] += service.PREVIEW_TTL_S - 1
    assert service.preview.current_id() != 0
    now[0] += 2
    assert service.preview.current_id() == 0
    assert client.get("/api/pillar/preview.bin").status_code == 404


def test_status_reports_each_side_that_polled(client, monkeypatch):
    now = [500.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: now[0])
    body = client.get("/api/pillar/status").json()
    assert (body["plans_version"], body["preview_id"], body["pillars"]) == (0, 0, {})
    service.pillar_status.record_poll("R", running_version=3)
    now[0] += 4
    pillars = client.get("/api/pillar/status").json()["pillars"]
    assert list(pillars) == ["R"]
    assert pillars["R"]["seen_s_ago"] == pytest.approx(4)
    assert pillars["R"]["running_version"] == 3
    service.pillar_status.record_poll("L", running_version=2)
    pillars = client.get("/api/pillar/status").json()["pillars"]
    assert pillars["L"] == {"seen_s_ago": pytest.approx(0), "running_version": 2}
    assert pillars["R"]["running_version"] == 3


@pytest.fixture
def state_client(client):
    from app.features.player.router import router as player_router
    client.app.include_router(player_router, prefix="/api")
    return client


def test_player_state_includes_pillar_fields(state_client):
    state_client.put("/api/pillar/plans/start", json=SEQ)
    pid = state_client.post("/api/pillar/preview", json=SEQ).json()["preview_id"]
    state = state_client.get("/api/player/state").json()
    assert state["pillar_plans_version"] == 1
    assert state["pillar_preview_id"] == pid
    assert state["show_palette_version"] > 0
    assert "current_song" in state


def test_player_state_poll_from_pillar_is_recorded_per_side(state_client):
    state_client.get("/api/player/state")
    assert service.pillar_status.snapshot() == {}
    state_client.get("/api/player/state", params={"client": "pillar", "side": "R", "running_version": 5})
    snap = service.pillar_status.snapshot()
    assert list(snap) == ["R"] and snap["R"]["running_version"] == 5 and snap["R"]["seen_s_ago"] < 1


def test_pillar_poll_without_side_counts_as_right(state_client):
    # Firmware from before the two-pillar change sends no side; that board is the right pillar
    state_client.get("/api/player/state", params={"client": "pillar", "running_version": 1})
    assert list(service.pillar_status.snapshot()) == ["R"]


def test_pillar_poll_with_unknown_side_is_rejected(state_client):
    res = state_client.get("/api/player/state", params={"client": "pillar", "side": "X"})
    assert res.status_code == 422
    assert service.pillar_status.snapshot() == {}
