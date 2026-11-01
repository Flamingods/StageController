"""Whole songs, headless and instantly (design D5): a fake clock and a fake player whose song time
runs with the clock play the fixture song from the launch presses to the song's end, through the
real director, the real event builders and the real JSONL log."""
import asyncio
import json
from itertools import groupby
from pathlib import Path

import pytest

from app.features.show import analytics, tunables
from app.features.show.service import ShowDirector, SongStatus
from app.features.show.songmap import SongMap

FIXTURE = Path(__file__).parent / "fixtures" / "its_only_love.analysis.json"
DURATION_MS = 290_551
STEP = 20


class Clock:
    t = 0

    def now_ms(self):
        return self.t


class SongPlayer:
    """Plays the fixture song: song time is the clock since start_game, gone at the end."""

    def __init__(self, clock):
        self.clock, self.started_ms, self.actions = clock, None, []

    async def start_game(self, game):
        self.started_ms = self.clock.t
        return 1

    def status(self):
        if self.started_ms is None or self.clock.t - self.started_ms >= DURATION_MS:
            return None
        return SongStatus(1, (self.clock.t - self.started_ms) / 1000, DURATION_MS / 1000)

    def song_map(self):
        return SongMap.load(FIXTURE)

    async def run_action(self, action):
        self.actions.append(action)

    async def apply_scene(self, label):
        pass


@pytest.fixture(autouse=True)
def jsonl(tmp_path, monkeypatch):
    tunables.clear_overrides()
    monkeypatch.setattr(analytics, "PATH", tmp_path / "show-events.jsonl")
    yield tmp_path / "show-events.jsonl"
    tunables.clear_overrides()


def run(launch, script=()):
    """launch: [(action, side, ago)] pressed at clock 0; script: [(song_t, action, side, ago)]."""
    clock = Clock()
    player = SongPlayer(clock)
    events = []

    async def emit(event):
        if event.action == "show":
            events.append(event)

    director = ShowDirector(player, clock, emit, analytics.append)

    async def main():
        for action, side, ago in launch:
            await director.on_press(action, side, ago)
        pending = list(script)
        while clock.t < DURATION_MS + 10_000:
            clock.t += STEP
            status = player.status()
            if pending and status and status.t >= pending[0][0]:
                _, action, side, ago = pending.pop(0)
                await director.on_press(action, side, ago)
            await director.tick()
            if director.state == "idle":
                return

    asyncio.run(main())
    assert director.state == "idle" and player.started_ms is not None
    return events, player


def lines(path):
    return [json.loads(l) for l in path.read_text().splitlines()]


def states(events):
    return [k for k, _ in groupby((e.state, e.step) for e in events)]


def playing(events):
    return [e for e in events if e.state == "playing"]


EXPECTED_STATES = [("launching", None), ("intro", 3), ("intro", 2), ("intro", 1), ("playing", None), ("idle", None)]
SECTIONS = [("intro", 1), ("instrumental", 1), ("verse", 1), ("instrumental", 2), ("verse", 2), ("chorus", 1),
            ("instrumental", 3), ("bridge", 1), ("instrumental", 4), ("chorus", 2), ("verse", 3), ("chorus", 3),
            ("outro", 1)]


def check_log(path, game, count, extra=()):
    log = lines(path)
    assert [l["type"] for l in log] == ["launch_attempt", "song_start", *[e["type"] for e in extra], "song_end"]
    assert log[0]["countL"] + log[0]["countR"] == count and log[0]["result"] == game
    assert log[1] == {**log[1], "songId": "1", "game": game, "bpm": 103.4, "hasSections": True, "hasBeats": True}
    for line, want in zip(log[2:-1], extra):
        assert {k: line[k] for k in want} == want
    end = log[-1]
    assert (end["reason"], end["game"]) == ("finished", game)
    assert end["playedMs"] == pytest.approx(DURATION_MS, abs=STEP) and end["atMs"] == pytest.approx(DURATION_MS, abs=STEP)
    monos = [l["mono"] for l in log]
    assert monos == sorted(monos)
    return log


def test_solo_whole_song(jsonl):
    events, player = run([("start", "R", 0)])
    # one pillar: no 3-2-1, the song starts as soon as the launch is decided
    assert states(events) == [("launching", None), ("playing", None), ("idle", None)]
    assert [(e.song.section, e.song.section_index) for e in playing(events)] == SECTIONS
    assert all(e.turn is None and e.thunder is None for e in playing(events))
    check_log(jsonl, "solo", 1)
    assert player.actions == []


