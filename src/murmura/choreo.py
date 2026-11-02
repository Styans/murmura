"""High-level show composition: takeoff, scenes with transitions, landing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ._compat import KDTree
from .colors import parse_color
from .effects import Effect, FormationColors, Solid, make_effect
from .i18n import plan_label
from .i18n import t as tr
from .lights import LightProgram
from .model import Audio, Cue, Drone, SafetyLimits, Show, ShowLocation
from .planning import (
    match_points,
    min_transition_durations,
    plan_waves,
    takeoff_layers,
)
from .planning.dissolve import plan_dissolve
from .planning.matching import synchronized_clearance
from .planning.transition import MovePlan, plan_safe_moves, synchronised_plan
from .trajectory import Trajectory

__all__ = ("Motion", "ShowBuilder", "make_motion")


# ----------------------------------------------------------------------
# Motions applied to a formation while it is being held
# ----------------------------------------------------------------------


def _ramped_time(tau: np.ndarray, total: float, ramp: float) -> np.ndarray:
    """Time warped so that the motion speed ramps up and down smoothly.

    The derivative is 0 at both ends, rises along a smoothstep during
    ``ramp`` seconds and is 1 in between.
    """
    ramp = min(ramp, total / 2)
    if ramp <= 1e-9:
        return np.asarray(tau, dtype=float)
    tau = np.clip(np.asarray(tau, dtype=float), 0.0, total)

    def integral(x):  # ∫ smoothstep from 0 to x (x in units of ramp)
        x = np.clip(x, 0.0, 1.0)
        return ramp * (x**3 - 0.5 * x**4)

    head = integral(tau / ramp)
    middle = np.clip(tau - ramp, 0.0, total - 2 * ramp)
    tail = np.where(tau > total - ramp, ramp / 2 - integral((total - tau) / ramp), 0.0)
    return head + middle + tail


def _envelope(tau: np.ndarray, total: float, ramp: float) -> np.ndarray:
    ramp = min(ramp, total / 2)
    if ramp <= 1e-9:
        return np.ones_like(np.asarray(tau, dtype=float))
    x = np.clip(np.minimum(tau, total - tau) / ramp, 0.0, 1.0)
    return x * x * (3 - 2 * x)


@dataclass
class Motion:
    """Animated motion of a held formation.

    kinds:
        ``rotate``: spin around a vertical axis through ``center`` (or the
        formation centroid) at ``rpm`` revolutions per minute
        ``breathe``: scale in and out by ``amplitude`` (relative) with ``period``
        ``wave``: vertical wave travelling along ``along`` with ``amplitude``
        metres, ``wavelength`` metres and ``period`` seconds
    """

    kind: str = "rotate"
    rpm: float = 2.0
    amplitude: float = 0.15
    period: float = 4.0
    wavelength: float = 12.0
    along: str = "x"
    center: Sequence[float] | None = None
    ramp: float = 2.0

    def positions(self, base: np.ndarray, tau: np.ndarray, total: float) -> np.ndarray:
        """Positions of all drones at times ``tau`` (shape ``(k, n, 3)``)."""
        base = np.asarray(base, dtype=float)
        tau = np.atleast_1d(np.asarray(tau, dtype=float))
        c = np.asarray(self.center, dtype=float) if self.center is not None else base.mean(axis=0)
        if self.kind == "rotate":
            angle = 2 * np.pi * self.rpm / 60.0 * _ramped_time(tau, total, self.ramp)
            cos, sin = np.cos(angle)[:, None], np.sin(angle)[:, None]
            rel = base - c
            x = rel[None, :, 0] * cos - rel[None, :, 1] * sin
            y = rel[None, :, 0] * sin + rel[None, :, 1] * cos
            z = np.broadcast_to(rel[None, :, 2], x.shape)
            return np.stack([x, y, z], axis=-1) + c
        env = _envelope(tau, total, self.ramp)[:, None]
        if self.kind == "breathe":
            scale = 1 + self.amplitude * env * np.sin(2 * np.pi * tau / self.period)[:, None]
            return c + (base - c)[None] * scale[..., None]
        if self.kind == "wave":
            axis = {"x": 0, "y": 1, "z": 2}[self.along]
            phase = 2 * np.pi * (base[None, :, axis] / self.wavelength - tau[:, None] / self.period)
            dz = (
                self.amplitude
                * env
                * (np.sin(phase) - np.sin(2 * np.pi * base[None, :, axis] / self.wavelength))
            )
            out = np.repeat(base[None], len(tau), axis=0)
            out[..., 2] += dz
            return out
        raise ValueError(f"unknown motion kind: {self.kind!r}")

    def _peaks(
        self, base: np.ndarray, total: float, dt: float = 0.05
    ) -> tuple[float, float, float, float]:
        """Peak horizontal / vertical speed and acceleration of the motion."""
        taus = np.arange(0.0, total + dt, dt)
        p = self.positions(base, taus, total)
        v = np.diff(p, axis=0) / dt
        a = np.diff(v, axis=0) / dt
        return (
            float(np.max(np.hypot(v[..., 0], v[..., 1]), initial=0.0)),
            float(np.max(np.abs(v[..., 2]), initial=0.0)),
            float(np.max(np.hypot(a[..., 0], a[..., 1]), initial=0.0)),
            float(np.max(np.abs(a[..., 2]), initial=0.0)),
        )

    def fitted_to_limits(
        self, base: np.ndarray, total: float, limits: SafetyLimits, *, margin: float = 0.85
    ) -> tuple[Motion, list[str]]:
        """Returns a copy whose speed and acceleration respect ``limits``:
        ramps are lengthened first, then the rate or amplitude is reduced."""
        m = Motion(**{k: getattr(self, k) for k in self.__dataclass_fields__})
        notes: list[str] = []
        vxy, vz = limits.max_velocity_xy * margin, limits.max_velocity_z * margin
        axy, az = limits.max_acceleration_xy * margin, limits.max_acceleration_z * margin
        for _ in range(12):
            sxy, sz, accxy, accz = m._peaks(base, total)
            speed_ratio = max(sxy / vxy, sz / vz)
            acc_ratio = max(accxy / axy, accz / az)
            if speed_ratio <= 1.0 and acc_ratio <= 1.0:
                break
            if speed_ratio > 1.0:
                m._scale_rate(1.0 / speed_ratio)
                notes.append(
                    tr("{kind} motion slowed down to respect the speed limit", kind=tr(m.kind))
                )
            elif m.ramp < total / 2 - 1e-6:
                m.ramp = min(total / 2, m.ramp * max(1.2, acc_ratio))
            else:
                m._scale_rate(1.0 / np.sqrt(acc_ratio))
                notes.append(
                    tr("{kind} motion softened to respect the acceleration limit", kind=tr(m.kind))
                )
        return m, sorted(set(notes))

    def _scale_rate(self, factor: float) -> None:
        if self.kind == "rotate":
            self.rpm *= factor
        else:
            self.amplitude *= factor


def make_motion(spec: dict[str, Any] | str | None) -> Motion | None:
    if spec is None or spec is False:
        return None
    if isinstance(spec, str):
        return Motion(kind=spec)
    spec = dict(spec)
    kind = spec.pop("kind", spec.pop("type", None))
    if kind is None and len(spec) == 1 and isinstance(next(iter(spec.values())), dict):
        kind, params = next(iter(spec.items()))
        spec = dict(params)
    return Motion(kind=str(kind or "rotate"), **spec)


# ----------------------------------------------------------------------
# Builder
# ----------------------------------------------------------------------


class ShowBuilder:
    """Composes a complete drone show step by step.

    Example::

        b = ShowBuilder(50, title="Demo")
        b.takeoff(altitude=6)
        b.scene("Ring", formations.circle(50, radius=15, center=(0, 0, 25)), hold=8,
                effect=Rainbow(period=4))
        b.land()
        show = b.build()
    """

    def __init__(
        self,
        num_drones: int,
        *,
        title: str = "Murmura show",
        limits: SafetyLimits | None = None,
        home: np.ndarray | Sequence[Sequence[float]] | None = None,
        grid_spacing: float | None = None,
        grid_columns: int | None = None,
        names: Sequence[str] | None = None,
        light_fps: float = 10.0,
        motion_fps: float = 8.0,
        fit_tolerance: float = 0.02,
        profile: str = "smooth",
        stagger: bool = True,
        speed_margin: float = 0.97,
        start_time: float = 0.0,
    ):
        if num_drones <= 0:
            raise ValueError("a show needs at least one drone")
        self.n = int(num_drones)
        self.title = title
        self.limits = limits or SafetyLimits()
        if home is None:
            from .formations import grid

            spacing = (
                grid_spacing if grid_spacing is not None else max(self.limits.min_distance, 1.5)
            )
            home = grid(self.n, spacing=spacing, columns=grid_columns)
        self.home = np.asarray(home, dtype=float).reshape(-1, 3)
        if len(self.home) != self.n:
            raise ValueError(f"expected {self.n} home positions, got {len(self.home)}")
        self.names = list(names) if names else [f"Drone {i + 1}" for i in range(self.n)]
        self.light_fps = float(light_fps)
        self.motion_fps = float(motion_fps)
        self.fit_tolerance = float(fit_tolerance)
        self.profile = profile
        self.stagger = stagger
        # plan slightly below the limits so that resampled exports stay inside them
        self.speed_margin = float(speed_margin)

        self.t = float(start_time)
        self.positions = self.home.copy()
        self.trajectories = [Trajectory().start_at(self.t, p) for p in self.home]
        self.lights = [LightProgram() for _ in range(self.n)]
        self.colors = np.zeros((self.n, 3))
        self.slot_colors: np.ndarray | None = None
        self.active: np.ndarray | None = None
        self.dark: np.ndarray | None = None
        self.cues: list[Cue] = []
        self.segments: dict[str, tuple[float, float]] = {}
        self.audio: Audio | None = None
        self.location: ShowLocation | None = None
        self.takeoff_altitudes: np.ndarray | None = None
        self.log: list[str] = []

    # ------------------------------------------------------------------
    # Lights
    # ------------------------------------------------------------------

    def _set_colors(
        self, t: float, colors: np.ndarray, *, fade: bool = True, raw: bool = False
    ) -> None:
        colors = np.clip(np.round(np.asarray(colors, dtype=float)), 0, 255)
        if colors.ndim == 1:
            colors = np.tile(colors, (self.n, 1))
        if not raw:
            # drones outside the current group keep their colour, idle ones go dark
            if self.active is not None:
                colors = np.where(self.active[:, None], colors, self.colors)
            if self.dark is not None:
                colors = np.where(self.dark[:, None], 0.0, colors)
        for i in range(self.n):
            self.lights[i].add(t, tuple(int(v) for v in colors[i]), fade)
        self.colors = colors

    def _anchor_colors(self) -> None:
        """Pins the current colours at the current time so that the next
        fade starts now and not at the previous keyframe."""
        self._set_colors(self.t, self.colors, fade=True, raw=True)

    def _apply_effect(
        self, effect: Effect, t0: float, t1: float, sampler, *, moving: bool = False
    ) -> None:
        """Samples ``effect`` between ``t0`` and ``t1``; ``sampler(times)``
        returns the drone positions at those times, shape ``(k, n, 3)``.
        Static effects are sampled densely too when the drones are ``moving``
        because their colours may depend on position."""
        if t1 <= t0:
            return
        if effect.static and not moving:
            pos = sampler(np.array([t0]))[0]
            colors = effect(0.0, pos, self.slot_colors)
            self._set_colors(t0, colors, fade=True)
            self._set_colors(t1, colors, fade=True)
            return
        step = 1.0 / self.light_fps
        times = np.arange(t0, t1, step)
        times = np.append(times[times < t1 - 1e-6], t1)
        positions = sampler(times)
        for t, pos in zip(times, positions):
            self._set_colors(float(t), effect(float(t - t0), pos, self.slot_colors), fade=True)

    # ------------------------------------------------------------------
    # Motion primitives
    # ------------------------------------------------------------------

    def _static_sampler(self):
        pos = self.positions.copy()
        return lambda times: np.repeat(pos[None], len(times), axis=0)

    def wait(self, duration: float, *, effect: Effect | None = None) -> ShowBuilder:
        """Holds the current formation for ``duration`` seconds."""
        if duration <= 0:
            return self
        t0, t1 = self.t, self.t + duration
        for traj in self.trajectories:
            traj.hold_until(t1)
        if effect is not None:
            self._apply_effect(effect, t0, t1, self._static_sampler())
        else:
            self._set_colors(t1, self.colors, fade=True)
        self.t = t1
        return self

    def wait_until(self, t: float) -> ShowBuilder:
        if t > self.t:
            self.wait(t - self.t)
        return self

    def takeoff(
        self,
        *,
        altitude: float = 6.0,
        layered: bool = True,
        layer_spacing: float | None = None,
        color: Any = (80, 80, 80),
        duration: float | None = None,
        climb_velocity: float | None = None,
        rows: int = 0,
    ) -> ShowBuilder:
        """Vertical takeoff from the home positions.

        ``rows`` asks for at least that many waves (2: checkerboard, 4: every
        other drone in both directions) even when fewer would do.

        With ``layered`` takeoff, drones standing closer than the minimum
        distance take off in waves (a checkerboard on a square grid): each
        wave climbs to its own altitude layer, the first wave highest, and
        starts only when the drones above it are far enough away. When the
        pad spacing already respects the minimum distance, every drone takes
        off at once.

        The climb speed is ``climb_velocity`` (peak speed), derived from
        ``duration`` when only that is given, and never above the limits.
        """
        if layered:
            groups, gap = takeoff_layers(
                self.home, min_distance=self.limits.min_distance, min_waves=rows
            )
        else:
            groups, gap = np.zeros(self.n, dtype=int), 0.0
        if layer_spacing is not None and gap > 0:
            gap = max(gap, float(layer_spacing))
        waves = int(groups.max(initial=0)) + 1
        heights = altitude + (waves - 1 - np.arange(waves)) * gap
        self.takeoff_altitudes = heights[groups]

        m = self.speed_margin
        kv = 1.5  # peak / average speed of the smooth profile
        if climb_velocity is None:
            climb_velocity = kv * altitude / duration if duration else float("inf")
        limit_up = (self.limits.max_velocity_z_up or self.limits.max_velocity_z) * m
        starts, durations = plan_waves(
            heights,
            gap=gap,
            velocity=min(climb_velocity, limit_up),
            max_acceleration=self.limits.max_acceleration_z * m,
        )

        t0 = self.t
        self.cues.append(Cue(t0, tr("Takeoff")))
        self._set_colors(t0, np.array(parse_color(color), dtype=float), fade=False)
        targets = self.home.copy()
        targets[:, 2] += self.takeoff_altitudes
        for i, traj in enumerate(self.trajectories):
            k = groups[i]
            traj.hold_until(t0 + starts[k])
            traj.smooth_to(t0 + starts[k] + durations[k], targets[i])
        end = t0 + float(np.max(starts + durations))
        for traj in self.trajectories:
            traj.hold_until(end)
        self.positions = targets
        self.t = end
        self.segments["takeoff"] = (t0, end)
        if waves > 1:
            self.log.append(
                tr(
                    "takeoff in {count} waves, layers {gap:.1f} m apart",
                    count=waves,
                    gap=gap,
                )
            )
        return self

    def _duration_fn(self, profile: str):
        m = self.speed_margin

        def duration_fn(delta: np.ndarray) -> np.ndarray:
            return min_transition_durations(
                delta,
                max_velocity_xy=self.limits.max_velocity_xy * m,
                max_velocity_z=self.limits.max_velocity_z * m,
                max_velocity_z_up=(self.limits.max_velocity_z_up or self.limits.max_velocity_z) * m,
                max_acceleration=self.limits.max_acceleration_xy * m,
                max_acceleration_z=self.limits.max_acceleration_z * m,
                profile=profile,
            )

        return duration_fn

    def _plan_move(
        self,
        targets: np.ndarray,
        *,
        duration: float | None = None,
        profile: str,
        stagger: bool | None = None,
        label: str = "transition",
        mirror: bool = False,
    ) -> tuple[MovePlan | None, float]:
        """Plans the move of drone i to ``targets[i]`` without performing it;
        returns the plan (``None`` if nothing moves) and its separation.

        With ``mirror`` the move is planned as if the drones flew from the
        targets to their current positions and then played backwards, so a
        return to the takeoff points retraces the flight out of them. The
        search for it is kept short, as the caller has a fallback.
        """
        duration_fn = self._duration_fn(profile)
        window = float(np.max(duration_fn(targets - self.positions), initial=0.0))
        if duration is not None:
            if duration + 1e-9 < window:
                self.log.append(
                    tr(
                        "{label}: requested {requested:.2f}s is too short, using {used:.2f}s",
                        label=label,
                        requested=duration,
                        used=window,
                    )
                )
            window = max(window, float(duration))
        if window <= 0:
            return None, float("inf")
        if not (self.stagger if stagger is None else stagger):
            return synchronised_plan(self.positions, targets, window, profile), float("inf")

        if not mirror:
            return plan_safe_moves(
                self.positions,
                targets,
                min_distance=self.limits.min_distance,
                duration_fn=duration_fn,
                profile=profile,
                minimum_window=window,
            )
        plan, separation = plan_safe_moves(
            targets,
            self.positions,
            min_distance=self.limits.min_distance,
            duration_fn=lambda delta: duration_fn(-delta),
            profile=profile,
            minimum_window=window,
            time_limit=5.0,
        )
        return plan.reversed(), separation

    def _perform(self, plan: MovePlan | None, separation: float, targets, *, label: str) -> float:
        """Writes a planned move into the trajectories; returns its duration."""
        if plan is None:
            return 0.0
        if plan.label != "synchronised":
            self.log.append(
                tr(
                    "{label}: {plan} transition keeps {separation:.2f} m separation",
                    label=label,
                    plan=plan_label(plan.label),
                    separation=separation,
                )
            )
        if separation < self.limits.min_distance - 1e-3:
            self.log.append(
                tr("warning")
                + ": "
                + tr(
                    "{label}: could only keep {separation:.2f} m between drones (minimum {minimum:g} m)",
                    label=label,
                    separation=separation,
                    minimum=self.limits.min_distance,
                )
            )
        t0 = self.t
        total = plan.total_duration
        for i, traj in enumerate(self.trajectories):
            for k in range(plan.starts.shape[1]):
                start = t0 + plan.starts[i, k]
                end = start + plan.durations[i, k]
                goal = plan.waypoints[i, k + 1]
                if np.allclose(goal, plan.waypoints[i, k], atol=1e-6):
                    continue
                traj.hold_until(start)
                traj.smooth_to(end, goal, profile=plan.profile)
            traj.hold_until(t0 + total)
        self.positions = np.asarray(targets, dtype=float).copy()
        self.t = t0 + total
        return total

    def _move_to(
        self,
        targets: np.ndarray,
        *,
        duration: float | None = None,
        profile: str | None = None,
        stagger: bool | None = None,
        label: str = "transition",
    ) -> float:
        """Moves drone i to ``targets[i]`` along straight lines; returns the
        duration of the move."""
        targets = np.asarray(targets, dtype=float)
        plan, separation = self._plan_move(
            targets,
            duration=duration,
            profile=profile or self.profile,
            stagger=stagger,
            label=label,
        )
        return self._perform(plan, separation, targets, label=label)

    def transition_to(
        self,
        points: np.ndarray | Sequence[Sequence[float]],
        *,
        colors: np.ndarray | None = None,
        duration: float | None = None,
        profile: str | None = None,
        stagger: bool | None = None,
        matching: str = "optimal",
        effect: Effect | None = None,
        name: str = "transition",
        drones: Sequence[int] | None = None,
    ) -> list[int]:
        """Flies the swarm (or only the ``drones`` given by index) into a new
        formation.

        Every point gets a drone; if there are fewer points than drones, the
        drones left over stay where they are with their lights off. Drones
        outside ``drones`` keep flying their current position and colour.

        Returns the target point index of each drone (-1 when it has none).
        """
        pts = np.asarray(points, dtype=float).reshape(-1, 3)
        group = np.arange(self.n) if drones is None else np.asarray(drones, dtype=int)
        if len(pts) > len(group):
            raise ValueError(
                f"formation {name!r} has {len(pts)} points but only {len(group)} drones can fly"
            )
        slot = np.full(self.n, -1)
        if matching == "fixed" and len(pts) == len(group):
            slot[group] = np.arange(len(group))
        elif matching in ("optimal", "fixed"):
            mapping = match_points(self.positions[group], pts)  # target -> drone in group
            for target, member in enumerate(mapping):
                slot[group[member]] = target  # type: ignore[index]
        else:
            raise ValueError(f"unknown matching method: {matching!r}")
        moving = slot >= 0
        targets = self.positions.copy()
        targets[moving] = pts[slot[moving]]
        in_group = np.zeros(self.n, dtype=bool)
        in_group[group] = True
        self.active = in_group if drones is not None else None
        idle = in_group & ~moving
        self.dark = idle if idle.any() else None
        if colors is None:
            self.slot_colors = None
        else:
            self.slot_colors = self.colors.copy()
            self.slot_colors[moving] = np.asarray(colors, dtype=float)[slot[moving]]
        assignment = slot.tolist()

        t0 = self.t
        self._anchor_colors()
        self._move_to(targets, duration=duration, profile=profile, stagger=stagger, label=name)
        if effect is not None and self.t > t0:
            trajs = self.trajectories
            self._apply_effect(
                effect,
                t0,
                self.t,
                lambda times: np.stack([tr.position_at(times) for tr in trajs], axis=1),
                moving=True,
            )
        return assignment

    def hold(
        self,
        duration: float,
        *,
        effect: Effect | None = None,
        motion: Motion | None = None,
    ) -> ShowBuilder:
        """Holds the current formation for ``duration`` seconds, optionally
        animating it with ``motion`` and running a light ``effect``."""
        if duration <= 0:
            return self
        t0, t1 = self.t, self.t + duration
        effect = effect or Solid("white")

        if motion is None:
            for traj in self.trajectories:
                traj.hold_until(t1)
            self._apply_effect(effect, t0, t1, self._static_sampler())
        else:
            base = self.positions.copy()
            motion, notes = motion.fitted_to_limits(base, duration, self.limits)
            self.log.extend(notes)
            k = max(2, int(np.ceil(duration * self.motion_fps)) + 1)
            taus = np.linspace(0.0, duration, k)
            frames = motion.positions(base, taus, duration)  # (k, n, 3)
            if self.active is not None:  # only the current group moves
                frames[:, ~self.active] = base[~self.active]
            for i, traj in enumerate(self.trajectories):
                traj.extend_with_samples(t0 + taus, frames[:, i, :], tolerance=self.fit_tolerance)
            self.positions = frames[-1].copy()

            def sampler(times):
                return motion.positions(base, np.asarray(times) - t0, duration)

            self._apply_effect(effect, t0, t1, sampler, moving=True)
        self.t = t1
        return self

    def scene(
        self,
        name: str,
        points: np.ndarray | Sequence[Sequence[float]],
        *,
        hold: float = 5.0,
        colors: np.ndarray | None = None,
        effect: Effect | None = None,
        motion: Motion | None = None,
        transition_duration: float | None = None,
        transition_effect: Effect | None = None,
        profile: str | None = None,
        stagger: bool | None = None,
        matching: str = "optimal",
        start: float | None = None,
        drones: Sequence[int] | None = None,
        keep_lights: bool = False,
    ) -> ShowBuilder:
        """Transition into a formation and hold it.

        ``drones`` limits the scene to a group of drones (by index); with
        ``keep_lights`` the lights are left as they are.

        Lights fade from the previous scene into the new effect during the
        transition unless ``transition_effect`` is given. ``start`` pins the
        start of the transition to an absolute show time (e.g. a beat).
        """
        if start is not None:
            self.wait_until(start)
        if effect is None:
            effect = FormationColors() if colors is not None else Solid("white")
        t0 = self.t
        self.cues.append(Cue(t0, name))
        self.transition_to(
            points,
            colors=colors,
            duration=transition_duration,
            profile=profile,
            stagger=stagger,
            matching=matching,
            effect=None if keep_lights else transition_effect,
            name=name,
            drones=drones,
        )
        if keep_lights:
            effect = None
        elif transition_effect is None:
            target_colors = effect(0.0, self.positions, self.slot_colors)
            self._set_colors(self.t, target_colors, fade=True)
        if "show" not in self.segments:
            self.segments["show"] = (t0, t0)
        if effect is None:
            if motion is None:
                self.wait(hold)
            else:
                self.hold(hold, effect=_KeepColors(self.colors), motion=motion)
        else:
            self.hold(hold, effect=effect, motion=motion)
        self.segments["show"] = (self.segments["show"][0], self.t)
        self.active = self.dark = None
        return self

    def land(
        self,
        *,
        velocity: float = 1.0,
        spindown: float = 3.0,
        altitude: float | None = None,
        target: str = "home",
        color: Any = (80, 80, 80),
        layered: bool = True,
        staging_spread: float | None = None,
        rows: int = 0,
        sequential: bool = True,
        style: str = "dissolve",
        order: str = "random",
        interval: float = 0.15,
    ) -> ShowBuilder:
        """Returns every drone above a landing spot and lands the swarm.

        ``target="home"`` (default) sends every drone back to the very point
        where it hovered after takeoff, retracing the flight out of it: the
        return is planned like a transition from the takeoff points into the
        current formation and played backwards. The landing then mirrors the
        takeoff wave by wave. ``target="nearest"`` assigns landing spots (the
        home grid) optimally instead.

        With ``staging_spread`` the swarm first forms a horizontal copy of the
        landing grid enlarged by that factor at the mean altitude of the
        current formation, then contracts and descends uniformly onto the
        landing grid. The second step is an affine blend of two similar grids,
        so it can never bring drones closer than the grid spacing.

        The swarm lands in rows (the takeoff waves, at least ``rows`` of
        them), lowest layer first; with ``sequential`` a row starts only when
        the previous one has touched down plus ``spindown`` seconds.

        ``style="dissolve"`` (default) makes the formation fall apart drone by
        drone like sakura petals: each drone leaves on its turn (``order``,
        about ``interval`` seconds apart), flies straight to its point above
        a landing spot and lands at once (see :meth:`_land_dissolve`);
        ``style="morph"`` re-forms the swarm in the air into its home grid with
        every drone moving at once and lands it row by row (see
        :meth:`_land_morph`). Both take the nearest free spots, so ``target``
        does not apply to them; ``style="direct"`` flies the return described
        above.
        """
        if style not in ("dissolve", "morph", "direct"):
            raise ValueError("return style must be 'dissolve', 'morph' or 'direct'")
        spots = self.home.copy()
        hover = altitude
        if hover is None:
            hover = (
                float(np.min(self.takeoff_altitudes)) if self.takeoff_altitudes is not None else 6.0
            )
        if style == "dissolve":
            return self._land_dissolve(
                hover=hover,
                velocity=velocity,
                spindown=spindown,
                color=color,
                order=order,
                interval=interval,
            )
        if style == "morph":
            return self._land_morph(
                hover=hover,
                rows=rows,
                velocity=velocity,
                spindown=spindown,
                sequential=sequential,
                color=color,
            )
        if layered:
            groups, gap = takeoff_layers(
                spots, min_distance=self.limits.min_distance, min_waves=rows
            )
        else:
            groups, gap = np.zeros(self.n, dtype=int), 0.0
        waves = int(groups.max(initial=0)) + 1
        heights = hover + (waves - 1 - np.arange(waves)) * gap
        # the same altitude layers as the takeoff: wave 0 highest
        layer = (waves - 1 - groups) * gap
        lift = heights[groups]

        if staging_spread:
            centre = spots.mean(axis=0)
            slots = centre + (spots - centre) * staging_spread
            slots[:, 2] = max(
                float(np.mean(self.positions[:, 2])),
                float(np.max(spots[:, 2] + lift)) + self.limits.min_distance,
            )
            slots[:, 2] += layer
        else:
            slots = spots.copy()
            slots[:, 2] = spots[:, 2] + lift

        if target not in ("nearest", "home"):
            raise ValueError("landing target must be 'nearest' or 'home'")
        home_spots, home_slots, home_lift, home_groups = spots, slots, lift, groups

        def nearest_order() -> np.ndarray:
            mapping = match_points(self.positions, home_slots)
            order = np.zeros(self.n, dtype=int)
            for slot, drone in enumerate(mapping):
                order[drone] = slot  # type: ignore[index]
            return order

        label = tr("return")
        profile = self.profile
        order = np.arange(self.n) if target == "home" else nearest_order()
        slots = home_slots[order]
        plan, separation = self._plan_move(
            slots, profile=profile, label=label, mirror=target == "home" and not staging_spread
        )
        if target == "home" and separation < self.limits.min_distance - 1e-3:
            # the own takeoff points cannot be reached safely from here
            fallback = nearest_order()
            other_slots = home_slots[fallback]
            other, other_separation = self._plan_move(other_slots, profile=profile, label=label)
            if other_separation > separation:
                self.log.append(
                    tr("return: drones land on the nearest free spots, their own were not safe")
                )
                order, slots, plan, separation = fallback, other_slots, other, other_separation
        spots, lift, groups = home_spots[order], home_lift[order], home_groups[order]
        above = spots.copy()
        above[:, 2] = spots[:, 2] + lift

        t0 = self.t
        self.cues.append(Cue(t0, tr("Landing")))
        self._anchor_colors()
        self._perform(plan, separation, slots, label=label)
        if staging_spread:
            self._move_to(above, label=tr("approach"), stagger=False)
        return self._land_rows(
            t0,
            spots,
            groups,
            heights,
            gap,
            velocity=velocity,
            spindown=spindown,
            sequential=sequential,
            color=color,
        )

    def _land_rows(
        self,
        t0: float,
        spots: np.ndarray,
        groups: np.ndarray,
        heights: np.ndarray,
        gap: float,
        *,
        velocity: float,
        spindown: float,
        sequential: bool,
        color: Any,
    ) -> ShowBuilder:
        """Lands drones hovering above ``spots`` in altitude rows ``heights``
        (row ``groups[i]`` for drone ``i``, row 0 highest), lowest row first."""
        self._set_colors(self.t, np.array(parse_color(color), dtype=float), fade=True)
        waves = len(heights)
        # the takeoff played backwards: the lowest wave lands first, the next
        # one descends when it stays far enough above, neighbours touch down
        # at least ``spindown`` seconds apart
        m = self.speed_margin
        climb, durations = plan_waves(
            heights,
            gap=gap,
            velocity=min(velocity, self.limits.max_velocity_z * m),
            max_acceleration=self.limits.max_acceleration_z * m,
            min_offset=spindown if waves > 1 else 0.0,
            sequential=sequential,
        )
        total = float(np.max(climb + durations))
        t1 = self.t
        for i, traj in enumerate(self.trajectories):
            k = groups[i]
            touch = t1 + total - climb[k]
            traj.hold_until(touch - durations[k])
            traj.smooth_to(touch, spots[i])
            self.lights[i].add(touch, (0, 0, 0), False)
        end = t1 + total
        for traj in self.trajectories:
            traj.hold_until(end)
        self.positions = spots
        self.t = end
        self.segments["landing"] = (t0, end)
        if waves > 1:
            self.log.append(tr("landing in {count} waves", count=waves))
        return self

    def _home_grid(self, hover: float, spacing: float, rows: int = 0):
        """Points above every landing spot in altitude rows, drones of a row at
        least ``spacing`` apart: (row of each spot, row heights, gap, points)."""
        groups, gap = takeoff_layers(self.home, min_distance=spacing, min_waves=rows)
        waves = int(groups.max(initial=0)) + 1
        heights = hover + (waves - 1 - np.arange(waves)) * gap
        air = self.home.copy()
        air[:, 2] += heights[groups]
        return groups, heights, gap, air

    def _waiting_above_pad(self) -> np.ndarray:
        """Drones still hovering where they were after takeoff (not used by
        the last formation)."""
        if self.takeoff_altitudes is None:
            return np.zeros(self.n, dtype=bool)
        hover_points = self.home.copy()
        hover_points[:, 2] += self.takeoff_altitudes
        return np.linalg.norm(self.positions - hover_points, axis=1) < 1e-3

    def _land_dissolve(
        self,
        *,
        hover: float,
        velocity: float,
        spindown: float,
        color: Any,
        order: str,
        interval: float,
    ) -> ShowBuilder:
        """The formation falls apart drone by drone like sakura petals: each
        drone leaves on its turn, flies straight to its point above a free
        landing spot and lands at once, while the others are still leaving.

        The formation first breathes out to sqrt(2) times the minimum
        distance (uniform scaling, safe) and the points above the pad use the
        same spacing within a row; drones that are not in the formation land
        first, from where they hover. Departures are planned drone by drone
        so that every pair keeps the minimum distance (see
        :func:`~murmura.planning.plan_dissolve`); if that fails the swarm
        re-forms and lands row by row instead.
        """
        d = self.limits.min_distance
        need = float(np.sqrt(2.0) * d * 1.02)
        _, _, _, air = self._home_grid(hover, need)
        t0 = self.t
        self.cues.append(Cue(t0, tr("Landing")))
        self._anchor_colors()
        label = tr("return")

        waiting = self._waiting_above_pad()
        flying = np.flatnonzero(~waiting)
        wide = self.positions.copy()
        wide[flying] = _breathe_out(self.positions[flying], need)
        if not np.allclose(wide, self.positions):
            self._move_to(wide, stagger=False, label=label)

        start = self.positions.copy()
        above = start.copy()  # drones not in the formation land from where they are
        ground = self.home.copy()
        free = np.flatnonzero(~waiting)  # spots whose drones are in the formation
        for slot, drone in enumerate(match_points(start[flying], air[free])):
            above[flying[drone]] = air[free[slot]]  # type: ignore[index]
            ground[flying[drone]] = self.home[free[slot]]  # type: ignore[index]
        m = self.speed_margin
        plan = plan_dissolve(
            start,
            above,
            ground,
            min_distance=d,
            flight_durations=self._duration_fn(self.profile)(above - start),
            landing_velocity=min(velocity, self.limits.max_velocity_z * m),
            max_acceleration_z=self.limits.max_acceleration_z * m,
            airborne_altitude=self.limits.min_nav_altitude,
            spindown=spindown,
            order=order,
            interval=interval,
            first=waiting,
        )
        if not plan.complete:
            self.log.append(
                tr("return: crumbling is not possible here, the swarm re-forms into its homes")
            )
            return self._land_morph(
                hover=hover,
                rows=0,
                velocity=velocity,
                spindown=spindown,
                sequential=True,
                color=color,
            )

        t1 = self.t
        dark = np.array(parse_color(color), dtype=float)
        for i, traj in enumerate(self.trajectories):
            leave = t1 + float(plan.departures[i])
            arrive = leave + float(plan.flight[i])
            touch = arrive + float(plan.descent[i])
            traj.hold_until(leave)
            if plan.flight[i] > 0 and not np.allclose(start[i], above[i], atol=1e-6):
                traj.smooth_to(arrive, above[i])
            traj.smooth_to(touch, ground[i])
            self.lights[i].add(arrive, dark, True)
            self.lights[i].add(touch, (0, 0, 0), False)
        end = t1 + plan.total_duration
        for traj in self.trajectories:
            traj.hold_until(end)
        self.positions = ground
        self.t = end
        self.segments["landing"] = (t0, end)
        self.log.append(
            tr(
                "return like falling petals: drones leave one by one over {seconds:.0f} s"
                " and land at once",
                seconds=float(np.ptp(plan.departures[flying])) if len(flying) else 0.0,
            )
        )
        return self

    def _land_morph(
        self,
        *,
        hover: float,
        rows: int,
        velocity: float,
        spindown: float,
        sequential: bool,
        color: Any,
    ) -> ShowBuilder:
        """The swarm re-forms in the air into its home grid - a point above
        every landing spot, in altitude rows - with every drone moving at
        once along a straight line, then lands row by row.

        Drones are assigned to home points minimising the sum of squared
        distances. With such an assignment synchronised straight moves never
        bring two drones closer than the smaller of the start and end
        spacings divided by sqrt(2) (Turpin et al., "CAPT", 2014). The home
        grid is built with that spacing, and a formation that is denser first
        breathes out: it is scaled up about its base, which only increases
        distances.
        """
        d = self.limits.min_distance
        need = float(np.sqrt(2.0) * d * 1.02)
        spots = self.home.copy()
        groups, heights, gap, air = self._home_grid(hover, need, rows)

        t0 = self.t
        self.cues.append(Cue(t0, tr("Landing")))
        self._anchor_colors()
        label = tr("return")
        # breathe out: the formation and the drones waiting above the pad (not
        # in the formation) each scale up about their own base until their
        # spacing allows a safe synchronised morph
        waiting = self._waiting_above_pad()
        wide = self.positions.copy()
        for group in (np.flatnonzero(~waiting), np.flatnonzero(waiting)):
            wide[group] = _breathe_out(self.positions[group], need)
        start = float(np.min(KDTree(self.positions).query(self.positions, k=2)[0][:, 1]))
        if synchronized_clearance(self.positions, wide)[0] < min(d, start) - 1e-3:
            # the groups would grow into each other: scale everything together
            wide = _breathe_out(self.positions, need)
        if not np.allclose(wide, self.positions):
            self._move_to(wide, stagger=False, label=label)
        mapping = match_points(self.positions, air)
        order = np.zeros(self.n, dtype=int)
        for slot, drone in enumerate(mapping):
            order[drone] = slot  # type: ignore[index]
        targets = air[order]
        clearance, _ = synchronized_clearance(self.positions, targets)
        self._move_to(targets, stagger=bool(clearance < d - 1e-3), label=label)
        self.log.append(
            tr(
                "return: the swarm re-forms into its home grid in the air ({count} rows)"
                " and keeps {clearance:.2f} m",
                count=len(heights),
                clearance=clearance,
            )
        )
        return self._land_rows(
            t0,
            spots[order],
            groups[order],
            heights,
            gap,
            velocity=velocity,
            spindown=spindown,
            sequential=sequential,
            color=color,
        )

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def build(self, *, light_tolerance: float = 2.0) -> Show:
        drones = [
            Drone(name=name, trajectory=traj, lights=lights.simplified(light_tolerance))
            for name, traj, lights in zip(self.names, self.trajectories, self.lights)
        ]
        segments = dict(self.segments)
        if "show" in segments and segments["show"][1] <= segments["show"][0]:
            del segments["show"]
        return Show(
            drones=drones,
            title=self.title,
            limits=self.limits,
            cues=sorted(self.cues, key=lambda c: c.time),
            segments=segments,
            audio=self.audio,
            location=self.location,
        )


def _breathe_out(points: np.ndarray, spacing: float) -> np.ndarray:
    """Scales ``points`` up about the centre of their base (their lowest
    altitude) until their closest pair is ``spacing`` apart; uniform scaling
    only increases distances and never lowers the base."""
    if len(points) < 2:
        return points.copy()
    closest = float(np.min(KDTree(points).query(points, k=2)[0][:, 1]))
    if closest >= spacing:
        return points.copy()
    centre = np.array([*points[:, :2].mean(axis=0), float(points[:, 2].min())])
    return centre + (points - centre) * (spacing / max(closest, 1e-6))


class _KeepColors(Effect):
    """Keeps the given colours unchanged."""

    def __init__(self, colors: np.ndarray):
        super().__init__()
        self._colors = np.asarray(colors, dtype=float)
        self.static = True

    def colors(self, t, positions, base):
        return self._colors


def effect_or_default(spec: Any, colors: np.ndarray | None) -> Effect:
    default: Effect = FormationColors() if colors is not None else Solid("white")
    return make_effect(spec, default=default)
