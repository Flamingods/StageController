from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db

from . import service
from .defaults import DEFAULT_SEQUENCES, SLOTS
from .poles import poles
from .schemas import Sequence

router = APIRouter(prefix="/pillar", tags=["pillar"])

BINARY = "application/octet-stream"


def _check_slot(slot: str):
    if slot not in SLOTS:
        raise HTTPException(status_code=404, detail=f"Unknown slot '{slot}'")


@router.get("/plans")
def get_plans(db: Session = Depends(get_db)):
    """Saved sequences per slot (null = the ESP's built-in default) and the plans version."""
    return {"version": service.get_version(db), "slots": service.list_plans(db, SLOTS)}


@router.get("/plans/defaults")
def get_defaults():
    return DEFAULT_SEQUENCES


@router.get("/plans/{slot}.bin")
def get_plan_binary(slot: str, db: Session = Depends(get_db)):
    """ESP download: the compiled slot, or 404 when the slot uses the built-in default."""
    _check_slot(slot)
    data = service.plan_binary(db, slot)
    if data is None:
        raise HTTPException(status_code=404, detail="Slot uses the built-in default")
    return Response(content=data, media_type=BINARY)


@router.put("/plans/{slot}")
def save_plan(slot: str, sequence: Sequence, db: Session = Depends(get_db)):
    _check_slot(slot)
    return {"version": service.save_plan(db, slot, sequence)}


@router.delete("/plans/{slot}")
def reset_plan(slot: str, db: Session = Depends(get_db)):
    """Back to the built-in default."""
    _check_slot(slot)
    return {"version": service.reset_plan(db, slot)}


@router.post("/preview")
def start_preview(sequence: Sequence):
    """Play an unsaved draft on the real pillar (picked up within ~1 s, expires after 60 s)."""
    return {"preview_id": service.preview.start(sequence)}


@router.delete("/preview")
def stop_preview():
    service.preview.clear()
    return {"preview_id": 0}


@router.get("/preview.bin")
def get_preview_binary(request: Request):
    """The editor's draft, else the show pole of the pillar polling from this address (the ESP's
    preview fetch carries no pillar id)."""
    data = service.preview.binary() or poles.binary(poles.pillar_at(request.client.host if request.client else None))
    if data is None:
        raise HTTPException(status_code=404, detail="No preview playing")
    return Response(content=data, media_type=BINARY)


@router.get("/status")
def get_status(db: Session = Depends(get_db)):
    return {
        "plans_version": service.get_version(db),
        "preview_id": service.preview.current_id(),
        **service.pillar_status.snapshot(),
    }
