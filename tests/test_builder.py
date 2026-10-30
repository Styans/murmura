import numpy as np
import pytest

from murmura import ShowBuilder, read_skyc, validate_show, write_skyc
from murmura.cli import DEMO_SCRIPT
from murmura.csvio import read_csv_zip, write_csv_zip
from murmura.effects import Rainbow, Solid
from murmura.formations import circle
from murmura.model import SafetyLimits
from murmura.script import ScriptError, build_from_script


def test_builder_produces_a_valid_show():
    limits = SafetyLimits(
        max_velocity_xy=6,
        max_velocity_z=2.5,
        max_acceleration_xy=3,
        max_acceleration_z=3,
        min_distance=2,
    )
    b = ShowBuilder(16, limits=limits, grid_spacing=3)
    b.takeoff(altitude=5)
    b.scene("Ring", circle(16, radius=8, center=(0, 0, 20)), hold=4, effect=Rainbow(period=2))
    b.scene(
        "Big ring",
        circle(16, radius=12, center=(0, 0, 25), plane="xy"),
        hold=3,
        effect=Solid("#ff8800"),
    )
    b.land()
    show = b.build()
    assert show.num_drones == 16
    assert set(show.segments) == {"takeoff", "show", "landing"}
    report = validate_show(show)
    assert report.passed, report.summary()
    # every drone ends on the ground with lights off
    for drone in show.drones:
        assert drone.trajectory.last_position[2] == pytest.approx(0.0)
        assert drone.lights.keyframes[-1].color == (0, 0, 0)


def test_demo_script_passes_validation():
    show, _ = build_from_script(DEMO_SCRIPT)
    report = validate_show(show)
    assert report.passed, report.summary()
    loaded = read_skyc(write_skyc(show))
    assert loaded.num_drones == 100


def test_script_errors_are_reported():
    with pytest.raises(ScriptError):
        build_from_script({"title": "no drones"})
    with pytest.raises(ScriptError):
        build_from_script({"drones": 4, "scenes": [{"name": "x", "formation": {"shape": "nope"}}]})


def test_motion_is_limited_to_the_envelope():
    limits = SafetyLimits(
        max_velocity_xy=3, max_acceleration_xy=1.5, max_acceleration_z=1.5, min_distance=2
    )
    b = ShowBuilder(12, limits=limits, grid_spacing=3)
    b.takeoff()
    from murmura.choreo import Motion

    b.scene(
        "Spin",
        circle(12, radius=10, center=(0, 0, 20), plane="xy"),
        hold=10,
        motion=Motion("rotate", rpm=12),
    )
    report = validate_show(b.build())
    assert report.stats["maxVelocityXY"] <= 3 * 1.01
    assert report.stats["maxAccelerationXY"] <= 1.5 * 1.05


def test_csv_roundtrip():
    b = ShowBuilder(4, grid_spacing=4)
    b.takeoff(altitude=5)
    b.scene("Line", np.array([[x, 0, 15] for x in (-6, -2, 2, 6)]), hold=2, effect=Solid("#00ff00"))
    b.land()
    show = b.build()
    loaded = read_csv_zip(write_csv_zip(show, fps=8))
    t = np.linspace(0, show.end_time, 200)
    for a, c in zip(show.drones, loaded.drones):
        assert np.max(np.abs(a.trajectory.position_at(t) - c.trajectory.position_at(t))) < 0.1
