"""Storyboard: turns the list of entries into an animation.

Nothing is computed while the storyboard is edited; everything happens when
"Recalculate" is pressed.
"""

import numpy as np

from . import scene as sc
from .core import engine
from .i18n import tr

DEFAULT_ALTITUDE = 6.0
DEFAULT_CLIMB = 1.2


class _Override(engine.effects.Effect):
    """Paints some drones with a fixed colour on top of another effect."""

    def __init__(self, base, mask: np.ndarray, color: np.ndarray):
        super().__init__()
        self.base, self.mask, self.color = base, mask, color
        self.static = base.static

    def colors(self, t, positions, base):
        out = np.array(self.base(t, positions, base), dtype=float)
        out[self.mask] = self.color
        return out


def name_mask(drones, names: set[str]) -> np.ndarray:
    return np.array([o.name in names for o in drones], dtype=bool)


def group_indices(settings, drones, group_name: str) -> np.ndarray | None:
    if not group_name:
        return None
    group = settings.groups.get(group_name)
    if group is None:
        raise ValueError(tr("drone group '{name}' not found", name=group_name))
    index = np.flatnonzero(name_mask(drones, group.names()))
    if len(index) == 0:
        raise ValueError(tr("drone group '{name}' is empty", name=group_name))
    return index


def _takeoff(builder, entry) -> None:
    altitude = entry.altitude if entry else DEFAULT_ALTITUDE
    climb = entry.climb_speed if entry else DEFAULT_CLIMB
    # smooth climb whose peak speed is the chosen climb speed; drones closer
    # than the minimum distance take off in waves
    builder.takeoff(
        altitude=altitude,
        layered=entry.layered if entry else True,
        rows=int(entry.rows) if entry else 0,
        climb_velocity=climb,
        color=(80, 80, 80),
    )


def _land(settings, builder, entry) -> None:
    builder.land(
        velocity=settings.landing_velocity,
        spindown=settings.spindown,
        target=entry.land_on if entry else "home",
        layered=entry.layered if entry else True,
        rows=int(entry.rows) if entry else 0,
        style=entry.return_style if entry else "dissolve",
        order=entry.petal_order if entry else "random",
        interval=entry.petal_interval if entry else 0.15,
    )


def recalculate(context):
    """Plans the whole show from the storyboard; returns ``(show, builder)``."""
    s = context.scene.murmura
    drones = sc.get_drones(context)
    if not drones:
        raise ValueError(tr("Create drones first (Murmura > Drones)"))
    if not len(s.storyboard):
        raise ValueError(tr("The storyboard is empty"))
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base
    n = len(drones)

    builder = engine.ShowBuilder(
        n,
        title=s.show_title or tr("Blender show"),
        limits=s.limits(),
        home=sc.home_positions(context, drones),
        names=[o.name for o in drones],
        speed_margin=s.tempo,
    )
    first_takeoff = next((e for e in s.storyboard if e.kind == "TAKEOFF"), None)
    airborne = False

    for entry in s.storyboard:
        t_start = builder.t
        if entry.kind == "TAKEOFF":
            if airborne:
                continue
            if entry.use_start:
                builder.wait_until(entry.start)
            t_start = builder.t
            _takeoff(builder, entry)
            airborne = True

        elif entry.kind == "FORMATION":
            if not airborne:
                _takeoff(builder, first_takeoff)
                builder.log.append(
                    tr("Takeoff added automatically before '{name}'", name=entry.name)
                )
                airborne = True
                t_start = builder.t
            points, colors = sc.entry_points(context, entry, drones)
            group = group_indices(s, drones, entry.group)
            size = n if group is None else len(group)
            if len(points) == 0:
                raise ValueError(tr("'{name}': no points found", name=entry.name))
            if len(points) > size:
                chosen = engine.formations.even_subset(points, size)
                _, index = engine._compat.KDTree(points).query(chosen)
                points = points[index]
                colors = colors[index] if colors is not None else None
            elif len(points) < size:
                builder.log.append(
                    tr(
                        "'{name}': {count} points for {drones} drones - the others wait with lights off",
                        name=entry.name,
                        count=len(points),
                        drones=size,
                    )
                )
            keep = entry.effect == "keep"
            effect = None if keep else entry.make_effect()
            colors = (
                sc.entry_colors(context, entry, points, colors)
                if entry.effect == "object"
                else None
            )
            if effect is not None:
                for override in entry.overrides:
                    mask = name_mask(drones, override.names())
                    if mask.any():
                        effect = _Override(effect, mask, np.array(override.color) * 255.0)
            builder.scene(
                entry.name,
                points,
                hold=entry.hold,
                colors=colors,
                effect=effect,
                motion=entry.make_motion(),
                transition_duration=entry.transition or None,
                start=entry.start if entry.use_start else None,
                drones=group,
                keep_lights=keep,
            )
            t_start = builder.cues[-1].time

        elif entry.kind == "LAND":
            if not airborne:
                continue
            _land(s, builder, entry)
            airborne = False

        entry.frame_start = scene.frame_start + int(round(t_start * fps))
        entry.frame_end = scene.frame_start + int(round(builder.t * fps))

    if airborne:
        _land(s, builder, None)
        builder.log.append(tr("Landing added automatically at the end"))

    return builder.build(), builder
