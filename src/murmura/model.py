"""Data model of a complete drone show."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .lights import LightProgram
from .trajectory import Trajectory, Vec3

__all__ = (
    "Audio",
    "Camera",
    "Cue",
    "Drone",
    "PyroEvent",
    "PyroPayload",
    "PyroProgram",
    "SafetyLimits",
    "Show",
    "ShowLocation",
    "YawSetpoint",
)


@dataclass
class SafetyLimits:
    """Flight envelope used for planning and validation."""

    max_altitude: float = 150.0
    max_velocity_xy: float = 8.0
    max_velocity_z: float = 3.0
    max_velocity_z_up: float | None = None
    max_acceleration_xy: float = 4.0
    max_acceleration_z: float = 4.0
    min_distance: float = 3.0
    min_nav_altitude: float = 2.5
    max_yaw_rate: float = 30.0

    @property
    def max_acceleration(self) -> float:
        return min(self.max_acceleration_xy, self.max_acceleration_z)

    @property
    def climb_velocity(self) -> float:
        return self.max_velocity_z_up if self.max_velocity_z_up else self.max_velocity_z

    def to_json(self, ndigits: int = 3) -> dict[str, float]:
        result = {
            "maxAccelerationXY": _r(self.max_acceleration_xy, ndigits),
            "maxAccelerationZ": _r(self.max_acceleration_z, ndigits),
            "maxAltitude": _r(self.max_altitude, ndigits),
            "maxVelocityXY": _r(self.max_velocity_xy, ndigits),
            "maxVelocityZ": _r(self.max_velocity_z, ndigits),
            "maxYawRate": _r(self.max_yaw_rate, ndigits),
            "minDistance": _r(self.min_distance, ndigits),
            "minNavAltitude": _r(self.min_nav_altitude, ndigits),
        }
        if self.max_velocity_z_up is not None:
            result["maxVelocityZUp"] = _r(self.max_velocity_z_up, ndigits)
        return result

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> SafetyLimits:
        data = data or {}
        d = cls()
        acc = data.get("maxAcceleration")
        return cls(
            max_altitude=float(data.get("maxAltitude", d.max_altitude)),
            max_velocity_xy=float(data.get("maxVelocityXY", d.max_velocity_xy)),
            max_velocity_z=float(data.get("maxVelocityZ", d.max_velocity_z)),
            max_velocity_z_up=(
                float(data["maxVelocityZUp"]) if data.get("maxVelocityZUp") is not None else None
            ),
            max_acceleration_xy=float(data.get("maxAccelerationXY", acc or d.max_acceleration_xy)),
            max_acceleration_z=float(data.get("maxAccelerationZ", acc or d.max_acceleration_z)),
            min_distance=float(data.get("minDistance", d.min_distance)),
            min_nav_altitude=float(data.get("minNavAltitude", d.min_nav_altitude)),
            max_yaw_rate=float(data.get("maxYawRate", d.max_yaw_rate)),
        )


@dataclass
class Cue:
    time: float
    name: str


@dataclass
class ShowLocation:
    """Geographic placement of the show coordinate system."""

    latitude: float
    longitude: float
    amsl: float | None = None
    orientation: float = 0.0
    """Heading of the +X axis, in degrees clockwise from North."""

    def to_json(self) -> dict[str, Any]:
        origin = [round(self.latitude * 1e7), round(self.longitude * 1e7)]
        if self.amsl is not None:
            origin.append(round(self.amsl * 1e3))
        return {"origin": origin, "orientation": round(self.orientation, 3)}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ShowLocation:
        origin = data.get("origin") or [0, 0]
        return cls(
            latitude=origin[0] / 1e7,
            longitude=origin[1] / 1e7,
            amsl=origin[2] / 1e3 if len(origin) > 2 and origin[2] is not None else None,
            orientation=float(data.get("orientation", 0.0)),
        )


@dataclass
class Camera:
    name: str
    position: Vec3
    orientation: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    """Orientation quaternion in ``(w, x, y, z)`` order."""
    type: str = "perspective"

    def to_json(self, ndigits: int = 3) -> dict[str, Any]:
        return {
            "type": self.type,
            "position": [_r(v, ndigits) for v in self.position],
            "orientation": [_r(v, ndigits) for v in self.orientation],
            "name": self.name,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Camera:
        return cls(
            name=str(data.get("name", "Camera")),
            position=tuple(float(v) for v in data.get("position", (0, 0, 0))),  # type: ignore[arg-type]
            orientation=tuple(float(v) for v in data.get("orientation", (1, 0, 0, 0))),  # type: ignore[arg-type]
            type=str(data.get("type", "perspective")),
        )


@dataclass
class Audio:
    data: bytes
    media_type: str = "audio/mpeg"
    start_time: float = 0.0
    filename: str = "music.mp3"


@dataclass
class YawSetpoint:
    time: float
    angle: float
    """Heading in degrees, clockwise."""


@dataclass
class PyroPayload:
    name: str
    duration: float = 30.0
    prefire_time: float = 0.0
    yaw: float = 0.0
    pitch: float = -90.0

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "prefireTime": self.prefire_time,
            "duration": self.duration,
            "yaw": round(self.yaw, 3),
            "pitch": round(self.pitch, 3),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PyroPayload:
        return cls(
            name=str(data.get("name", "pyro")),
            duration=float(data.get("duration", 30.0)),
            prefire_time=float(data.get("prefireTime", data.get("prefire_time", 0.0))),
            yaw=float(data.get("yaw", 0.0)),
            pitch=float(data.get("pitch", -90.0)),
        )


@dataclass
class PyroEvent:
    time: float
    channel: int
    """Zero-based pyro channel index."""
    payload: str


@dataclass
class PyroProgram:
    events: list[PyroEvent] = field(default_factory=list)
    payloads: dict[str, PyroPayload] = field(default_factory=dict)


@dataclass
class Drone:
    name: str
    trajectory: Trajectory
    lights: LightProgram = field(default_factory=LightProgram)
    yaw: list[YawSetpoint] | None = None
    auto_yaw: bool = False
    auto_yaw_offset: float = 0.0
    pyro: PyroProgram | None = None
    home: Vec3 | None = None
    land_at: Vec3 | None = None

    @property
    def home_position(self) -> Vec3:
        return self.home if self.home is not None else self.trajectory.first_position

    @property
    def landing_position(self) -> Vec3:
        return self.land_at if self.land_at is not None else self.trajectory.last_position


@dataclass
class Show:
    drones: list[Drone] = field(default_factory=list)
    title: str = "Untitled"
    limits: SafetyLimits = field(default_factory=SafetyLimits)
    cues: list[Cue] = field(default_factory=list)
    environment: str = "outdoor"
    location: ShowLocation | None = None
    cameras: list[Camera] = field(default_factory=list)
    audio: Audio | None = None
    segments: dict[str, tuple[float, float]] = field(default_factory=dict)
    timestamp_offset: float | None = None
    show_id: str | None = None

    @property
    def num_drones(self) -> int:
        return len(self.drones)

    @property
    def start_time(self) -> float:
        return min((d.trajectory.start_time for d in self.drones if d.trajectory), default=0.0)

    @property
    def end_time(self) -> float:
        return max((d.trajectory.end_time for d in self.drones if d.trajectory), default=0.0)

    @property
    def duration(self) -> float:
        return self.end_time - min(0.0, self.start_time)

    def positions_at(self, t: float) -> np.ndarray:
        """Returns the positions of all drones at time ``t``, shape ``(n, 3)``."""
        return np.array([d.trajectory.position_at(t)[0] for d in self.drones])

    def drone(self, name: str) -> Drone:
        for d in self.drones:
            if d.name == name:
                return d
        raise KeyError(name)


def _r(value: float, ndigits: int) -> float:
    v = round(float(value), ndigits)
    return 0.0 if v == 0 else v
