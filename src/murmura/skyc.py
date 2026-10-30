"""Reading and writing ``.skyc`` compiled show files and JSON show specifications.

A ``.skyc`` file is a ZIP archive::

    show.json                     show specification with "$ref" links
    cues.json                     time markers
    cameras.json                  optional camera list
    assets/music.mp3              optional soundtrack
    drones/<name>/trajectory.json Bézier trajectory (times relative to takeoffTime)
    drones/<name>/lights.json     base64-encoded light program bytecode
    drones/<name>/yaw_control.json  optional yaw setpoints
    drones/<name>/pyro.json       optional pyro events

The same specification can also be given inline (without ``$ref`` links);
that is the format accepted by the render API.
"""

from __future__ import annotations

import base64
import io
import json
import re
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

import numpy as np

from .lights import LightKeyframe, LightProgram
from .model import (
    Audio,
    Camera,
    Cue,
    Drone,
    PyroEvent,
    PyroPayload,
    PyroProgram,
    SafetyLimits,
    Show,
    ShowLocation,
    YawSetpoint,
)
from .trajectory import Trajectory, TrajectoryPoint

__all__ = (
    "SkycError",
    "parse_show_spec",
    "read_skyc",
    "show_to_spec",
    "write_skyc",
)

FORMAT_VERSION = 1


class SkycError(ValueError):
    """Raised when a show file or specification is malformed."""


# ----------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------


def _round(value: float, ndigits: int) -> float:
    v = round(float(value), ndigits)
    return 0.0 if v == 0 else v


def _round_vec(vec, ndigits: int) -> list[float]:
    return [_round(v, ndigits) for v in vec]


def trajectory_to_json(traj: Trajectory, *, ndigits: int = 3) -> dict[str, Any]:
    """Converts a trajectory into the ``.skyc`` trajectory representation.

    Leading hover time is trimmed and expressed via ``takeoffTime``; all point
    timestamps become relative to ``takeoffTime``.
    """
    if not traj:
        return {"version": 1, "points": [], "takeoffTime": 0.0, "landingTime": 0.0}

    takeoff = traj.first_movement_time()
    pts = traj.points
    k = next(i for i, p in enumerate(pts) if p.t >= takeoff - 1e-9)

    out = []
    last_t = None
    for i, p in enumerate(pts[k:]):
        t = _round(p.t - takeoff, ndigits)
        if last_t is not None and t <= last_t:
            continue
        controls = [] if i == 0 else [_round_vec(c, ndigits) for c in p.controls]
        out.append([t, _round_vec(p.pos, ndigits), controls])
        last_t = t

    return {
        "version": 1,
        "points": out,
        "takeoffTime": _round(takeoff, ndigits),
        "landingTime": _round(traj.end_time, ndigits),
    }


def _yaw_to_json(drone: Drone, ndigits: int) -> dict[str, Any]:
    return {
        "version": 1,
        "setpoints": [[_round(s.time, ndigits), _round(s.angle, ndigits)] for s in drone.yaw or []],
        "autoYaw": bool(drone.auto_yaw),
        "autoYawOffset": _round(drone.auto_yaw_offset, ndigits),
    }


def _pyro_to_json(program: PyroProgram, ndigits: int) -> dict[str, Any]:
    return {
        "version": 1,
        "events": [[_round(e.time, ndigits), int(e.channel), e.payload] for e in program.events],
        "payloads": {key: p.to_json() for key, p in program.payloads.items()},
    }


def _safe_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip() or "drone"
    return cleaned[:120]


