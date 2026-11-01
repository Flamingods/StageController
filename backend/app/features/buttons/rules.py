"""Which button actions take effect in which show state.

Kept free of player/device imports so it can be unit-tested without audio hardware.
"""

# While the show is idle, a single press (start) brings it up and a long press (stop)
# makes sure everything is off; every other gesture is ignored.
IDLE_ALLOWED_ACTIONS = frozenset({"start", "stop"})


def is_action_allowed(action: str, show_running: bool) -> bool:
    return show_running or action in IDLE_ALLOWED_ACTIONS

# Launch gestures (side-aware presses while the show is idle): the action name maps back to
# the tap count the pillar counted, which is what the spec's launch rule works on.
# Lossy by design: "special" covers both 3 and 5+ taps.
IDLE_TAPS = {"start": 1, "claps": 2, "special": 3, "skip": 4}

# In-song meaning of each action (side-aware presses while a game is playing). "tap" is the
# plain single press, used for thunder steals; everything else is today's behaviour.
IN_SONG = {"start": "tap", "claps": "claps", "special": "special", "skip": "skip", "stop": "stop"}


def in_song_meaning(action: str, taps: int | None) -> str:
    """In-song meaning of a side-aware press: by the real tap count when the pillar sends it
    (1 tap, 2 claps, 3 skip, 4+ special; user rule 2026-11-01), else by the action name.
    The pillar still names gestures by its own table (3 = special, 4 = skip), so the count wins."""
    if action == "stop" or taps is None:
        return IN_SONG[action]
    return {1: "tap", 2: "claps", 3: "skip"}.get(taps, "special")
