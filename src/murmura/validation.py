"""Safety validation of a show against its flight envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ._compat import KDTree as cKDTree
from .i18n import t
from .model import SafetyLimits, Show

__all__ = ("ValidationReport", "Violation", "validate_show")

_TOL = 1e-3


@dataclass
class Violation:
    check: str
    drone: str
    time: float
    value: float
    limit: float
    other: str | None = None

    def describe(self) -> str:
        who = f"{self.drone} / {self.other}" if self.other else self.drone
        return t(
            "{check}: {value:.2f} (limit {limit:.2f}) at t={time:.2f}s, {who}",
            check=t(self.check),
            value=self.value,
            limit=self.limit,
            time=self.time,
            who=who,
        )


@dataclass
class ValidationReport:
    title: str
    num_drones: int
    duration: float
    limits: SafetyLimits
    stats: dict[str, Any] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    series: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(self.counts.values())

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "passed": self.passed,
            "numDrones": self.num_drones,
            "duration": round(self.duration, 3),
            "stats": {
                k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.stats.items()
            },
            "violationCounts": self.counts,
            "violations": [
                {
                    "check": v.check,
                    "drone": v.drone,
                    "other": v.other,
                    "time": round(v.time, 3),
                    "value": round(v.value, 4),
                    "limit": round(v.limit, 4),
                }
                for v in self.violations
            ],
        }

    def summary_rows(self) -> list[tuple[str, bool]]:
        """Human-readable summary lines with a flag telling whether each one is OK."""
        s, lim = self.stats, self.limits
        minutes, seconds = divmod(self.duration, 60)
        rows: list[tuple[str, bool]] = [
            (
                t(
                    "Show: {title} - {drones} drones, {duration}",
                    title=self.title,
                    drones=self.num_drones,
                    duration=f"{int(minutes)}:{seconds:05.2f}",
                ),
                True,
            )
        ]

        def row(label, value, limit, unit, key, extra=""):
            if value is None:
                return
            bad = self.counts.get(key, 0)
            mark = t("FAIL") if bad else t(" OK ")
            unit = t(unit)
            lim_text = f" ({t('limit')} {limit:g} {unit})" if limit is not None else ""
            count = " - " + t("{count} violation(s)", count=bad) if bad else ""
            rows.append(
                (f"[{mark}] {t(label)}: {value:.2f} {unit}{lim_text}{count}{extra}", not bad)
            )

        row("Max altitude", s.get("maxAltitude"), lim.max_altitude, "m", "altitude")
        row(
            "Max horizontal speed",
            s.get("maxVelocityXY"),
            lim.max_velocity_xy,
            "m/s",
            "velocity_xy",
        )
        row(
            "Max climb speed",
            s.get("maxVelocityZUp"),
            lim.max_velocity_z_up or lim.max_velocity_z,
            "m/s",
            "velocity_z_up",
        )
        row(
            "Max descent speed",
            s.get("maxVelocityZDown"),
            lim.max_velocity_z,
            "m/s",
            "velocity_z_down",
        )
        row(
            "Max horizontal accel.",
            s.get("maxAccelerationXY"),
            lim.max_acceleration_xy,
            "m/s2",
            "acceleration_xy",
        )
        row(
            "Max vertical accel.",
            s.get("maxAccelerationZ"),
            lim.max_acceleration_z,
            "m/s2",
            "acceleration_z",
        )
        extra = ""
        if s.get("minDistancePair"):
            a, b = s["minDistancePair"]
            extra = t(" at t={time:.2f}s ({a} / {b})", time=s.get("minDistanceTime", 0), a=a, b=b)
        row(
            "Min distance (airborne)",
            s.get("minDistance"),
            lim.min_distance,
            "m",
            "distance",
            extra,
        )
        if "minShowAltitude" in s:
            row(
                "Min altitude during show",
                s["minShowAltitude"],
                lim.min_nav_altitude,
                "m",
                "nav_altitude",
            )
        if "maxYawRate" in s:
            row("Max yaw rate", s["maxYawRate"], lim.max_yaw_rate, "deg/s", "yaw_rate")
        rows.append((t("RESULT: PASSED") if self.passed else t("RESULT: FAILED"), self.passed))
        return rows

    def summary(self) -> str:
        return "\n".join(text for text, _ in self.summary_rows())


def validate_show(
    show: Show,
    *,
    limits: SafetyLimits | None = None,
    dt: float = 0.25,
    max_violations: int = 200,
) -> ValidationReport:
    """Samples every trajectory every ``dt`` seconds and checks altitude,
    velocity, acceleration, minimum distance, minimum navigation altitude
    during the show segment and yaw rate.

    Proximity is only checked between drones that are both at least
    ``min_nav_altitude`` above their home position, so that drones standing
    on a dense takeoff grid are not reported.
    """
    lim = limits or show.limits
    drones = [d for d in show.drones if d.trajectory]
    t_start = min(0.0, show.start_time)
    t_end = show.end_time
    times = np.arange(t_start, t_end + dt * 0.5, dt) if t_end > t_start else np.array([t_start])
    k, n = len(times), len(drones)

    report = ValidationReport(
        title=show.title, num_drones=len(show.drones), duration=t_end - t_start, limits=lim
    )
    counts = {
        key: 0
        for key in (
            "altitude",
            "velocity_xy",
            "velocity_z_up",
            "velocity_z_down",
            "acceleration_xy",
            "acceleration_z",
            "distance",
            "nav_altitude",
            "yaw_rate",
        )
    }
    violations: list[Violation] = []

    def flag(
        check: str, drone: str, t: float, value: float, limit: float, other: str | None = None
    ):
        counts[check] += 1
        if len(violations) < max_violations:
            violations.append(Violation(check, drone, float(t), float(value), float(limit), other))

    positions = np.zeros((k, n, 3), dtype=np.float32)
    series = {
        "time": times,
        "maxAltitude": np.full(k, -np.inf),
        "maxVelocityXY": np.zeros(k),
        "maxVelocityZ": np.zeros(k),
        "maxAcceleration": np.zeros(k),
        "minDistance": np.full(k, np.inf),
    }
    vz_up_limit = lim.max_velocity_z_up or lim.max_velocity_z
    show_segment = show.segments.get("show")
    stats: dict[str, Any] = {}
    min_show_alt = np.inf

    for j, drone in enumerate(drones):
        traj = drone.trajectory
        p = traj.position_at(times)
        v = traj.velocity_at(times)
        a = traj.acceleration_at(times)
        positions[:, j] = p
        vxy = np.hypot(v[:, 0], v[:, 1])
        axy = np.hypot(a[:, 0], a[:, 1])
        series["maxAltitude"] = np.maximum(series["maxAltitude"], p[:, 2])
        series["maxVelocityXY"] = np.maximum(series["maxVelocityXY"], vxy)
        series["maxVelocityZ"] = np.maximum(series["maxVelocityZ"], np.abs(v[:, 2]))
        series["maxAcceleration"] = np.maximum(series["maxAcceleration"], np.hypot(axy, a[:, 2]))

        for check, values, limit in (
            ("altitude", p[:, 2], lim.max_altitude),
            ("velocity_xy", vxy, lim.max_velocity_xy),
            ("velocity_z_up", v[:, 2], vz_up_limit),
            ("velocity_z_down", -v[:, 2], lim.max_velocity_z),
            ("acceleration_xy", axy, lim.max_acceleration_xy),
            ("acceleration_z", np.abs(a[:, 2]), lim.max_acceleration_z),
        ):
            bad = np.flatnonzero(values > limit * (1 + _TOL) + _TOL)
            if len(bad):
                worst = bad[np.argmax(values[bad])]
                counts[check] += len(bad) - 1
                flag(check, drone.name, times[worst], values[worst], limit)

        if show_segment is not None:
            home_z = drone.home_position[2]
            mask = (times >= show_segment[0]) & (times <= show_segment[1])
            if np.any(mask):
                rel = p[mask, 2] - home_z
                min_show_alt = min(min_show_alt, float(np.min(rel)))
                bad = np.flatnonzero(rel < lim.min_nav_altitude - _TOL)
                if len(bad):
                    counts["nav_altitude"] += len(bad) - 1
                    flag(
                        "nav_altitude",
                        drone.name,
                        times[mask][bad[0]],
                        rel[bad[0]],
                        lim.min_nav_altitude,
                    )

        if drone.yaw and len(drone.yaw) > 1:
            ts = np.array([s.time for s in drone.yaw])
            angles = np.array([s.angle for s in drone.yaw])
            rates = np.abs(np.diff(angles)) / np.maximum(np.diff(ts), 1e-9)
            stats["maxYawRate"] = max(stats.get("maxYawRate", 0.0), float(np.max(rates)))
            bad = np.flatnonzero(rates > lim.max_yaw_rate * (1 + _TOL))
            if len(bad):
                counts["yaw_rate"] += len(bad) - 1
                flag("yaw_rate", drone.name, ts[bad[0]], rates[bad[0]], lim.max_yaw_rate)

        stats["maxAltitude"] = max(stats.get("maxAltitude", -np.inf), float(np.max(p[:, 2])))
        stats["maxVelocityXY"] = max(stats.get("maxVelocityXY", 0.0), float(np.max(vxy)))
        stats["maxVelocityZUp"] = max(stats.get("maxVelocityZUp", 0.0), float(np.max(v[:, 2])))
        stats["maxVelocityZDown"] = max(stats.get("maxVelocityZDown", 0.0), float(np.max(-v[:, 2])))
        stats["maxAccelerationXY"] = max(stats.get("maxAccelerationXY", 0.0), float(np.max(axy)))
        stats["maxAccelerationZ"] = max(
            stats.get("maxAccelerationZ", 0.0), float(np.max(np.abs(a[:, 2])))
        )

    # Proximity between airborne drones
    if n >= 2:
        home_z = np.array([d.home_position[2] for d in drones])
        names = [d.name for d in drones]
        best = (np.inf, 0.0, None)
        for ti in range(k):
            pos = positions[ti].astype(float)
            airborne = np.flatnonzero(pos[:, 2] - home_z >= lim.min_nav_altitude)
            if len(airborne) < 2:
                continue
            sub = pos[airborne]
            tree = cKDTree(sub)
            dist, idx = tree.query(sub, k=2)
            nearest = dist[:, 1]
            m = int(np.argmin(nearest))
            series["minDistance"][ti] = nearest[m]
            if nearest[m] < best[0]:
                best = (
                    float(nearest[m]),
                    float(times[ti]),
                    (names[airborne[m]], names[airborne[idx[m, 1]]]),
                )
            close = np.flatnonzero(nearest < lim.min_distance - _TOL)
            if len(close):
                pairs = {tuple(sorted((int(airborne[c]), int(airborne[idx[c, 1]])))) for c in close}
                for a_idx, b_idx in pairs:
                    d = float(np.linalg.norm(pos[a_idx] - pos[b_idx]))
                    flag("distance", names[a_idx], times[ti], d, lim.min_distance, names[b_idx])
        if best[2] is not None:
            stats["minDistance"] = best[0]
            stats["minDistanceTime"] = best[1]
            stats["minDistancePair"] = list(best[2])

    if np.isfinite(min_show_alt):
        stats["minShowAltitude"] = min_show_alt

    series["maxAltitude"][~np.isfinite(series["maxAltitude"])] = 0.0
    report.stats = stats
    report.counts = counts
    report.violations = violations
    report.series = series
    return report