def show_to_spec(
    show: Show,
    *,
    ndigits: int = 3,
    files: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Converts a show into a JSON show specification.

    If ``files`` is given, per-drone data, cues, cameras and audio are stored
    in that dict (path -> content) and referenced with ``$ref`` links, which
    is the layout used inside ``.skyc`` archives. Otherwise everything is
    inlined.
    """
    end_time = max(
        [show.end_time] + [d.lights.end_time for d in show.drones if d.lights],
    )
    linked = files is not None

    def store(path: str, payload: Any, *, raw: bool = False) -> Any:
        if not linked:
            return payload
        files[path] = payload if raw else _dumps(payload)
        return {"$ref": f"./{path}"}

    used_dirs: set[str] = set()
    drones_json = []
    for drone in show.drones:
        base = _safe_name(drone.name)
        dirname, k = base, 2
        while dirname.lower() in used_dirs:
            dirname, k = f"{base}_{k}", k + 1
        used_dirs.add(dirname.lower())
        prefix = f"drones/{dirname}"

        settings: dict[str, Any] = {}
        traj = trajectory_to_json(drone.trajectory, ndigits=ndigits)
        settings["trajectory"] = _ref_hash(store(f"{prefix}/trajectory.json", traj))
        if drone.lights:
            code = drone.lights.to_bytecode(end_time=end_time)
            lights = {"version": 1, "data": base64.b64encode(code).decode("ascii")}
            settings["lights"] = _ref_hash(store(f"{prefix}/lights.json", lights))
        if drone.pyro and drone.pyro.events:
            settings["pyro"] = _ref_hash(
                store(f"{prefix}/pyro.json", _pyro_to_json(drone.pyro, ndigits))
            )
        if drone.yaw:
            settings["yawControl"] = _ref_hash(
                store(f"{prefix}/yaw_control.json", _yaw_to_json(drone, ndigits))
            )
        if drone.trajectory:
            settings["home"] = _round_vec(drone.home_position, ndigits)
            settings["landAt"] = _round_vec(drone.landing_position, ndigits)
        settings["name"] = drone.name
        drones_json.append({"type": "generic", "settings": settings})

    cues = {
        "version": 1,
        "items": [{"time": _round(c.time, ndigits), "name": c.name} for c in show.cues],
    }

    environment: dict[str, Any] = {"type": show.environment}
    if show.cameras:
        environment["cameras"] = store("cameras.json", [c.to_json(ndigits) for c in show.cameras])
    if show.location is not None:
        environment["location"] = show.location.to_json()

    meta: dict[str, Any] = {"id": show.show_id or uuid.uuid4().hex, "title": show.title}
    if show.timestamp_offset is not None:
        meta["timestampOffset"] = show.timestamp_offset
    if show.segments:
        meta["segments"] = {
            k: [_round(a, ndigits), _round(b, ndigits)] for k, (a, b) in show.segments.items()
        }

    media: dict[str, Any] = {}
    if show.audio is not None:
        filename = _safe_name(show.audio.filename or "music.mp3")
        audio_data = (
            {"$ref": f"./assets/{filename}"}
            if linked
            else base64.b64encode(show.audio.data).decode("ascii")
        )
        if linked:
            files[f"assets/{filename}"] = show.audio.data
        media["audio"] = {
            "data": audio_data,
            "mediaType": show.audio.media_type,
            "startTime": show.audio.start_time,
        }

    return {
        "version": FORMAT_VERSION,
        "settings": {
            "cues": store("cues.json", cues),
            "validation": show.limits.to_json(ndigits),
        },
        "swarm": {"drones": drones_json},
        "environment": environment,
        "meta": meta,
        "media": media,
    }


def _ref_hash(value: Any) -> Any:
    if isinstance(value, dict) and "$ref" in value:
        return {"$ref": value["$ref"] + "#"}
    return value


def _dumps(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_skyc(
    show: Show,
    target: str | Path | IO[bytes] | None = None,
    *,
    ndigits: int = 3,
) -> bytes | None:
    """Writes the show into a ``.skyc`` archive.

    Returns the archive as bytes when ``target`` is ``None``.
    """
    files: dict[str, bytes] = {}
    spec = show_to_spec(show, ndigits=ndigits, files=files)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("show.json", json.dumps(spec, indent=2, ensure_ascii=False))
        order = sorted(
            files, key=lambda p: (not p.endswith("cues.json"), not p.startswith("cameras"), p)
        )
        for path in order:
            zf.writestr(path, files[path])
    data = buffer.getvalue()

    if target is None:
        return data
    if hasattr(target, "write"):
        target.write(data)  # type: ignore[union-attr]
    else:
        Path(target).write_bytes(data)
    return None


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------


def _fit_or_line(times, positions, *, simplify: bool, tolerance: float) -> Trajectory:
    if simplify:
        return Trajectory.from_samples(times, positions, tolerance=tolerance)
    traj = Trajectory()
    for t, p in zip(times, positions):
        if not traj:
            traj.start_at(t, p)
        elif t > traj.end_time:
            traj.line_to(t, p)
    return traj


def parse_trajectory(
    data: dict[str, Any], *, simplify: bool = True, tolerance: float = 0.03
) -> Trajectory:
    """Parses a trajectory in any of the supported representations.

    Version 0: ``[[t, x, y, z], ...]`` samples. Version 1: Bézier points
    ``[[t, [x, y, z], [controls...]], ...]`` relative to ``takeoffTime``.
    Version 2: base64-encoded little-endian float32 ``t, x, y, z`` samples.
    """
    version = int(data.get("version", 1))
    points = data.get("points") or []

    if version == 2:
        raw = base64.b64decode(points) if isinstance(points, str) else b""
        if len(raw) % 16:
            raise SkycError("version 2 trajectory data length is not a multiple of 16 bytes")
        arr = np.frombuffer(raw, dtype="<f4").astype(float).reshape(-1, 4)
        if not len(arr):
            return Trajectory()
        return _fit_or_line(arr[:, 0], arr[:, 1:], simplify=simplify, tolerance=tolerance)

    if version == 0:
        arr = np.asarray(points, dtype=float).reshape(-1, 4)
        if not len(arr):
            return Trajectory()
        return _fit_or_line(arr[:, 0], arr[:, 1:], simplify=simplify, tolerance=tolerance)

    if version == 1:
        offset = float(data.get("takeoffTime") or 0.0)
        if not points:
            return Trajectory()
        has_controls = any(len(p) > 2 and p[2] for p in points)
        if not has_controls and simplify and len(points) > 2 and data.get("takeoffTime") is None:
            # Plain samples sent by a client: compress them
            arr = np.asarray([[p[0], *p[1]] for p in points], dtype=float)
            return Trajectory.from_samples(arr[:, 0], arr[:, 1:], tolerance=tolerance)
        traj = Trajectory()
        for p in points:
            t = float(p[0]) + offset
            pos = tuple(float(v) for v in p[1])
            controls = [tuple(float(v) for v in c) for c in (p[2] if len(p) > 2 else [])]
            if not traj:
                traj.start_at(t, pos)
            elif t > traj.end_time + 1e-9:
                traj.points.append(TrajectoryPoint(t, pos, controls))  # type: ignore[arg-type]
        traj._invalidate()
        return traj

    raise SkycError(f"unsupported trajectory version: {version}")


def parse_lights(data: dict[str, Any] | None) -> LightProgram:
    if not data:
        return LightProgram()
    payload = data.get("data")
    if isinstance(payload, str):
        return LightProgram.from_bytecode(base64.b64decode(payload))
    if isinstance(payload, list):
        keyframes = []
        for item in payload:
            t, color, *rest = item
            keyframes.append(
                LightKeyframe(
                    float(t), tuple(int(c) for c in color[:3]), bool(rest[0]) if rest else True
                )  # type: ignore[arg-type]
            )
        return LightProgram(keyframes)
    return LightProgram()


def _parse_yaw(data: dict[str, Any] | None) -> tuple[list[YawSetpoint] | None, bool, float]:
    if not data:
        return None, False, 0.0
    setpoints = [YawSetpoint(float(t), float(a)) for t, a in data.get("setpoints", [])]
    return (
        setpoints or None,
        bool(data.get("autoYaw", False)),
        float(data.get("autoYawOffset", 0.0)),
    )


def _parse_pyro(data: dict[str, Any] | None) -> PyroProgram | None:
    if not data or not data.get("events"):
        return None
    payloads = {str(k): PyroPayload.from_json(v) for k, v in (data.get("payloads") or {}).items()}
    events = [PyroEvent(float(e[0]), int(e[1]), str(e[2])) for e in data["events"]]
    return PyroProgram(events=events, payloads=payloads)


Resolver = Callable[[str], Any]


def _resolve(value: Any, resolver: Resolver | None, *, raw: bool = False) -> Any:
    if isinstance(value, dict) and "$ref" in value:
        if resolver is None:
            raise SkycError(f"cannot resolve reference {value['$ref']!r} without an archive")
        ref = value["$ref"].split("#", 1)[0]
        if ref.startswith("./"):
            ref = ref[2:]
        content = resolver(ref)
        return content if raw else json.loads(content)
    return value


def parse_show_spec(
    spec: dict[str, Any],
    *,
    resolver: Resolver | None = None,
    simplify: bool = True,
    tolerance: float = 0.03,
) -> Show:
    """Builds a :class:`Show` from a JSON show specification."""
    if not isinstance(spec, dict):
        raise SkycError("show specification must be a JSON object")
    if int(spec.get("version", 1)) != 1:
        raise SkycError(f"unsupported show specification version: {spec.get('version')}")

    settings = spec.get("settings") or {}
    cues_json = _resolve(settings.get("cues"), resolver) or {}
    cues = [Cue(float(c["time"]), str(c.get("name", ""))) for c in cues_json.get("items", [])]
    limits = SafetyLimits.from_json(settings.get("validation"))

    drones: list[Drone] = []
    for index, item in enumerate((spec.get("swarm") or {}).get("drones") or []):
        s = item.get("settings") or {}
        name = str(s.get("name") or f"Drone {index + 1}")
        traj_json = _resolve(s.get("trajectory"), resolver)
        trajectory = (
            parse_trajectory(traj_json, simplify=simplify, tolerance=tolerance)
            if traj_json
            else Trajectory()
        )
        if not trajectory and s.get("home") is not None:
            trajectory = Trajectory.stationary(s["home"])
        yaw, auto_yaw, auto_yaw_offset = _parse_yaw(_resolve(s.get("yawControl"), resolver))
        drones.append(
            Drone(
                name=name,
                trajectory=trajectory,
                lights=parse_lights(_resolve(s.get("lights"), resolver)),
                yaw=yaw,
                auto_yaw=auto_yaw,
                auto_yaw_offset=auto_yaw_offset,
                pyro=_parse_pyro(_resolve(s.get("pyro"), resolver)),
                home=tuple(s["home"]) if s.get("home") is not None else None,  # type: ignore[arg-type]
                land_at=tuple(s["landAt"]) if s.get("landAt") is not None else None,  # type: ignore[arg-type]
            )
        )

    environment = spec.get("environment") or {}
    cameras_json = _resolve(environment.get("cameras"), resolver) or []
    location = environment.get("location")

    meta = spec.get("meta") or {}
    segments = {
        str(k): (float(v[0]), float(v[1]))
        for k, v in (meta.get("segments") or {}).items()
        if isinstance(v, (list, tuple)) and len(v) == 2
    }

    audio = None
    audio_json = (spec.get("media") or {}).get("audio")
    if audio_json and audio_json.get("data") is not None:
        data = audio_json["data"]
        filename = "music.mp3"
        if isinstance(data, dict) and "$ref" in data:
            filename = data["$ref"].rsplit("/", 1)[-1]
            content = _resolve(data, resolver, raw=True)
        else:
            content = base64.b64decode(data)
        audio = Audio(
            data=content,
            media_type=str(audio_json.get("mediaType", "audio/mpeg")),
            start_time=float(audio_json.get("startTime", 0.0)),
            filename=filename,
        )

    return Show(
        drones=drones,
        title=str(meta.get("title") or "Untitled"),
        limits=limits,
        cues=cues,
        environment=str(environment.get("type", "outdoor")),
        location=ShowLocation.from_json(location) if location else None,
        cameras=[Camera.from_json(c) for c in cameras_json],
        audio=audio,
        segments=segments,
        timestamp_offset=meta.get("timestampOffset"),
        show_id=meta.get("id"),
    )


def read_skyc(source: str | Path | bytes | IO[bytes]) -> Show:
    """Reads a ``.skyc`` archive."""
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    try:
        zf = zipfile.ZipFile(source)  # type: ignore[arg-type]
    except zipfile.BadZipFile as ex:
        raise SkycError("not a valid .skyc archive") from ex
    with zf:
        names = set(zf.namelist())
        if "show.json" not in names:
            raise SkycError("show.json is missing from the archive")

        def resolver(path: str) -> bytes:
            if path not in names:
                raise SkycError(f"referenced file {path!r} is missing from the archive")
            return zf.read(path)

        spec = json.loads(zf.read("show.json"))
        return parse_show_spec(spec, resolver=resolver)


def pack_float32_samples(times, positions) -> str:
    """Encodes samples as a version 2 trajectory payload (base64 float32)."""
    arr = np.column_stack([np.asarray(times, float), np.asarray(positions, float)]).astype("<f4")
    return base64.b64encode(arr.tobytes()).decode("ascii")
