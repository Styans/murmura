"""High-level show composition: takeoff, scenes with transitions, landing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .colors import parse_color
from .effects import Effect, FormationColors, Solid, make_effect
from .i18n import plan_label
from .i18n import t as tr
from .lights import LightProgram
from .model import Audio, Cue, Drone, SafetyLimits, Show, ShowLocation
from .planning import (
    match_points,
    min_transition_durations,
    plan_landing,
    plan_takeoff,
)
from .planning.transition import plan_safe_moves, synchronised_plan
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
    ) -> ShowBuilder:
        """Vertical takeoff from the home positions.

        With ``layered`` takeoff, drones closer than the minimum distance to
        each other are assigned to different altitude layers.
        """
        groups = (
            np.asarray(plan_takeoff(self.home, min_distance=self.limits.min_distance))
            if layered
            else np.zeros(self.n, dtype=int)
        )
        spacing = layer_spacing if layer_spacing is not None else self.limits.min_distance
        targets = self.home.copy()
        targets[:, 2] = self.home[:, 2] + altitude + groups * spacing
        self.takeoff_altitudes = targets[:, 2] - self.home[:, 2]

        t0 = self.t
        self.cues.append(Cue(t0, tr("Takeoff")))
        self._set_colors(t0, np.array(parse_color(color), dtype=float), fade=False)
        self._move_to(targets, duration=duration, stagger=False, label=tr("takeoff"))
        self.segments["takeoff"] = (t0, self.t)
        if groups.max() > 0:
            self.log.append(tr("takeoff uses {count} altitude layers", count=int(groups.max()) + 1))
        return self

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
        profile = profile or self.profile
        targets = np.asarray(targets, dtype=float)

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
            return 0.0

        use_stagger = self.stagger if stagger is None else stagger
        if use_stagger:
            plan, separation = plan_safe_moves(
                self.positions,
                targets,
                min_distance=self.limits.min_distance,
                duration_fn=duration_fn,
                profile=profile,
                minimum_window=window,
            )
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
        else:
            plan = synchronised_plan(self.positions, targets, window, profile)

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
                traj.smooth_to(end, goal, profile=profile)
            traj.hold_until(t0 + total)
        self.positions = targets.copy()
        self.t = t0 + total
        return total

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
        target: str = "nearest",
        color: Any = (80, 80, 80),
        layered: bool = True,
        staging_spread: float | None = 2.0,
    ) -> ShowBuilder:
        """Returns every drone above a landing spot and lands the swarm.

        ``target="nearest"`` assigns landing spots (the home grid) optimally,
        ``target="home"`` sends every drone back to its own takeoff spot.

        With ``staging_spread`` the swarm first forms a horizontal copy of the
        landing grid enlarged by that factor at the mean altitude of the
        current formation, then contracts and descends uniformly onto the
        landing grid. The second step is an affine blend of two similar grids,
        so it can never bring drones closer than the grid spacing.
        """
        spots = self.home.copy()
        hover = altitude
        if hover is None:
            hover = (
                float(np.min(self.takeoff_altitudes)) if self.takeoff_altitudes is not None else 6.0
            )
        groups = (
            np.asarray(plan_takeoff(spots, min_distance=self.limits.min_distance))
            if layered
            else np.zeros(self.n, dtype=int)
        )
        lift = hover + groups * self.limits.min_distance

        if staging_spread:
            centre = spots.mean(axis=0)
            slots = centre + (spots - centre) * staging_spread
            slots[:, 2] = max(
                float(np.mean(self.positions[:, 2])),
                float(np.max(spots[:, 2] + lift)) + self.limits.min_distance,
            )
            slots[:, 2] += groups * self.limits.min_distance
        else:
            slots = spots.copy()
            slots[:, 2] = spots[:, 2] + lift

        if target == "nearest":
            mapping = match_points(self.positions, slots)
            order = np.zeros(self.n, dtype=int)
            for slot, drone in enumerate(mapping):
                order[drone] = slot  # type: ignore[index]
        elif target == "home":
            order = np.arange(self.n)
        else:
            raise ValueError("landing target must be 'nearest' or 'home'")
        spots, slots, lift = spots[order], slots[order], lift[order]
        above = spots.copy()
        above[:, 2] = spots[:, 2] + lift

        t0 = self.t
        self.cues.append(Cue(t0, tr("Landing")))
        self._anchor_colors()
        self._move_to(slots, label=tr("return"))
        if staging_spread:
            self._move_to(above, label=tr("approach"), stagger=False)
        self._set_colors(self.t, np.array(parse_color(color), dtype=float), fade=True)

        # plan relative to each spot so that uneven ground is handled too
        relative = above.copy()
        relative[:, 2] = above[:, 2] - spots[:, 2]
        starts, durations = plan_landing(
            relative,
            min_distance=self.limits.min_distance,
            velocity=min(velocity, self.limits.max_velocity_z * self.speed_margin),
            target_altitude=0.0,
            spindown_time=spindown,
            profile="smooth",
        )
        t1 = self.t
        end = t1
        for i, traj in enumerate(self.trajectories):
            touch = t1 + starts[i] + durations[i]
            traj.hold_until(t1 + starts[i])
            traj.smooth_to(touch, spots[i])
            self.lights[i].add(touch, (0, 0, 0), False)
            end = max(end, touch)
        self.positions = spots
        self.t = end
        self.segments["landing"] = (t0, end)
        return self

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
