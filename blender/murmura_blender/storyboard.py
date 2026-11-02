"""Storyboard: turns the list of entries into an animation.

Nothing is computed while the storyboard is edited; everything happens when
"Recalculate" is pressed.
"""

import copy

import numpy as np

from . import scene as sc
from .core import engine
from .i18n import tr

DEFAULT_ALTITUDE = 6.0
START_MARK = "\u25b6 "  # binding start marker
END_MARK = "\u25a0 "  # binding end marker
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


def _write_follow(entry, start: int, end: int) -> None:
    """Stores computed binding frames without marking them as typed by the user."""
    cls = type(entry)
    cls._writing = True
    try:
        entry.follow_start, entry.follow_end = start, end
    finally:
        cls._writing = False


def _follow_markers(scene, entry):
    names = entry.follow_markers.split("\n") if entry.follow_markers else []
    found = [scene.timeline_markers.get(n) for n in names] if len(names) == 2 else [None, None]
    return found


def read_follow_markers(scene, entry) -> None:
    """Frames of the binding markers the user dragged on the timeline become
    the binding range."""
    start, end = _follow_markers(scene, entry)
    if start is None or end is None:
        return
    if (start.frame, end.frame) != (entry.follow_start, entry.follow_end):
        _write_follow(entry, start.frame, max(end.frame, start.frame + 1))
        entry.follow_manual = True


def write_follow_markers(scene, entry) -> None:
    for marker in _follow_markers(scene, entry):
        if marker is not None:
            scene.timeline_markers.remove(marker)
    if not entry.follow:
        entry.follow_markers = ""
        return
    start = scene.timeline_markers.new(START_MARK + entry.name, frame=entry.follow_start)
    end = scene.timeline_markers.new(END_MARK + entry.name, frame=entry.follow_end)
    entry.follow_markers = start.name + "\n" + end.name


def _formation_points(context, entry, drones, size, frame=None):
    """Points of an entry (at ``frame`` if given) reduced to at most ``size``;
    returns points, colours and the indices of the points used."""
    if frame is not None:
        context.scene.frame_set(frame)
    points, colors = sc.entry_points(context, entry, drones)
    index = np.arange(len(points))
    if len(points) > size:
        chosen = engine.formations.even_subset(points, size)
        _, index = engine._compat.KDTree(points).query(chosen)
        index = np.asarray(index)
    return points[index], (colors[index] if colors is not None else None), index


def _follow_track(context, entry, drones, index, start: int, end: int, count: int):
    """Positions of the used points on every frame of the binding range."""
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base
    frames = []
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        points, _ = sc.entry_points(context, entry, drones)
        if len(points) != count:
            raise ValueError(
                tr(
                    "'{name}': the number of vertices changes during the binding"
                    " ({before} -> {after}); drones can only follow a mesh with fixed vertices",
                    name=entry.name,
                    before=count,
                    after=len(points),
                )
            )
        frames.append(points[index])
    times = (np.arange(start, end + 1) - start) / fps
    return times, np.array(frames)


def _last_keyframe() -> float:
    """The last keyframe of any animation in the file (0 without any)."""
    import bpy

    ends = [action.frame_range[1] for action in bpy.data.actions]
    return max(ends, default=0.0)


def _return_track(context, follow, drones, builder, interval: float):
    """Positions of the bound points after the binding ends, sampled while
    the drones may still be in the figure (5 times a second, until the model
    has been still for 3 s after its last keyframe)."""
    entry, index, count, end_frame = follow
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base
    step = max(1, int(round(fps / 5)))
    window = min(300.0, builder.n * interval * 2.0 + 60.0)
    last_key = _last_keyframe()
    times, frames, still = [], [], 0
    for frame in range(end_frame, end_frame + int(window * fps) + 1, step):
        scene.frame_set(frame)
        points, _ = sc.entry_points(context, entry, drones)
        if len(points) != count:
            break
        points = points[index]
        if frames and np.allclose(points, frames[-1], atol=1e-4):
            still += 1
            if still * step >= 3 * fps and frame > last_key:
                break
        else:
            still = 0
        times.append((frame - end_frame) / fps)
        frames.append(points)
    if len(times) < 2:
        return None
    return np.array(times), np.array(frames)


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


