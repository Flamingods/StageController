import struct

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.features.pillar import programs, service
from app.features.pillar.router import router

SEQ = {"loop": True, "steps": [{"kind": "effect", "effect": "solid", "duration_ms": 500, "colors": ["#123456"]}]}
FRAME = {"kind": "frame", "duration_ms": 1000, "transition": {"type": "cut"},
         "pixels": [{"color": "#FFFFFF"}] * 100}


@pytest.fixture
def sent(monkeypatch):
    """WebSocket broadcasts captured instead of sent."""
    messages = []

    async def fake_broadcast(message: dict):
        messages.append(message)

    monkeypatch.setattr(programs, "broadcast", fake_broadcast)
    return messages


@pytest.fixture
def client(sent):
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


def create(client, name="Rainbow wave", seq=SEQ):
    res = client.post("/api/pillar/programs", json={"name": name, "sequence": seq})
    assert res.status_code == 200, res.text
    return res.json()


# ---- library ---------------------------------------------------------------------

def test_empty_library(client):
    assert client.get("/api/pillar/programs").json() == {"version": 0, "programs": []}
    assert client.get("/api/pillar/programs/index").json() == {"version": 0, "ids": []}


def test_create_assigns_lowest_free_id_and_bumps_version(client):
    a = create(client, "A")
    b = create(client, "B")
    assert (a["id"], b["id"]) == (1, 2)
    assert b["version"] == 2
    client.delete("/api/pillar/programs/1")
    assert create(client, "C")["id"] == 1


def test_list_returns_name_sequence_and_size(client):
    create(client, "Wave")
    [p] = client.get("/api/pillar/programs").json()["programs"]
    assert p["id"] == 1 and p["name"] == "Wave"
    assert p["sequence"]["steps"][0]["colors"] == ["#123456"]
    assert p["size"] == 16 + 16  # header + one effect step


def test_update_changes_program_and_bumps_version(client):
    create(client)
    res = client.put("/api/pillar/programs/1", json={"name": "Renamed", "sequence": {**SEQ, "loop": False}})
    assert res.status_code == 200 and res.json()["version"] == 2
    [p] = client.get("/api/pillar/programs").json()["programs"]
    assert p["name"] == "Renamed" and p["sequence"]["loop"] is False


def test_update_or_delete_unknown_program_is_404(client):
    assert client.put("/api/pillar/programs/9", json={"name": "x", "sequence": SEQ}).status_code == 404
    assert client.delete("/api/pillar/programs/9").status_code == 404


def test_name_is_required(client):
    assert client.post("/api/pillar/programs", json={"name": "  ", "sequence": SEQ}).status_code == 422


def test_invalid_sequence_is_rejected(client):
    bad = {"steps": [{"kind": "effect", "effect": "lasers", "duration_ms": 500}]}
    assert client.post("/api/pillar/programs", json={"name": "x", "sequence": bad}).status_code == 422
    assert client.get("/api/pillar/programs/index").json()["version"] == 0


def test_at_most_24_programs(client):
    for i in range(programs.MAX_PROGRAMS):
        create(client, f"P{i}")
    res = client.post("/api/pillar/programs", json={"name": "one too many", "sequence": SEQ})
    assert res.status_code == 422 and "24" in res.text


def test_library_total_size_limit(client, monkeypatch):
    monkeypatch.setattr(programs, "MAX_LIBRARY_BYTES", 2000)
    big = {"loop": False, "steps": [FRAME, FRAME]}  # 16 + 2 * 703 bytes
    create(client, "big", big)
    res = client.post("/api/pillar/programs", json={"name": "big2", "sequence": big})
    assert res.status_code == 422 and "library" in res.text.lower()
    # Editing the existing program in place is measured without its old size
    assert client.put("/api/pillar/programs/1", json={"name": "big", "sequence": big}).status_code == 200


def test_index_and_binary_for_the_esp(client):
    create(client, "A")
    create(client, "B")
    client.delete("/api/pillar/programs/1")
    index = client.get("/api/pillar/programs/index").json()
    assert index == {"version": 3, "ids": [2]}
    res = client.get("/api/pillar/programs/2.bin")
    assert res.status_code == 200 and res.headers["content-type"] == "application/octet-stream"
    magic, version, loop, count = struct.unpack_from("<4sIBB", res.content)
    assert (magic, version, loop, count) == (b"PLP1", 3, 1, 1)  # header carries the programs version
    assert client.get("/api/pillar/programs/1.bin").status_code == 404


