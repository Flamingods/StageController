from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.features.songs.models import Song
from app.features.playlists.services import get_playlist, get_playlist_songs
from app.features.pillar import service as pillar
from app.features.pillar.poles import poles
from .service import player

router = APIRouter(prefix="/player", tags=["player"])


class PlaySongRequest(BaseModel):
    song_id: int


class PlayPlaylistRequest(BaseModel):
    playlist_id: int
    start_index: int = 0


class SeekRequest(BaseModel):
    time: float


class VolumeRequest(BaseModel):
    volume: float


@router.get("/state")
def get_state(request: Request, client: str | None = None, running_version: int | None = None,
              pillar_id: int | None = None, db: Session = Depends(get_db)):
    """Get current player state, plus what the pillar ESP watches (it polls this every second
    as ?client=pillar&pillar_id=N&running_version=N). The preview id is the editor's draft when one
    plays, else that pillar's show pole (docs/pillar-led-contract.md §9)."""
    if client == "pillar":
        pillar.pillar_status.record_poll(running_version)
        if pillar_id is not None:
            poles.seen(pillar_id, request.client.host if request.client else None)
    return {
        **player.get_state(),
        "pillar_plans_version": pillar.get_version(db),
        "pillar_preview_id": pillar.preview.current_id() or poles.current_id(pillar_id),
    }


@router.post("/play/song")
def play_song(request: PlaySongRequest, db: Session = Depends(get_db)):
    """Play a specific song."""
    song = db.query(Song).filter(Song.id == request.song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    success = player.play_song(song.id, song.title, song.artist, song.file_path)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to play song")

    return {"status": "ok", "song": {"id": song.id, "title": song.title}}


@router.post("/play/playlist")
def play_playlist(request: PlayPlaylistRequest, db: Session = Depends(get_db)):
    """Load a playlist and start playing."""
    playlist = get_playlist(db, request.playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    songs = get_playlist_songs(db, request.playlist_id)
    if not songs:
        raise HTTPException(status_code=400, detail="Playlist is empty")

    queue = [
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "file_path": s.file_path,
        }
        for s in songs
    ]

    player.set_queue(queue, playlist.name)
    success = player.play_from_queue(request.start_index)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to start playlist")

    return {"status": "ok", "playlist": playlist.name, "song_count": len(queue)}


@router.post("/toggle")
def toggle_play():
    """Toggle play/pause."""
    player.toggle_play()
    return {"status": "ok", "is_playing": player.get_state()["is_playing"]}


@router.post("/pause")
def pause():
    """Pause playback."""
    player.pause()
    return {"status": "ok"}


@router.post("/resume")
def resume():
    """Resume playback."""
    player.resume()
    return {"status": "ok"}


@router.post("/stop")
def stop():
    """Stop playback and clear current song."""
    player.stop()
    return {"status": "ok"}


@router.post("/next")
def next_song():
    """Skip to next song in queue."""
    success = player.next()
    if not success:
        raise HTTPException(status_code=400, detail="No queue or at end of queue")
    return {"status": "ok", **player.get_state()}


@router.post("/prev")
def prev_song():
    """Go to previous song in queue."""
    success = player.prev()
    if not success:
        raise HTTPException(status_code=400, detail="No queue")
    return {"status": "ok", **player.get_state()}


@router.post("/seek")
def seek(request: SeekRequest):
    """Seek to a specific time."""
    player.seek(request.time)
    return {"status": "ok"}


@router.post("/volume")
def set_volume(request: VolumeRequest):
    """Set volume (0-100)."""
    player.set_volume(request.volume)
    return {"status": "ok", "volume": request.volume}
