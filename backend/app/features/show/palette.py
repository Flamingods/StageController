"""The palette the pillars need to light poles like the emulator (docs/pillar-led-contract.md §11).

Each spec colour: its 3-stop ramp [dim, base, bright], its gain tunable and its drift period.
`version` is a checksum of the payload, so it changes exactly when a ramp or colour tunable
does, and stays the same across restarts.
"""
import json
import zlib

from . import tunables

# frontend/src/show/stageLook.ts drift(): colours without their own period drift at 2800 ms
DEFAULT_DRIFT_MS = 2800


def _tunable(tunable_id: str, fallback):
    return tunables.get(tunable_id) if tunable_id in tunables.defaults() else fallback


def build_palette() -> dict:
    colors = {
        name: {
            "ramp": spec["ramp"],
            "gain": _tunable(f"{name}Gain", 1.0),
            "drift_ms": _tunable(f"{name}DriftPeriodMs", _tunable("driftPeriodMs", DEFAULT_DRIFT_MS)),
        }
        for name, spec in tunables.SPEC["palette"].items()
    }
    # Never 0, so "no palette yet" on the ESP is always different from a real version
    version = zlib.crc32(json.dumps(colors, sort_keys=True).encode()) or 1
    return {"version": version, "colors": colors}
