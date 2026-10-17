import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pathlib import Path
from pydantic import BaseModel

from app.core.database import get_db
from . import services
from .schemas import SongResponse, SongListResponse, SongUpdate


class TrimRequest(BaseModel):
    start_time: float
    end_time: float

router = APIRouter(prefix="/songs", tags=["songs"])


@router.post("/upload", response_model=SongResponse)
async def upload_song(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a single song."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    if not services.is_valid_audio_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Allowed: mp3, flac, wav, ogg, aac, m4a, wma",
        )

    file_path = await services.save_uploaded_file(file)
    song = services.create_song_from_file(db, file_path, file.filename)
    return song


@router.post("/upload/batch", response_model=list[SongResponse])
async def upload_songs_batch(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Upload multiple songs at once."""
    uploaded_songs = []

    for file in files:
        if not file.filename:
            continue

        if not services.is_valid_audio_file(file.filename):
            continue

        file_path = await services.save_uploaded_file(file)
        song = services.create_song_from_file(db, file_path, file.filename)
        uploaded_songs.append(song)

    return uploaded_songs


@router.get("", response_model=SongListResponse)
def get_songs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    search: str | None = None,
    sort_by: str = Query("created_at", pattern="^(title|artist|album|duration|created_at)$"),
    sort_desc: bool = True,
    db: Session = Depends(get_db),
):
    """Get all songs with optional filtering and pagination."""
    songs, total = services.get_songs(db, skip, limit, search, sort_by, sort_desc)
    return SongListResponse(songs=songs, total=total)


@router.get("/{song_id}", response_model=SongResponse)
def get_song(song_id: int, db: Session = Depends(get_db)):
    """Get a single song by ID."""
    song = services.get_song(db, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


@router.get("/{song_id}/stream")
def stream_song(song_id: int, db: Session = Depends(get_db)):
    """Stream a song file."""
    song = services.get_song(db, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    file_path = Path(song.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Song file not found")

    return FileResponse(
        file_path,
        media_type=f"audio/{song.format}",
        filename=song.filename,
        headers={
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.put("/{song_id}/analysis")
def put_analysis(song_id: int, analysis: dict, db: Session = Depends(get_db)):
    """Store the analyzer's JSON as the song's sidecar (<stem>.analysis.json) so the show gets markers."""
    song = services.get_song(db, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    Path(song.file_path).with_suffix(".analysis.json").write_text(json.dumps(analysis))
    return {"message": "Analysis stored"}


@router.patch("/{song_id}", response_model=SongResponse)
def update_song(
    song_id: int,
    song_update: SongUpdate,
    db: Session = Depends(get_db),
):
    """Update song metadata."""
    song = services.update_song(db, song_id, song_update)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


@router.delete("/{song_id}")
def delete_song(song_id: int, db: Session = Depends(get_db)):
    """Delete a song."""
    success = services.delete_song(db, song_id)
    if not success:
        raise HTTPException(status_code=404, detail="Song not found")
    return {"message": "Song deleted successfully"}


@router.post("/{song_id}/trim", response_model=SongResponse)
def trim_song(
    song_id: int,
    trim: TrimRequest,
    db: Session = Depends(get_db),
):
    """Trim a song to the specified time range."""
    song = services.get_song(db, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    if trim.start_time < 0 or trim.end_time <= trim.start_time:
        raise HTTPException(status_code=400, detail="Invalid trim range")

    if trim.end_time > song.duration:
        raise HTTPException(status_code=400, detail="End time exceeds song duration")

    result = services.trim_song(db, song_id, trim.start_time, trim.end_time)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to trim song")
    return result
