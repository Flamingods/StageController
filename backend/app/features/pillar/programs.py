"""Program library and per-side commands (docs/pillar-led-contract.md §10).

Both pillars download the whole library; the Pi then tells each side which program to play.
Commands go out over the buttons WebSocket and are repeated in each pillar's state poll.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .compiler import compile_sequence
from .models import PillarCommand, PillarProgram, PillarProgramsMeta
from .schemas import Sequence

MAX_PROGRAMS = 24
# The ESP stages a whole new library next to the active one in a 1.4 MB partition
MAX_LIBRARY_BYTES = 512 * 1024
MAX_PROGRAM_ID = 255
SIDES = ("L", "R")


class _WsMessage:
    """Shape the buttons ConnectionManager broadcasts (it calls model_dump)."""

    def __init__(self, data: dict):
        self.data = data
        self.action = data["action"]

    def model_dump(self, mode: str | None = None) -> dict:
        return self.data


async def broadcast(message: dict) -> None:
    from app.features.buttons.router import manager
    await manager.broadcast(_WsMessage(message))


def _meta(db: Session) -> PillarProgramsMeta:
    meta = db.get(PillarProgramsMeta, 1)
    if meta is None:
        meta = PillarProgramsMeta(id=1, programs_version=0, command_seq=0)
        db.add(meta)
        db.flush()
    return meta


def get_version(db: Session) -> int:
    meta = db.get(PillarProgramsMeta, 1)
    return meta.programs_version if meta else 0


def _bump_version(db: Session) -> int:
    meta = _meta(db)
    meta.programs_version += 1
    return meta.programs_version


def _size(data: dict) -> int:
    return len(compile_sequence(Sequence.model_validate(data), 0))


def list_programs(db: Session) -> dict:
    rows = db.query(PillarProgram).order_by(PillarProgram.id).all()
    return {
        "version": get_version(db),
        "programs": [{"id": p.id, "name": p.name, "sequence": p.data, "size": _size(p.data)} for p in rows],
    }


def _check_library(db: Session, sequence: Sequence, replacing: int | None = None) -> None:
    others = [p for p in db.query(PillarProgram).all() if p.id != replacing]
    if replacing is None and len(others) >= MAX_PROGRAMS:
        raise HTTPException(422, f"The library holds at most {MAX_PROGRAMS} programs")
    total = sum(_size(p.data) for p in others) + len(compile_sequence(sequence, 0))
    if total > MAX_LIBRARY_BYTES:
        raise HTTPException(422, f"The library would be {total} bytes; the pillars store at most {MAX_LIBRARY_BYTES}")


def create_program(db: Session, name: str, sequence: Sequence) -> dict:
    _check_library(db, sequence)
    used = {p.id for p in db.query(PillarProgram.id).all()}
    program_id = next(i for i in range(1, MAX_PROGRAM_ID + 1) if i not in used)
    db.add(PillarProgram(id=program_id, name=name, data=sequence.model_dump()))
    version = _bump_version(db)
    db.commit()
    return {"id": program_id, "version": version}


def update_program(db: Session, program_id: int, name: str, sequence: Sequence) -> dict:
    program = db.get(PillarProgram, program_id)
    if program is None:
        raise HTTPException(404, f"No program {program_id}")
    _check_library(db, sequence, replacing=program_id)
    program.name = name
    program.data = sequence.model_dump()
    version = _bump_version(db)
    db.commit()
    return {"id": program_id, "version": version}


async def delete_program(db: Session, program_id: int) -> dict:
    """Delete a program; sides currently commanded to play it are released."""
    program = db.get(PillarProgram, program_id)
    if program is None:
        raise HTTPException(404, f"No program {program_id}")
    db.delete(program)
    version = _bump_version(db)
    db.commit()
    playing = [side for side, c in commands(db).items() if c["program"] == program_id]
    if playing:
        await command(db, playing, 0)
    return {"version": version}


def index(db: Session) -> dict:
    ids = [p.id for p in db.query(PillarProgram.id).order_by(PillarProgram.id).all()]
    return {"version": get_version(db), "ids": ids}


def program_binary(db: Session, program_id: int) -> bytes | None:
    program = db.get(PillarProgram, program_id)
    if program is None:
        return None
    return compile_sequence(Sequence.model_validate(program.data), get_version(db))


def commands(db: Session) -> dict:
    rows = {c.side: c for c in db.query(PillarCommand).all()}
    return {side: {"seq": rows[side].seq, "program": rows[side].program} if side in rows else {"seq": 0, "program": 0}
            for side in SIDES}


async def command(db: Session, sides: list[str], program_id: int) -> dict:
    """Tell the given sides to play a program (0 = release). One seq for the whole command."""
    if not sides or any(s not in SIDES for s in sides):
        raise HTTPException(422, "sides must be a non-empty list of 'L' and/or 'R'")
    if program_id != 0 and db.get(PillarProgram, program_id) is None:
        raise HTTPException(422, f"No program {program_id}")
    meta = _meta(db)
    meta.command_seq += 1
    seq = meta.command_seq
    for side in dict.fromkeys(sides):
        row = db.get(PillarCommand, side)
        if row is None:
            db.add(PillarCommand(side=side, seq=seq, program=program_id))
        else:
            row.seq, row.program = seq, program_id
    db.commit()
    for side in dict.fromkeys(sides):
        await broadcast({"action": "pillar_command", "side": side, "seq": seq, "program": program_id})
    return {"seq": seq, "commands": commands(db)}
