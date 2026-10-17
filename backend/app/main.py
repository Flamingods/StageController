import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.config import API_PREFIX
from app.core.database import init_db
from app.features.songs.router import router as songs_router
from app.features.playlists.router import router as playlists_router
from app.features.devices.router import router as devices_router, sequences_router
from app.features.buttons.router import router as buttons_router, websocket_endpoint
from app.features.stats.router import router as stats_router
import asyncio

from app.features.player.router import router as player_router
from app.features.pillar.router import router as pillar_router
from app.features.show.router import router as show_router
from app.features.player.service import player as music_player, set_main_loop
from app.features.stats.models import SongPlay
from app.features.buttons.router import end_show, manager as button_manager, ButtonEvent

app = FastAPI(
    title="StageController",
    description="Raspberry Pi appliance controller with music management",
    version="1.0.0",
)

STATIC_DIR = Path(__file__).parent.parent / "static"

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include feature routers
app.include_router(songs_router, prefix=API_PREFIX)
app.include_router(playlists_router, prefix=API_PREFIX)
app.include_router(devices_router, prefix=API_PREFIX)
app.include_router(sequences_router, prefix=API_PREFIX)
app.include_router(buttons_router, prefix=API_PREFIX)
app.include_router(stats_router, prefix=API_PREFIX)
app.include_router(player_router, prefix=API_PREFIX)
app.include_router(pillar_router, prefix=API_PREFIX)
app.include_router(show_router, prefix=API_PREFIX)


@app.on_event("startup")
async def startup():
    init_db()

    # Set main event loop for mpv callbacks
    set_main_loop(asyncio.get_event_loop())

    from app.core.database import SessionLocal
    from app.features.show.service import director, load_tunables
    db = SessionLocal()
    try:
        load_tunables(db)
    finally:
        db.close()
    app.state.show_loop = asyncio.create_task(director.run())  # keep a reference so it is not collected

    # Set up music player callbacks
    async def on_song_end():
        """Called when a song ends naturally - record stat, stop playback, turn off devices."""
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            # Record completed stat
            song_id = music_player.get_current_song_id()
            if song_id:
                play = SongPlay(song_id=song_id, outcome="completed")
                db.add(play)
                db.commit()

            # Stop playback, advance queue (keeps queue intact for next start)
            # If we've reached the end of the playlist, clear queue so next start reshuffles
            music_player.stop(advance_queue=True)
            if music_player.is_queue_exhausted():
                music_player.clear_queue()

            # Turn off devices
            await end_show(db)

            # Broadcast state change
            from datetime import datetime
            event = ButtonEvent(action="stop", timestamp=datetime.now())
            await button_manager.broadcast(event)
        finally:
            db.close()

    async def on_state_change():
        """Called when player state changes - broadcast to WebSocket clients."""
        pass  # Frontend will poll /player/state

    async def on_song_ending():
        """Called a few seconds before a song ends - play end-of-song claps."""
        from app.core.database import SessionLocal
        from app.features.buttons.claps import play_finale_claps

        db = SessionLocal()
        try:
            song = play_finale_claps(db)
            if song:
                print(f"Playing finale claps: {song['title']}")
        finally:
            db.close()

    music_player.set_callbacks(on_song_end, on_state_change, on_song_ending)


@app.get("/health")
def health():
    return {"status": "healthy"}


# WebSocket endpoint needs to be registered before the catch-all route
app.add_api_websocket_route("/api/buttons/ws", websocket_endpoint)


# Serve frontend static files in production
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    async def serve_frontend(path: str):
        file_path = STATIC_DIR / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/")
    def root():
        return {"message": "StageController API", "version": "1.0.0", "note": "Frontend not built. Run npm run build in frontend/"}