def test_duet_whole_song(jsonl):
    events, _ = run([("start", "L", 0), ("start", "R", 80)])
    assert states(events) == EXPECTED_STATES
    assert all(e.poles.L.color == e.poles.R.color == "pink" for e in events if e.state == "intro")
    assert [(e.song.section, e.song.section_index) for e in playing(events)] == SECTIONS
    log = check_log(jsonl, "duet", 2)
    assert log[0]["gapMs"] == 80


def test_showoff_whole_song(jsonl):
    events, _ = run([("claps", "L", 0), ("claps", "R", 30)])
    assert states(events) == EXPECTED_STATES
    changes = [(turn, next(group).song.t) for turn, group in groupby(playing(events), key=lambda e: e.turn)]
    assert [turn for turn, _ in changes] == ["both", "L", "both", "R", "both", "L", "both"]
    assert [t for turn, t in changes if turn != "both"] == pytest.approx([66.04, 104.77, 194.49], abs=0.021)
    check_log(jsonl, "showoff", 4)


def thunder_phases(events):
    """(phase, performer) as they change: the steal loop, time-based."""
    return [k for k, _ in groupby((e.thunder.phase, e.thunder.performer) for e in playing(events) if e.thunder)]


def first(events, phase, performer):
    return next(e for e in playing(events) if e.thunder and (e.thunder.phase, e.thunder.performer) == (phase, performer))


THUNDER = [("special", "L", 0), ("special", "R", 40)]
C = tunables.defaults()["cooldownMs"] / 1000  # seconds; the single source is spec.json


def test_thunder_whole_song_with_steals(jsonl):
    # right steals once its pole is full; left steals back once the cooldown has run again
    events, player = run(THUNDER, script=[(C + 5, "start", "R", 0), (2 * C + 10, "start", "L", 0)])
    assert states(events) == EXPECTED_STATES
    assert [e.perimeter.side for e in events if e.state == "intro"] == ["L", "R", "centre"]
    assert thunder_phases(events) == [("cooldown", "L"), ("ready", "L"), ("steal", "R"), ("cooldown", "R"),
                                      ("ready", "R"), ("steal", "L"), ("cooldown", "L"), ("ready", "L")]
    # the cooldown restarts after a steal: from 0 once the blackout is over, full cooldownMs later
    restart = first(events, "cooldown", "R")
    assert restart.thunder.pct == 0 and restart.song.t == pytest.approx(C + 5.3, abs=0.03)
    assert first(events, "ready", "R").song.t == pytest.approx(2 * C + 5.3, abs=0.03)
    assert (restart.poles.R.color, restart.poles.R.pct, restart.poles.L.color, restart.poles.L.pct) == ("blue", 100, "lime", 0)
    assert player.actions == ["special", "special"]  # a smoke puff per steal
    check_log(jsonl, "thunder", 6, extra=[
        {"type": "press", "side": "R", "kind": "steal"}, {"type": "steal", "from": "L", "to": "R"},
        {"type": "press", "side": "L", "kind": "steal"}, {"type": "steal", "from": "R", "to": "L"}])
    waited = [l["waitedMs"] for l in lines(jsonl) if l["type"] == "steal"]
    assert waited == [pytest.approx(5000, abs=40), pytest.approx(4700, abs=40)]


def test_thunder_whole_song_an_early_press_is_ignored(jsonl):
    events, player = run(THUNDER, script=[(C / 2, "start", "R", 0), (C * 0.8, "start", "L", 0)])
    assert thunder_phases(events) == [("cooldown", "L"), ("ready", "L")]  # left keeps the stage, no timeout
    assert player.actions == []
    check_log(jsonl, "thunder", 6, extra=[{"type": "press", "side": "R", "kind": "early"},
                                          {"type": "press", "side": "L", "kind": "ordinary"}])  # the performer's own pole


def test_thunder_whole_song_without_a_press(jsonl):
    events, _ = run(THUNDER)
    assert thunder_phases(events) == [("cooldown", "L"), ("ready", "L")]
    rising = [e.thunder.pct for e in playing(events) if e.thunder and e.thunder.phase == "cooldown"]
    assert rising == sorted(rising) and rising[0] == 0 and rising[-1] == 99
    ready = first(events, "ready", "L")
    assert ready.song.t == pytest.approx(C, abs=0.03)
    assert (ready.poles.R.mode, ready.poles.R.ms, ready.buttons.flicker) == ("pulse", 500, "R")
    check_log(jsonl, "thunder", 6)
