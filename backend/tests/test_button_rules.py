import pytest

from app.features.buttons.rules import IDLE_TAPS, IN_SONG, in_song_meaning, is_action_allowed


@pytest.mark.parametrize("action", ["start", "stop", "skip", "claps", "special"])
def test_every_action_allowed_while_show_running(action):
    assert is_action_allowed(action, show_running=True)


@pytest.mark.parametrize("action", ["start", "stop"])
def test_start_and_stop_allowed_while_idle(action):
    assert is_action_allowed(action, show_running=False)


@pytest.mark.parametrize("action", ["skip", "claps", "special"])
def test_other_actions_ignored_while_idle(action):
    assert not is_action_allowed(action, show_running=False)


def test_idle_taps_map_actions_back_to_tap_counts():
    assert IDLE_TAPS == {"start": 1, "claps": 2, "special": 3, "skip": 4}
    assert "stop" not in IDLE_TAPS  # a long press is never a launch


def test_in_song_table_covers_every_action():
    assert set(IN_SONG) == {"start", "stop", "skip", "claps", "special"}
    assert IN_SONG["start"] == "tap"
    assert all(IN_SONG[a] == a for a in ("claps", "special", "skip", "stop"))


@pytest.mark.parametrize("taps, meaning", [(1, "tap"), (2, "claps"), (3, "skip"), (4, "special"), (5, "special"), (12, "special")])
def test_in_song_meaning_follows_the_real_tap_count(taps, meaning):
    # the pillar's action name is still the old one (3 = special, 4 = skip); the count decides
    old_name = {1: "start", 2: "claps", 3: "special", 4: "skip"}.get(taps, "special")
    assert in_song_meaning(old_name, taps) == meaning


def test_in_song_long_press_is_stop_whatever_the_count():
    assert in_song_meaning("stop", 1) == "stop"


@pytest.mark.parametrize("action", ["start", "claps", "special", "skip", "stop"])
def test_in_song_meaning_without_a_count_falls_back_to_the_action_name(action):
    assert in_song_meaning(action, None) == IN_SONG[action]
