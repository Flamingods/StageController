import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.features.show import palette, tunables
from app.features.show.router import router


@pytest.fixture(autouse=True)
def clean_overrides():
    tunables.clear_overrides()
    yield
    tunables.clear_overrides()


def test_every_spec_colour_with_ramp_gain_and_drift():
    body = palette.build_palette()
    assert set(body["colors"]) == {"pink", "lime", "blue", "white"}
    pink = body["colors"]["pink"]
    assert pink["ramp"] == tunables.SPEC["palette"]["pink"]["ramp"]
    assert pink["gain"] == tunables.get("pinkGain")
    assert pink["drift_ms"] == tunables.get("pinkDriftPeriodMs")


def test_colours_without_their_own_tunables_use_the_emulator_fallbacks():
    white = palette.build_palette()["colors"]["white"]
    assert white["gain"] == 1.0
    # Only pink has its own drift tunable; the others drift at the emulator's 2800 ms
    assert white["drift_ms"] == 2800
    assert palette.build_palette()["colors"]["lime"]["drift_ms"] == 2800


def test_version_is_stable_and_changes_with_a_colour_tunable():
    v1 = palette.build_palette()["version"]
    assert palette.build_palette()["version"] == v1
    tunables.set_override("limeGain", 1.3)
    body = palette.build_palette()
    assert body["colors"]["lime"]["gain"] == 1.3
    assert body["version"] != v1
    assert 0 < body["version"] < 2**32


def test_unrelated_tunable_does_not_change_the_version():
    v1 = palette.build_palette()["version"]
    tunables.set_override("failBlinkMs", tunables.get("failBlinkMs") + 1)
    assert palette.build_palette()["version"] == v1


def test_endpoint_serves_the_palette():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    res = TestClient(app).get("/api/show/palette")
    assert res.status_code == 200
    assert res.json() == palette.build_palette()
