"""Claps sounds played over the music, each moment from its own playlist.

- start_claps: a single press starts or resumes the show
- claps: the claps button (2 taps)
- finale_claps: a few seconds before a song ends
start_claps and finale_claps fall back to "claps" when missing or empty.
"""
import random

from sqlalchemy.orm import Session

from app.features.player.service import player as music_player
from app.features.playlists.models import Playlist, playlist_songs
from app.features.songs.models import Song

START_CLAPS = "start_claps"
BUTTON_CLAPS = "claps"
FINALE_CLAPS = "finale_claps"


def _random_song(db: Session, playlist_name: str) -> Song | None:
    playlist = db.query(Playlist).filter(Playlist.name.ilike(playlist_name)).first()
    if not playlist:
        return None
    entries = db.execute(
        playlist_songs.select().where(playlist_songs.c.playlist_id == playlist.id)
    ).fetchall()
    if not entries:
        return None
    return db.query(Song).filter(Song.id == random.choice(entries).song_id).first()


def play_claps(db: Session, playlist_name: str, fallback: str | None = None) -> dict | None:
    """Play a random song from the playlist as an overlay (doesn't stop the main music).

    Returns the song played, or None if neither playlist has anything to play.
    """
    song = _random_song(db, playlist_name)
    if song is None and fallback:
        song = _random_song(db, fallback)
    if song is None:
        return None
    music_player.play_overlay(song.file_path)
    return {"id": song.id, "title": song.title, "artist": song.artist}


def play_start_claps(db: Session) -> dict | None:
    return play_claps(db, START_CLAPS, fallback=BUTTON_CLAPS)


def play_button_claps(db: Session) -> dict | None:
    return play_claps(db, BUTTON_CLAPS)


def play_finale_claps(db: Session) -> dict | None:
    return play_claps(db, FINALE_CLAPS, fallback=BUTTON_CLAPS)
