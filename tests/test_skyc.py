import io
import json
import zipfile

import numpy as np

from murmura.lights import LightProgram
from murmura.model import (
    Audio,
    Camera,
    Cue,
    Drone,
    PyroEvent,
    PyroPayload,
    PyroProgram,
    Show,
    ShowLocation,
    YawSetpoint,
)
from murmura.skyc import parse_show_spec, read_skyc, show_to_spec, trajectory_to_json, write_skyc
from murmura.trajectory import Trajectory


def _show() -> Show:
    a = (
        Trajectory()
        .start_at(0, (0, 0, 0))
        .hold_until(5)
        .smooth_to(10, (0, 0, 10))
        .smooth_to(20, (20, 0, 10))
        .hold_until(25)
    )
    b = Trajectory().start_at(0, (5, 0, 0)).hold_until(5).smooth_to(10, (5, 0, 10)).hold_until(25)
    return Show(
        drones=[
            Drone("Drone 1", a, LightProgram([[0, "#ff0000"], [10, "#00ff00"]])),
            Drone(
                "Drone 2",
                b,
                LightProgram([[0, "white"]]),
                yaw=[YawSetpoint(0, 0), YawSetpoint(10, 90)],
                pyro=PyroProgram(
                    [PyroEvent(12.0, 0, "p1")], {"p1": PyroPayload("Gerb", duration=5)}
                ),
            ),
        ],
        title="Unit test",
        cues=[Cue(0, "Start"), Cue(10, "Move")],
        location=ShowLocation(47.4979, 19.0402, 120.0, 15.0),
        cameras=[Camera("Front", (0, -50, 10))],
        audio=Audio(b"ID3-fake", start_time=1.5),
        segments={"show": (10.0, 20.0)},
    )


def test_archive_layout_and_references():
    data = write_skyc(_show())
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = set(zf.namelist())
    assert {"show.json", "cues.json", "cameras.json", "assets/music.mp3"} <= names
    assert "drones/Drone 1/trajectory.json" in names
    assert "drones/Drone 2/yaw_control.json" in names
    assert "drones/Drone 2/pyro.json" in names
    spec = json.loads(zf.read("show.json"))
    settings = spec["swarm"]["drones"][0]["settings"]
    assert settings["trajectory"] == {"$ref": "./drones/Drone 1/trajectory.json#"}
    assert settings["home"] == [0.0, 0.0, 0.0] and settings["landAt"] == [20.0, 0.0, 10.0]
    assert spec["media"]["audio"]["data"] == {"$ref": "./assets/music.mp3"}
    assert spec["environment"]["location"] == {
        "origin": [474979000, 190402000, 120000],
        "orientation": 15.0,
    }


def test_takeoff_time_trims_leading_hover():
    traj = Trajectory().start_at(0, (0, 0, 0)).hold_until(5).smooth_to(9, (0, 0, 6))
    out = trajectory_to_json(traj)
    assert out["takeoffTime"] == 5.0
    assert out["landingTime"] == 9.0
    assert out["points"][0] == [0.0, [0.0, 0.0, 0.0], []]
    assert out["points"][1][0] == 4.0


def test_roundtrip():
    show = _show()
    loaded = read_skyc(write_skyc(show))
    assert [d.name for d in loaded.drones] == ["Drone 1", "Drone 2"]
    t = np.linspace(0, 25, 251)
    for a, b in zip(show.drones, loaded.drones):
        assert np.allclose(a.trajectory.position_at(t), b.trajectory.position_at(t), atol=2e-3)
        assert np.allclose(a.lights.color_at(t), b.lights.color_at(t), atol=1.0)
    assert loaded.drones[1].yaw[1].angle == 90
    assert loaded.drones[1].pyro.events[0].time == 12.0
    assert loaded.audio.data == b"ID3-fake"
    assert loaded.cameras[0].name == "Front"
    assert loaded.location.latitude == 47.4979
    assert loaded.segments == {"show": (10.0, 20.0)}
    assert [c.name for c in loaded.cues] == ["Start", "Move"]


def test_inline_spec_with_sampled_trajectories():
    from murmura.skyc import pack_float32_samples

    t = np.arange(0, 10.01, 0.25)
    pos = np.column_stack([t, np.zeros_like(t), np.full_like(t, 5.0)])
    spec = {
        "version": 1,
        "settings": {"cues": {"version": 1, "items": []}, "validation": {"minDistance": 2}},
        "swarm": {
            "drones": [
                {
                    "type": "generic",
                    "settings": {
                        "name": "A",
                        "trajectory": {"version": 2, "points": pack_float32_samples(t, pos)},
                        "lights": {
                            "version": 1,
                            "data": [[0, [255, 0, 0], 1], [5, [0, 0, 255], 1]],
                        },
                    },
                }
            ]
        },
        "meta": {"title": "inline"},
    }
    show = parse_show_spec(spec)
    traj = show.drones[0].trajectory
    assert len(traj) == 2  # a constant-velocity line compresses to one segment
    assert np.allclose(traj.position_at(t), pos, atol=1e-4)
    assert show.limits.min_distance == 2
    assert np.allclose(show.drones[0].lights.color_at([2.5])[0], [127.5, 0, 127.5])


def test_inline_spec_matches_linked_spec():
    show = _show()
    inline = show_to_spec(show)
    assert isinstance(inline["settings"]["cues"], dict) and "items" in inline["settings"]["cues"]
    again = parse_show_spec(inline)
    assert again.drones[0].trajectory.end_time == 25.0