def test_programs_version_does_not_touch_plans_version(client):
    create(client)
    assert client.get("/api/pillar/plans").json()["version"] == 0


# ---- commands --------------------------------------------------------------------

def test_command_both_sides_shares_one_seq_and_broadcasts_per_side(client, sent):
    create(client)
    res = client.post("/api/pillar/command", json={"sides": ["L", "R"], "program": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["seq"] == 1
    assert body["commands"] == {"L": {"seq": 1, "program": 1}, "R": {"seq": 1, "program": 1}}
    assert sent == [
        {"action": "pillar_command", "side": "L", "seq": 1, "program": 1},
        {"action": "pillar_command", "side": "R", "seq": 1, "program": 1},
    ]


def test_seq_only_grows_and_release_is_program_zero(client):
    create(client)
    client.post("/api/pillar/command", json={"sides": ["L"], "program": 1})
    body = client.post("/api/pillar/command", json={"sides": ["L"], "program": 0}).json()
    assert body["seq"] == 2
    assert body["commands"]["L"] == {"seq": 2, "program": 0}


def test_one_side_command_leaves_the_other_alone(client):
    create(client)
    create(client, "B")
    client.post("/api/pillar/command", json={"sides": ["L", "R"], "program": 1})
    body = client.post("/api/pillar/command", json={"sides": ["R"], "program": 2}).json()
    assert body["commands"] == {"L": {"seq": 1, "program": 1}, "R": {"seq": 2, "program": 2}}


def test_command_for_unknown_program_or_side_is_rejected(client, sent):
    assert client.post("/api/pillar/command", json={"sides": ["L"], "program": 7}).status_code == 422
    create(client)
    assert client.post("/api/pillar/command", json={"sides": ["X"], "program": 1}).status_code == 422
    assert client.post("/api/pillar/command", json={"sides": [], "program": 1}).status_code == 422
    assert sent == []


def test_deleting_a_commanded_program_releases_those_sides(client, sent):
    create(client)
    create(client, "B")
    client.post("/api/pillar/command", json={"sides": ["L"], "program": 1})
    client.post("/api/pillar/command", json={"sides": ["R"], "program": 2})
    client.delete("/api/pillar/programs/1")
    status = client.get("/api/pillar/status").json()
    assert status["commands"]["L"] == {"seq": 3, "program": 0}
    assert status["commands"]["R"] == {"seq": 2, "program": 2}
    assert sent[-1] == {"action": "pillar_command", "side": "L", "seq": 3, "program": 0}


def test_status_reports_programs_version_commands_and_unseen_sides(client):
    create(client)
    client.post("/api/pillar/command", json={"sides": ["R"], "program": 1})
    status = client.get("/api/pillar/status").json()
    assert status["programs_version"] == 1
    assert status["commands"] == {"L": {"seq": 0, "program": 0}, "R": {"seq": 1, "program": 1}}


# ---- the pillar's poll (backup channel) -------------------------------------------

@pytest.fixture
def state_client(client):
    from app.features.player.router import router as player_router
    client.app.include_router(player_router, prefix="/api")
    return client


def test_pillar_poll_carries_its_sides_command_and_programs_version(state_client):
    create(state_client)
    state_client.post("/api/pillar/command", json={"sides": ["L"], "program": 1})
    left = state_client.get("/api/player/state", params={"client": "pillar", "side": "L"}).json()
    right = state_client.get("/api/player/state", params={"client": "pillar", "side": "R"}).json()
    assert left["pillar_command"] == {"seq": 1, "program": 1}
    assert right["pillar_command"] == {"seq": 0, "program": 0}
    assert left["pillar_programs_version"] == 1


def test_browser_state_poll_has_no_pillar_command(state_client):
    assert "pillar_command" not in state_client.get("/api/player/state").json()


def test_status_reports_the_show_state(client, monkeypatch):
    from app.features.show import service as show
    assert client.get("/api/pillar/status").json()["show_state"] == "idle"
    monkeypatch.setattr(show.director, "state", "playing")
    assert client.get("/api/pillar/status").json()["show_state"] == "playing"
