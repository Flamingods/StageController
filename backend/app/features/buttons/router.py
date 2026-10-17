from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.features.devices.models import Sequence, Device
from app.features.devices.service import execute_sequence, set_device_state, update_device_state

from app.features.playlists.models import Playlist
from app.features.playlists.services import shuffle_playlist, get_playlist_songs
from app.features.player.service import player as music_player
from app.features.stats.models import SongPlay
from app.features.buttons.rules import is_action_allowed
from app.features.buttons.claps import play_button_claps, play_start_claps

router = APIRouter(prefix="/buttons", tags=["buttons"])

ButtonAction = Literal["start", "stop", "skip", "claps", "special"]


class ButtonPress(BaseModel):
    action: ButtonAction
    timestamp: datetime | None = None
    # Present = a side-aware pillar press, handled by the show director (docs/show-events-contract.md);
    # absent = the legacy single-button path
    side: Literal["L", "R"] | None = None
    first_press_ago_ms: int = Field(default=0, ge=0)
    # The gesture's real tap count, when the sender knows it: the action name alone is lossy
    # (4 taps = skip, 5+ = special = 3), so the launch rule would read 4+4 or 5+5 wrong
    taps: int | None = Field(default=None, ge=1)


class ButtonEvent(BaseModel):
    action: ButtonAction
    timestamp: datetime
    playlist_id: int | None = None
    playlist_name: str | None = None
    overlay_song_id: int | None = None


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.last_events: list[ButtonEvent] = []
        self.last_show: BaseModel | None = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # show events are sent on changes only: a client joining mid-song would think the show is idle
        if self.last_show is not None:
            await websocket.send_json(self.last_show.model_dump(mode="json"))

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, event: BaseModel):
        if isinstance(event, ButtonEvent):  # /recent stays button presses only, not show frames
            self.last_events.append(event)
            if len(self.last_events) > 100:
                self.last_events = self.last_events[-100:]
        elif getattr(event, "action", None) == "show":  # not cues: a late client needs the state only
            self.last_show = event

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(event.model_dump(mode="json"))
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.active_connections.remove(conn)


manager = ConnectionManager()


async def handle_start_action(db: Session, playlist_name: str = "main") -> dict:
    """Start main sequence and a playlist ("main" unless a game asks for its own), with a claps sound to open the show."""
    result = {"sequence": None, "playlist": None, "overlay_song": None}

    # Find and execute "main" sequence
    main_sequence = db.query(Sequence).filter(Sequence.name.ilike("main")).first()
    if main_sequence:
        seq_result = await execute_sequence(db, main_sequence.id)
        result["sequence"] = seq_result

    # Find the playlist
    main_playlist = db.query(Playlist).filter(Playlist.name.ilike(playlist_name)).first()
    if main_playlist:
        # If currently playing, just resume
        if music_player.get_current_song_id() is not None:
            music_player.resume()
        # If queue exists (was stopped mid-show), play next song
        elif music_player.has_queue():
            music_player.play_current_queue_position()
        # No queue - shuffle and start fresh
        else:
            shuffle_playlist(db, main_playlist.id)
            songs = get_playlist_songs(db, main_playlist.id)
            if songs:
                queue = [
                    {"id": s.id, "title": s.title, "artist": s.artist, "file_path": s.file_path}
                    for s in songs
                ]
                music_player.set_queue(queue, main_playlist.name)
                music_player.play_from_queue(0)

        result["playlist"] = {"id": main_playlist.id, "name": main_playlist.name}

    # Claps sound over the music (sound only, not the claps device sequence)
    result["overlay_song"] = play_start_claps(db)

    return result


async def end_show(db: Session) -> dict:
    """End the show - turn off all devices. Called by stop button or when playlist ends."""
    result = {"devices_off": []}

    devices = db.query(Device).all()
    for device in devices:
        success = await set_device_state(device.ip_address, False)
        if success:
            update_device_state(db, device.id, False)
        result["devices_off"].append({"device": device.name, "success": success})

    return result


async def handle_stop_action(db: Session) -> dict:
    """Stop button pressed - end the show."""
    # Record stopped stat for current song
    current_song_id = music_player.get_current_song_id()
    if current_song_id:
        play = SongPlay(song_id=current_song_id, outcome="stopped")
        db.add(play)
        db.commit()

    # Stop music playback and any claps/overlay sound still playing
    music_player.stop()
    music_player.stop_overlay()

    return await end_show(db)


