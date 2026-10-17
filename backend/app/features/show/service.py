"""ShowDirector: the show state machine (idle -> launching -> intro -> playing, or failing).

All time comes from the injected clock and the player behind a small adapter, so tests run
whole launches instantly without mpv or a database. The real adapter is StagePlayer.
"""
import asyncio
import time
from dataclasses import dataclass
from functools import partial

from app.features.buttons.rules import IDLE_TAPS, IN_SONG

from . import events, tunables
from .scene import scene_for
from . import analytics
from .launch import LaunchArbiter, LaunchResult
from .models import ShowTunable
from .schemas import Pole, ShowEvent
from .songmap import SongMap
from .thunder import Thunder

TICK_S = 0.02
# analytics press kind by in-song meaning (anything else is "ordinary")
PRESS_KIND = {"skip": "skip", "claps": "applause"}
INTRO_STEPS = tunables.SPEC["intro"]["steps"]


class Clock:
    def now_ms(self) -> int:
        return int(time.monotonic() * 1000)


@dataclass
class SongStatus:
    id: int
    t: float  # seconds into the song
    duration: float


class StagePlayer:
    """The real thing: game playlists, the existing button handlers and mpv."""

    async def start_game(self, game: str) -> int | None:
        from app.core.database import SessionLocal
        from app.features.buttons.router import handle_start_action
        from app.features.player.service import player

        # Always a fresh shuffle of this game's playlist, never a queue left by another one
        player.stop(advance_queue=False)
        player.clear_queue()
        db = SessionLocal()
        try:
            await handle_start_action(db, game)
        finally:
            db.close()
        return player.get_current_song_id()

    def status(self) -> SongStatus | None:
        from app.features.player.service import player
        state = player.get_state()
        song = state["current_song"]
        return SongStatus(song["id"], state["current_time"], state["duration"]) if song else None

    def song_map(self) -> SongMap:
        from app.core.config import MUSIC_DIR
        from app.core.database import SessionLocal
        from app.features.player.service import player
        from app.features.songs.models import Song

        db = SessionLocal()
        try:
            song = db.get(Song, player.get_current_song_id())
            return SongMap.for_audio(song.file_path, MUSIC_DIR) if song else SongMap(None, [], [])
        finally:
            db.close()

    async def run_action(self, action: str) -> None:
        from app.core.database import SessionLocal
        from app.features.buttons.router import perform

        db = SessionLocal()
        try:
            await perform(action, db)
        finally:
            db.close()


    async def apply_scene(self, section: str | None) -> None:
        """Switch the section's appliances (scene.SECTION_SCENE)."""
        from app.core.database import SessionLocal
        from app.features.devices.models import Device
        from app.features.devices.service import set_device_state, update_device_state

        db = SessionLocal()
        try:
            devices = db.query(Device).all()
            for name, on in scene_for(section, [d.name for d in devices]).items():
                device = next(d for d in devices if d.name == name)
                if device.is_on != on and await set_device_state(device.ip_address, on):
                    update_device_state(db, device.id, on)
        finally:
            db.close()


async def _broadcast(event) -> None:
    from app.features.buttons.router import manager
    from app.features.pillar.poles import poles
    if isinstance(event, ShowEvent):
        poles.apply(event)
    await manager.broadcast(event)


