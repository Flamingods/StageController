from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.features.show.songmap import SongMap
from app.features.songs.models import Song
from app.features.songs.router import router


def test_put_analysis_writes_the_sidecar_the_show_reads(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    audio = tmp_path / "abc.m4a"
    audio.write_bytes(b"x")
    with Session() as s:
        s.add(Song(title="t", duration=1.0, filename="t.m4a", file_path=str(audio), format="m4a", file_size=1))
        s.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: Session()
    c = TestClient(app)
    body = {"tempo": {"bpm": 100, "beats": [1.0]}, "sections": [{"start": 0, "end": 5, "label": "verse"}]}
    assert c.put("/songs/1/analysis", json=body).status_code == 200
    assert SongMap.for_audio(str(audio), tmp_path).has_markers
    assert c.put("/songs/9/analysis", json=body).status_code == 404
