from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.core.database import get_db

from . import programs, service
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
        "pillars": service.pillar_status.snapshot(),
        "programs_version": programs.get_version(db),
        "commands": programs.commands(db),
        # A game (any state but idle) owns the LEDs; commanded programs wait underneath
        "show_state": _show_state(),
    }


def _show_state() -> str:
    from app.features.show.service import director
    return director.state


# ---- Programs (contract §10) ------------------------------------------------------

class ProgramIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    sequence: Sequence


class CommandIn(BaseModel):
    sides: Annotated[list[Literal["L", "R"]], Field(min_length=1)]
    program: Annotated[int, Field(ge=0, le=programs.MAX_PROGRAM_ID)]


@router.get("/programs")
def list_programs(db: Session = Depends(get_db)):
    return programs.list_programs(db)


@router.post("/programs")
def create_program(body: ProgramIn, db: Session = Depends(get_db)):
    return programs.create_program(db, body.name, body.sequence)


@router.get("/programs/index")
def programs_index(db: Session = Depends(get_db)):
    """ESP: the library's version and ids; fetch each <id>.bin when the version changes."""
    return programs.index(db)


@router.get("/programs/{program_id}.bin")
def program_binary(program_id: int, db: Session = Depends(get_db)):
    data = programs.program_binary(db, program_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No program {program_id}")
    return Response(content=data, media_type=BINARY)


@router.put("/programs/{program_id}")
def update_program(program_id: int, body: ProgramIn, db: Session = Depends(get_db)):
    return programs.update_program(db, program_id, body.name, body.sequence)


@router.delete("/programs/{program_id}")
async def delete_program(program_id: int, db: Session = Depends(get_db)):
    return await programs.delete_program(db, program_id)


@router.post("/command")
async def send_command(body: CommandIn, db: Session = Depends(get_db)):
    """Tell sides to play a program (0 = release): WebSocket now, state-poll backup within ~1 s."""
    return await programs.command(db, body.sides, body.program)
