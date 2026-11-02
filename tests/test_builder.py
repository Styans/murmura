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


def _closest_airborne(show, t0, t1, steps=400):
    """Smallest distance between two drones that are both off the ground."""
    times = np.linspace(t0, t1, steps)
    pos = np.stack([d.trajectory.position_at(times) for d in show.drones], axis=1)
    home = pos[0, :, 2]
    worst = np.inf
    for p in pos:
        up = np.flatnonzero(p[:, 2] - home > 0.01)
        if len(up) < 2:
            continue
        diff = p[up, None, :] - p[None, up, :]
        dist = np.linalg.norm(diff, axis=-1) + np.eye(len(up)) * 1e9
        worst = min(worst, float(dist.min()))
    return worst


def _wave_show(grid_spacing):
    limits = SafetyLimits(min_distance=2)
    b = ShowBuilder(36, limits=limits, grid_spacing=grid_spacing)
    b.takeoff(altitude=6, climb_velocity=1.2)
    b.scene("Ring", circle(36, radius=14, center=(0, 0, 25)), hold=2)
    b.land(velocity=1.0, spindown=2.0)
    return b, b.build()


def test_takeoff_and_landing_in_waves_keep_the_minimum_distance():
    b, show = _wave_show(grid_spacing=1.5)  # pad closer than the 2 m minimum
    assert any("2 waves" in note for note in b.log)
    t0, t1 = show.segments["takeoff"]
    assert _closest_airborne(show, t0, t1) >= 2 - 1e-3
    l0, l1 = show.segments["landing"]
    assert _closest_airborne(show, l0, l1) >= 2 - 1e-3
    assert validate_show(show).passed

    # checkerboard: neighbours on the pad leave at different times
    lift_off = []
    for d in show.drones:
        times = np.linspace(t0, t1, 2000)
        z = d.trajectory.position_at(times)[:, 2]
        lift_off.append(times[np.argmax(z > 0.01)])
    lift_off = np.array(lift_off).reshape(6, 6)
    assert len(np.unique(np.round(lift_off, 1))) == 2
    assert lift_off[0, 0] != lift_off[0, 1] and lift_off[0, 0] == lift_off[1, 1]


def test_takeoff_is_simultaneous_when_the_pad_is_spacious():
    b, show = _wave_show(grid_spacing=3)
    assert not any("waves" in note for note in b.log)
    t0, t1 = show.segments["takeoff"]
    times = np.linspace(t0, t1, 500)
    first = [times[np.argmax(d.trajectory.position_at(times)[:, 2] > 0.01)] for d in show.drones]
    assert np.ptp(first) < 1e-6


def test_drones_return_to_their_own_takeoff_points():
    limits = SafetyLimits(min_distance=2)
    b = ShowBuilder(36, limits=limits, grid_spacing=1.5)
    b.takeoff(altitude=6, climb_velocity=1.2)
    hover = b.positions.copy()
    b.scene("Wall", circle(36, radius=14, center=(0, 30, 25)), hold=2)
    b.land(style="direct")
    show = b.build()
    assert validate_show(show).passed
    land0, _ = show.segments["landing"]
    end = np.array([d.trajectory.last_position for d in show.drones])
    assert np.allclose(end, b.home)  # every drone on its own spot
    # on the way down every drone passes the very point it hovered at after takeoff
    times = np.linspace(land0, show.end_time, 4000)
    for d, point in zip(show.drones, hover):
        track = d.trajectory.position_at(times)
        assert np.min(np.linalg.norm(track - point, axis=1)) < 0.02
    assert not any("nearest" in note for note in b.log)


def _touchdowns(show, t0):
    times = np.linspace(t0, show.end_time, 6000)
    out = []
    for d in show.drones:
        z = d.trajectory.position_at(times)[:, 2]
        out.append(times[np.argmax(z <= 1e-3)])
    return np.array(out)


def test_landing_rows_follow_one_another():
    limits = SafetyLimits(min_distance=2)
    b = ShowBuilder(36, limits=limits, grid_spacing=1.5)
    b.takeoff(altitude=6, climb_velocity=1.2)
    b.scene("Ring", circle(36, radius=14, center=(0, 30, 25)), hold=2)
    b.land(style="direct", spindown=2.0)
    show = b.build()
    assert validate_show(show).passed
    touch = np.round(_touchdowns(show, show.segments["landing"][0]), 1)
    first, second = np.unique(touch)
    # the second row starts descending only after the first one is down
    assert np.sum(touch == first) == np.sum(touch == second) == 18
    land0, _ = show.segments["landing"]
    times = np.linspace(land0, show.end_time, 6000)
    later = [d for d, t in zip(show.drones, touch) if t == second]
    hover = max(d.trajectory.position_at([first])[0][2] for d in later)
    # the moment each of them leaves its hover height
    leave = [
        times[len(times) - 1 - np.argmax(d.trajectory.position_at(times)[::-1, 2] >= hover - 0.05)]
        for d in later
    ]
    assert min(leave) >= first + 2.0 - 0.1


def test_four_landing_rows_on_request():
    b = ShowBuilder(36, limits=SafetyLimits(min_distance=2), grid_spacing=1.5)
    b.takeoff(altitude=6, rows=4)
    b.scene("Ring", circle(36, radius=14, center=(0, 30, 25)), hold=2)
    b.land(rows=4)
    assert any("4 waves" in note for note in b.log)
    assert validate_show(b.build()).passed


def test_petal_return_is_safe_and_lands_on_own_spots():
    b = ShowBuilder(36, limits=SafetyLimits(min_distance=2), grid_spacing=3)
    b.takeoff(altitude=6)
    b.scene("Ring", circle(36, radius=14, center=(0, 30, 25)), hold=2)
    b.land(style="petals", petal_order="top", petal_interval=0.3, sway=1.0)
    show = b.build()
    note = next(n for n in b.log if "petals" in n)
    assert "0 drones peel" not in note
    report = validate_show(read_skyc(write_skyc(show)))
    assert report.passed, report.summary()
    end = np.array([d.trajectory.last_position for d in show.drones])
    assert np.allclose(end, b.home)


def test_morph_return_reforms_the_swarm_above_the_pad_and_lands_in_rows():
    limits = SafetyLimits(min_distance=2)
    b = ShowBuilder(36, limits=limits, grid_spacing=1.5)
    b.takeoff(altitude=6, climb_velocity=1.2)
    b.scene("Ring", circle(36, radius=14, center=(0, 30, 25)), hold=2)  # 2.44 m: breathes out
    land0 = b.t
    b.land(spindown=2.0)
    show = b.build()
    assert any("re-forms" in note for note in b.log)
    assert any("4 waves" in note for note in b.log)
    end = np.array([d.trajectory.last_position for d in show.drones])
    # every pad spot gets exactly one drone
    assert len({tuple(np.round(p, 3)) for p in end}) == 36
    assert {tuple(np.round(p, 3)) for p in end} == {tuple(np.round(p, 3)) for p in b.home}
    # nobody comes closer than the minimum while breathing out and re-forming
    times = np.linspace(land0, show.end_time, 3000)
    pos = np.stack([d.trajectory.position_at(times) for d in show.drones], axis=1)
    for frame in pos[::5]:
        up = frame[frame[:, 2] >= limits.min_nav_altitude]
        if len(up) > 1:
            dist = np.linalg.norm(up[:, None] - up[None], axis=2) + np.eye(len(up)) * 9
            assert dist.min() >= 2 - 1e-3