def _land(settings, builder, entry, follow=None) -> None:
    builder.land(
        velocity=settings.landing_velocity,
        spindown=settings.spindown,
        target=entry.land_on if entry else "home",
        layered=entry.layered if entry else True,
        rows=int(entry.rows) if entry else 0,
        style=entry.return_style if entry else "dissolve",
        order=entry.petal_order if entry else "random",
        interval=entry.petal_interval if entry else 0.15,
        follow=follow,
    )


def recalculate(context):
    """Plans the whole show from the storyboard; returns ``(show, builder)``.

    Formations that follow an animated model are sampled frame by frame, so
    the current frame is restored afterwards, and their binding range is
    written to the timeline as a pair of markers.
    """
    scene = context.scene
    frame = scene.frame_current
    try:
        result = _recalculate(context)
    finally:
        scene.frame_set(frame)
    for entry in scene.murmura.storyboard:
        if entry.kind == "FORMATION":
            write_follow_markers(scene, entry)
    return result


def _recalculate(context):
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
    bound = None  # the last formation if its drones stay bound to the model

    def landing(entry):
        style = entry.return_style if entry else "dissolve"
        follow = None
        if bound is not None and style == "dissolve":
            interval = entry.petal_interval if entry else 0.15
            follow = _return_track(context, bound, drones, builder, interval)
        _land(s, builder, entry, follow)

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
            group = group_indices(s, drones, entry.group)
            size = n if group is None else len(group)
            frame_of = lambda t: scene.frame_start + int(np.ceil(t * fps - 1e-6))  # noqa: E731
            track = track_start = None
            if entry.follow:
                read_follow_markers(scene, entry)
                if entry.follow_manual:
                    f0 = entry.follow_start
                else:
                    # bind when the drones arrive; where they fly depends on
                    # where the vertices are then, so find it in a few trials
                    f0 = frame_of(builder.t)
                    for _ in range(4):
                        pts, _, _ = _formation_points(context, entry, drones, size, f0)
                        trial = copy.deepcopy(builder)
                        if entry.use_start:
                            trial.wait_until(entry.start)
                        trial.transition_to(
                            pts, duration=entry.transition or None, drones=group, name=entry.name
                        )
                        arrive = frame_of(trial.t)
                        if arrive <= f0:
                            break
                        f0 = arrive
                    _write_follow(entry, f0, f0 + max(1, int(round(entry.hold * fps))))
                f1 = max(entry.follow_end, f0 + 1)
                points, colors, index = _formation_points(context, entry, drones, size, f0)
                count = len(sc.entry_points(context, entry, drones)[0])
                track = _follow_track(context, entry, drones, index, f0, f1, count)
                track_start = (f0 - scene.frame_start) / fps
                scene.frame_set(f0)
                bound = (entry, index, count, f1) if entry.follow_until_leaving else None
            else:
                points, colors, index = _formation_points(context, entry, drones, size)
                bound = None
            if len(points) == 0:
                raise ValueError(tr("'{name}': no points found", name=entry.name))
            if len(points) < size:
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
                track=track,
                track_start=track_start,
            )
            t_start = builder.cues[-1].time

        elif entry.kind == "LAND":
            if not airborne:
                continue
            landing(entry)
            airborne = False
            bound = None

        entry.frame_start = scene.frame_start + int(round(t_start * fps))
        entry.frame_end = scene.frame_start + int(round(builder.t * fps))

    if airborne:
        landing(None)
        builder.log.append(tr("Landing added automatically at the end"))

    return builder.build(), builder
