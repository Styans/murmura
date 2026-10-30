import base64
import gzip
import io
import json
import zipfile

import numpy as np
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from murmura.server import create_app  # noqa: E402
from murmura.skyc import pack_float32_samples, read_skyc  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def _render_request(fmt="skyc"):
    t = np.arange(0, 20.01, 0.25)
    drones = []
    for i in range(3):
        pos = np.column_stack([np.full_like(t, i * 3.0), np.zeros_like(t), np.clip(t - 5, 0, 10)])
        drones.append(
            {
                "type": "generic",
                "settings": {
                    "name": f"Drone {i + 1}",
                    "trajectory": {"version": 2, "points": pack_float32_samples(t, pos)},
                    "lights": {"version": 1, "data": [[0, [255, 0, 0], 1], [10, [0, 0, 255], 1]]},
                    "yawControl": {"version": 1, "setpoints": [[0, 0], [10, 45]]},
                },
            }
        )
    return {
        "input": {
            "format": "json",
            "data": {
                "version": 1,
                "environment": {"type": "outdoor"},
                "settings": {
                    "cues": {"version": 1, "items": [{"name": "Go", "time": 5}]},
                    "validation": {"minDistance": 2},
                },
                "swarm": {"drones": drones},
                "meta": {"title": "api test"},
                "media": {},
            },
        },
        "output": {"format": fmt},
    }


def test_queries(client):
    assert client.get("/queries/version").json() == {"version": "2.45.0"}
    limits = client.get("/queries/limits").json()
    assert "import:svg" in limits["features"] and limits["num_drones"] is None
    assert client.get("/api/v1/ping").json() == {"result": True}


def test_render_skyc(client):
    response = client.post("/operations/render", json=_render_request())
    assert response.status_code == 200
    show = read_skyc(response.content)
    assert [d.name for d in show.drones] == ["Drone 1", "Drone 2", "Drone 3"]
    assert show.drones[0].trajectory.first_movement_time() == pytest.approx(5.0, abs=0.01)
    assert show.drones[1].yaw[1].angle == 45


def test_render_accepts_gzip_bodies(client):
    body = gzip.compress(json.dumps(_render_request("csv")).encode())
    response = client.post(
        "/operations/render",
        content=body,
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert response.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert names == ["Drone 1.csv", "Drone 2.csv", "Drone 3.csv"]


def test_render_roundtrips_skyc_input(client):
    skyc = client.post("/operations/render", json=_render_request()).content
    request = {
        "input": {"format": "skyc", "data": base64.b64encode(skyc).decode()},
        "output": {"format": "json"},
    }
    response = client.post("/operations/render", json=request)
    assert response.status_code == 200
    assert len(response.json()["swarm"]["drones"]) == 3


def test_planning_operations(client):
    plan = client.post(
        "/operations/plan-transition",
        json={
            "version": 1,
            "source": [[0, 0, 10], [3, 0, 10], [6, 0, 10], [0, 3, 10]],
            "target": [[6, 3, 15], [0, 6, 12], [3, 6, 12], [6, 6, 12]],
            "max_velocity_xy": 8,
            "max_velocity_z": 2,
            "max_acceleration": 4,
        },
    ).json()
    assert plan["durations"] == [3.75] * 4 and plan["version"] == 1
    match = client.post(
        "/operations/match-points",
        json={"version": 1, "source": [[0, 0, 0]], "target": [[1, 0, 0]], "radius": 0.5},
    ).json()
    assert match["mapping"] == [0]
    groups = client.post(
        "/operations/plan-takeoff",
        json={"version": 1, "points": [[0, 0, 0], [1, 0, 0]], "min_distance": 2},
    ).json()
    assert sorted(groups["groups"]) == [0, 1]
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><polyline points="0,0 100,0 100,50" stroke="red" fill="none"/></svg>'
    formation = client.post(
        "/operations/create-static-formation",
        json={
            "version": 1,
            "method": "svg",
            "parameters": {"version": 1, "source": svg, "n": 4, "size": 10, "angle": 30},
        },
    ).json()
    assert formation["points"][0] == [2.5, 5.0, 0]
    assert formation["colors"][0] == [255, 0, 0]


def test_errors_are_reported_as_detail(client):
    response = client.post(
        "/operations/render",
        json={"input": {"format": "dss", "data": ""}, "output": {"format": "skyc"}},
    )
    assert response.status_code == 400
    assert "not supported" in response.json()["detail"]
    response = client.post("/operations/plan-landing", json={"version": 1})
    assert response.status_code == 400 and "missing" in response.json()["detail"]