class ShowDirector:
    def __init__(self, player, clock, emit, log=None):
        self._player = player
        self._thunder: Thunder | None = None  # the steal loop, in a thunder song
        self._clock = clock
        self._emit = emit
        self._log_to = log
        self._map = SongMap(None, [], [])
        self._song_id: int | None = None
        self._song_started_ms = 0
        self._t = 0.0  # song time at the last tick
        self._key = None  # (section, turn, thunder frame key, owner) of the last playing event
        self._arbiter = LaunchArbiter()
        self._poles: dict[str, Pole] = {}
        self._timeline: list[tuple[int, object]] = []  # (due_ms, async callable), in due order
        self._background: set[asyncio.Task] = set()
        self.state = "idle"
        self.game: str | None = None

    async def on_press(self, action: str, side: str, first_press_ago_ms: int = 0, taps: int | None = None) -> dict:
        now = self._clock.now_ms()
        if self.state in ("idle", "launching"):
            if action == "stop":
                await self.to_idle()
                await self._player.run_action("stop")
            elif action in IDLE_TAPS:
                taps = taps or IDLE_TAPS[action]
                if not self._arbiter.on_gesture(side, taps, now - first_press_ago_ms, now):
                    return self._ignored(action, "late_press")
                self.state = "launching"
                self._poles[side] = events.launch_pole(taps)
                await self._emit(events.launching(self._poles))
            return self._ok(action, side)
        if action == "stop" and self.state in ("intro", "playing"):
            if self.state == "playing":
                self._log("press", side=side, kind="stop")
            await self.to_idle("stop")
            await self._player.run_action("stop")
            return self._ok(action, side)
        if self.state != "playing":
            return self._ignored(action, self.state)
        what = IN_SONG[action]
        if self._thunder and what == "tap":
            # the steal loop is time-based: the press counts when it arrives, not when it was made
            kind, fields = self._thunder.press(side, now)
            self._log("press", side=side, kind=kind if kind != "performer" else "ordinary")
            if kind != "steal":
                return {**self._ignored(action, "too_early" if kind == "early" else "performer"), **fields}
            self._log("steal", songId=str(self._song_id), **fields)
            self._background_run(self._player.run_action("special"))  # the smoke puff, off the tick
            if status := self._player.status():
                await self._follow(status)  # the blackout goes out now
            return self._ok(action, side)
        if what == "skip" and (status := self._player.status()) and status.t > self._map.skip_cutoff_s():
            self._log("press", side=side, kind="ordinary")
            return self._ignored(action, "after_cutoff")
        self._log("press", side=side, kind=PRESS_KIND.get(what, "ordinary"))
        if what == "tap":
            return self._ignored(action, "ordinary")
        if what == "claps":
            await self._emit(events.claps(side))
        await self._player.run_action(what)
        if what == "skip":
            await self._after_skip()
        return self._ok(action, side)

    async def tick(self) -> None:
        now = self._clock.now_ms()
        if self.state == "launching" and (result := self._arbiter.poll(now)):
            self._decide(result, now)
        while self._timeline and self._timeline[0][0] <= now:
            _, step = self._timeline.pop(0)
            await step()
        if self.state == "playing":
            if status := self._player.status():
                await self._follow(status)
            else:
                await self.to_idle()  # song ended or was stopped from somewhere else

    async def to_idle(self, reason: str = "finished") -> None:
        was_idle = self.state == "idle"
        self._end_song(reason)
        self._arbiter.reset()
        self._poles = {}
        self._timeline = []
        self.state = "idle"
        self.game = None
        if not was_idle:
            await self._emit(events.idle())

    async def run(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            try:
                await self.tick()
            except Exception as e:  # a broken tick must not end the show loop
                print(f"Show director tick failed: {e}")

    def _log(self, kind: str, /, **fields) -> None:
        if self._log_to:
            self._log_to(kind, self._clock.now_ms(), **fields)

    def _decide(self, result: LaunchResult, now: int) -> None:
        self._log("launch_attempt", countL=result.count_l, countR=result.count_r, gapMs=result.gap_ms, result=result.game)
        self._poles = {}
        if result.game == "fail":
            self._schedule_fail(now)
        else:
            self._schedule_intro(result, now)

    def _schedule_intro(self, result: LaunchResult, now: int) -> None:
        self.state, self.game = "intro", result.game
        step_ms = tunables.get("introStepMs")
        for i, count in enumerate(range(INTRO_STEPS, 0, -1)):
            self._timeline.append((now + i * step_ms, partial(self._emit, events.intro(result.game, count))))
        self._timeline.append((now + INTRO_STEPS * step_ms, self._start_song))

    def _schedule_fail(self, now: int) -> None:
        self.state = "failing"
        blink_ms = tunables.get("failBlinkMs")
        count = tunables.get("failBlinkCount")
        for i in range(count):
            lit = "L" if i % 2 == 0 else "R"
            self._timeline.append((now + i * blink_ms, partial(self._emit, events.fail_blink(lit))))
        last = "L" if (count - 1) % 2 == 0 else "R"
        self._timeline.append((now + count * blink_ms, partial(self._emit, events.fail_fade(last))))
        self._timeline.append((now + count * blink_ms + tunables.get("failFadeMs"), self.to_idle))

    async def _start_song(self) -> None:
        game = self.game
        self.state = "playing"
        song_id = await self._player.start_game(game)
        if self.state != "playing":  # stopped while the start sequence ran: don't leave music playing untracked
            if song_id is not None:
                await self._player.run_action("stop")
            return
        if song_id is None:
            print(f"Show: no song to play for game {game!r} (missing or empty playlist)")
            await self.to_idle()
            return
        await self._emit(events.legacy_start(game))
        await self._begin_song(song_id)

    async def _begin_song(self, song_id: int) -> None:
        self._song_id = song_id
        self._song_started_ms = self._clock.now_ms()
        self._key = None
        self._map = self._player.song_map()
        self._thunder = Thunder(self._clock.now_ms()) if self.game == "thunder" else None
        self._log("song_start", songId=str(song_id), game=self.game, bpm=self._map.bpm,
                  hasSections=self._map.has_markers, hasBeats=bool(self._map.beats))
        if not self._map.has_markers:
            self._log("fault", kind="markers_missing", detail=f"song {song_id}: no usable sections, using spec fallbacks")
        if status := self._player.status():
            await self._follow(status)

    async def _follow(self, status: SongStatus) -> None:
        """One playing event whenever the section, the showoff turn, the singer or the thunder frame changes."""
        if status.id != self._song_id:  # changed under us (web UI Next): a new song needs its own map
            self._end_song("skip")
            await self._begin_song(status.id)
            return
        self._t = status.t
        section = self._map.section_at(status.t)
        turn = self._map.turn_owner(status.t, status.duration) if self.game == "showoff" else None
        frame = self._thunder.frame(self._clock.now_ms()) if self._thunder else None
        owner = self._owner(status)
        key = (section, turn, frame and frame.key, owner)
        if key != self._key:
            new_section = not self._key or self._key[0] != section
            singer = owner or turn or "both"
            handover = self._key is not None and singer != (self._key[3] or self._key[1] or "both")
            self._key = key
            await self._emit(events.playing(self.game, status.id, section, turn, status.t, frame, owner, handover))
            if new_section:
                self._background_run(self._scene(section))
                await asyncio.sleep(0)

    def _owner(self, status: SongStatus) -> str | None:
        """Whose section it is, for the poles' glow (thunder's frame brings its own poles)."""
        if self.game == "duet":
            return self._map.singer(status.t, status.duration)
        return None  # showoff: the turn

    async def _scene(self, section) -> None:
        """The section's appliances; off the tick, a real plug may take seconds to answer."""
        await self._player.apply_scene(section[0] if section else None)

    def _background_run(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _after_skip(self) -> None:
        self._end_song("skip")
        if status := self._player.status():
            await self._begin_song(status.id)  # same game, next song (a one-song playlist replays it)
        else:
            await self.to_idle()

    def _end_song(self, reason: str) -> None:
        self._thunder = None
        if self._song_id is None:
            return
        self._log("song_end", songId=str(self._song_id), game=self.game, reason=reason,
                  playedMs=self._clock.now_ms() - self._song_started_ms, atMs=int(self._t * 1000))
        self._song_id = None

    def _ok(self, action, side) -> dict:
        return {"status": "ok", "action": action, "side": side, "show_state": self.state}

    def _ignored(self, action, reason) -> dict:
        return {"status": "ignored", "action": action, "reason": reason, "show_state": self.state}


def load_tunables(db) -> None:
    """Apply the saved tunable overrides (at startup)."""
    for row in db.query(ShowTunable).all():
        if row.id in tunables.defaults():  # a tunable dropped from the spec is ignored
            tunables.set_override(row.id, row.value)


def save_tunable(db, tunable_id: str, value) -> None:
    row = db.get(ShowTunable, tunable_id)
    if row:
        row.value = value
    else:
        db.add(ShowTunable(id=tunable_id, value=value))
    db.commit()
    tunables.set_override(tunable_id, value)


director = ShowDirector(StagePlayer(), Clock(), _broadcast, analytics.append)