async def handle_skip_action(db: Session) -> dict:
    """Skip to next song."""
    # Record skipped stat for current song
    current_song_id = music_player.get_current_song_id()
    if current_song_id:
        play = SongPlay(song_id=current_song_id, outcome="skipped")
        db.add(play)
        db.commit()

    # Skip to next song
    music_player.next()

    return {"command": "skip", "state": music_player.get_state()}


async def handle_claps_action(db: Session) -> dict:
    """Trigger claps sequence and play random song from claps playlist as overlay."""
    result = {"sequence": None, "overlay_song": None}

    # Find and execute "claps" sequence
    claps_sequence = db.query(Sequence).filter(Sequence.name.ilike("claps")).first()
    if claps_sequence:
        seq_result = await execute_sequence(db, claps_sequence.id)
        result["sequence"] = seq_result

    result["overlay_song"] = play_button_claps(db)

    return result


async def handle_special_action(db: Session) -> dict:
    """Trigger special sequence - smoke, bubbles, effects."""
    result = {"sequence": None}

    # Find and execute "special" sequence
    special_sequence = db.query(Sequence).filter(Sequence.name.ilike("special")).first()
    if special_sequence:
        seq_result = await execute_sequence(db, special_sequence.id)
        result["sequence"] = seq_result

    return result


async def handle_action(action: ButtonAction, db: Session | None = None) -> dict:
    """Handle button actions with side effects."""
    extras = {}

    if db:
        if action == "start":
            extras = await handle_start_action(db)
        elif action == "stop":
            extras = await handle_stop_action(db)
        elif action == "skip":
            extras = await handle_skip_action(db)
        elif action == "claps":
            extras = await handle_claps_action(db)
        elif action == "special":
            extras = await handle_special_action(db)

    return extras


def show_is_running() -> bool:
    """The show runs while a song is loaded (playing or paused); otherwise it is idle."""
    return music_player.get_current_song_id() is not None


def ignored_response(action: ButtonAction) -> dict:
    # 200 with an explicit status so the button doesn't treat it as a failure and retry
    return {"status": "ignored", "action": action, "reason": "show_stopped"}


async def perform(action: ButtonAction, db: Session, timestamp: datetime | None = None) -> dict:
    """Run an action and tell the WebSocket clients about it."""
    extras = await handle_action(action, db)

    playlist_info = extras.get("playlist", {})
    overlay_song = extras.get("overlay_song", {})
    event = ButtonEvent(
        action=action,
        timestamp=timestamp or datetime.now(),
        playlist_id=playlist_info.get("id") if playlist_info else None,
        playlist_name=playlist_info.get("name") if playlist_info else None,
        overlay_song_id=overlay_song.get("id") if overlay_song else None,
    )

    await manager.broadcast(event)

    return {"status": "ok", "action": action, "timestamp": event.timestamp, **extras}


async def end_game_on_stop(action: ButtonAction):
    """A legacy stop also ends any game the show director is running."""
    if action == "stop":
        from app.features.show.service import director
        await director.to_idle("stop")


@router.post("/press")
async def button_press(data: ButtonPress, db: Session = Depends(get_db)):
    """Receive a button press from external device (Pi GPIO, remote, etc.)"""
    if data.side:
        from app.features.show.service import director
        return await director.on_press(data.action, data.side, data.first_press_ago_ms, data.taps)

    if not is_action_allowed(data.action, show_is_running()):
        return ignored_response(data.action)

    result = await perform(data.action, db, data.timestamp)
    await end_game_on_stop(data.action)
    return result


@router.post("/press/{action}")
async def button_press_simple(action: ButtonAction, db: Session = Depends(get_db)):
    """Simple endpoint: POST /api/buttons/press/start"""
    if not is_action_allowed(action, show_is_running()):
        return ignored_response(action)

    result = await perform(action, db)
    await end_game_on_stop(action)
    return result


@router.post("/end")
async def playlist_ended(db: Session = Depends(get_db)):
    """Called when a song ends - turns off all devices. Does NOT broadcast stop event."""
    result = await end_show(db)
    return {"status": "ok", "reason": "song_ended", **result}


@router.get("/recent")
async def get_recent_events(limit: int = 10):
    """Get recent button events"""
    return manager.last_events[-limit:]


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time button events"""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
