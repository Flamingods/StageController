from sqlalchemy import Column, Integer, String, JSON

from app.core.database import Base


class PillarPlan(Base):
    """A saved sequence for one slot; slots without a row use the ESP's built-in default."""
    __tablename__ = "pillar_plans"

    slot = Column(String, primary_key=True)
    data = Column(JSON, nullable=False)


class PillarMeta(Base):
    """Single row holding the plans version the ESP watches for changes."""
    __tablename__ = "pillar_meta"

    id = Column(Integer, primary_key=True)
    plans_version = Column(Integer, nullable=False, default=0)


class PillarProgram(Base):
    """A program in the library the Pi can command each pillar to play (contract §10)."""
    __tablename__ = "pillar_programs"

    id = Column(Integer, primary_key=True)  # 1..255, the id the ESP sees
    name = Column(String, nullable=False)
    data = Column(JSON, nullable=False)


class PillarProgramsMeta(Base):
    """Single row: the library version and the command counter. Separate from PillarMeta so
    existing databases need no column migration."""
    __tablename__ = "pillar_programs_meta"

    id = Column(Integer, primary_key=True)
    programs_version = Column(Integer, nullable=False, default=0)
    command_seq = Column(Integer, nullable=False, default=0)


class PillarCommand(Base):
    """The current command per side; seq never decreases."""
    __tablename__ = "pillar_commands"

    side = Column(String, primary_key=True)  # "L" or "R"
    seq = Column(Integer, nullable=False)
    program = Column(Integer, nullable=False)  # 0 = released
