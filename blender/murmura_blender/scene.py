"""Scene helpers: drone objects, LED material, formation objects, keyframes."""

from __future__ import annotations

import bmesh
import bpy
import numpy as np

from .core import engine
from .i18n import tr

DRONES_COLLECTION = "Drones"
FORMATIONS_COLLECTION = "Formations"
LED_MATERIAL = "Murmura LED"
DRONE_MESH = "Murmura drone"
MARKER_MESH = "Murmura marker"
COLOR_ATTRIBUTE = "murmura_color"
MARKER_PREFIX = "◆ "
HOME_PROPERTY = "murmura_home"

# RNA enum values used with foreach_set
_INTERPOLATION = {"CONSTANT": 0, "LINEAR": 1, "BEZIER": 2}
_HANDLE_FREE = 0


# ----------------------------------------------------------------------
# Collections, meshes and materials
# ----------------------------------------------------------------------


def ensure_collection(
    name: str, parent: bpy.types.Collection | None = None
) -> bpy.types.Collection:
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    parent = parent or bpy.context.scene.collection
    if coll.name not in parent.children and coll != parent:
        try:
            parent.children.link(coll)
        except RuntimeError:
            pass
    return coll


def _icosphere_mesh(name: str, radius: float, subdivisions: int) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.get(name)
    if mesh is not None:
        return mesh
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=radius)
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = True
    return mesh


def led_material() -> bpy.types.Material:
    """A shared emissive material whose colour comes from the object colour,
    so that every drone can be lit individually by animating ``obj.color``."""
    mat = bpy.data.materials.get(LED_MATERIAL)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(LED_MATERIAL)
    if hasattr(mat, "use_nodes") and not mat.use_nodes:
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    info = nodes.new("ShaderNodeObjectInfo")
    info.location = (-400, 0)
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (-150, 0)
    emission.inputs["Strength"].default_value = 4.0
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (100, 0)
    links.new(info.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    mat.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    return mat


def drone_mesh() -> bpy.types.Mesh:
    mesh = _icosphere_mesh(DRONE_MESH, 0.25, 2)
    if not mesh.materials:
        mesh.materials.append(led_material())
    return mesh


def marker_mesh() -> bpy.types.Mesh:
    return _icosphere_mesh(MARKER_MESH, 0.18, 1)


# ----------------------------------------------------------------------
# Drones
# ----------------------------------------------------------------------


def get_drones(context) -> list[bpy.types.Object]:
    coll = bpy.data.collections.get(DRONES_COLLECTION)
    if coll is None:
        return []
    drones = [o for o in coll.all_objects if o.type in {"MESH", "EMPTY"}]
    return sorted(drones, key=lambda o: engine.utils.natural_key(o.name))


def create_drones(
    context, positions: np.ndarray, names: list[str] | None = None, size: float = 0.5
) -> list[bpy.types.Object]:
    """Creates (or reuses) drones named ``Drone 1..N`` at the given positions."""
    coll = ensure_collection(DRONES_COLLECTION)
    mesh = drone_mesh()
    names = names or [f"Drone {i + 1}" for i in range(len(positions))]
    drones = []
    for name, pos in zip(names, positions):
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            obj = bpy.data.objects.new(name, mesh)
        if coll not in obj.users_collection:
            coll.objects.link(obj)
        obj.location = tuple(float(v) for v in pos)
        obj.scale = (size / 0.5,) * 3
        obj.color = (1.0, 1.0, 1.0, 1.0)
        obj[HOME_PROPERTY] = [float(v) for v in pos]
        drones.append(obj)
    return drones


def home_positions(context, drones) -> np.ndarray:
    """Takeoff / landing spots (metres): stored on the drones when they were
    created, otherwise their positions on the first frame."""
    scale = unit_scale(context)
    stored = [obj.get(HOME_PROPERTY) for obj in drones]
    if all(s is not None and len(s) == 3 for s in stored):
        return np.array([list(s) for s in stored], dtype=float) * scale
    scene = context.scene
    current = (scene.frame_current, scene.frame_subframe)
    scene.frame_set(scene.frame_start)
    home = np.array([tuple(o.matrix_world.translation) for o in drones]) * scale
    scene.frame_set(current[0], subframe=current[1])
    return home


def remove_drones(context) -> int:
    count = 0
    for obj in get_drones(context):
        bpy.data.objects.remove(obj, do_unlink=True)
        count += 1
    return count


def unit_scale(context) -> float:
    return float(context.scene.unit_settings.scale_length or 1.0)


# ----------------------------------------------------------------------
# Formation objects
# ----------------------------------------------------------------------


def create_formation_object(
    name: str, points: np.ndarray, colors: np.ndarray | None = None
) -> bpy.types.Object:
    """A mesh made of loose vertices, displayed with a small sphere on every
    vertex. Optional per-point colours are stored in a colour attribute."""
    coll = ensure_collection(FORMATIONS_COLLECTION)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(map(float, p)) for p in points], [], [])
    if colors is not None:
        attr = mesh.color_attributes.new(COLOR_ATTRIBUTE, "FLOAT_COLOR", "POINT")
        rgba = np.column_stack([np.asarray(colors, dtype=float) / 255.0, np.ones(len(points))])
        attr.data.foreach_set("color_srgb", rgba.ravel())
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    marker = bpy.data.objects.new(f"{name} marker", marker_mesh())
    coll.objects.link(marker)
    marker.parent = obj
    marker.hide_render = True
    marker.hide_select = True
    obj.instance_type = "VERTS"
    obj.show_instancer_for_viewport = True
    obj.show_instancer_for_render = False
    return obj


def formation_points(context, obj: bpy.types.Object) -> tuple[np.ndarray, np.ndarray | None]:
    """World-space vertex positions (in metres) and colours of a mesh object."""
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        count = len(mesh.vertices)
        co = np.empty(count * 3)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        matrix = np.array(evaluated.matrix_world)
        world = co @ matrix[:3, :3].T + matrix[:3, 3]
        colors = attribute_colors(mesh)
    finally:
        evaluated.to_mesh_clear()
    return world * unit_scale(context), colors


def selected_points(context, obj: bpy.types.Object) -> tuple[np.ndarray, np.ndarray | None]:
    """Target points picked by the user, in metres.

    In Edit Mode these are the selected vertices of the mesh (all vertices if
    none is selected); in Object Mode all vertices of the evaluated mesh.
    """
    if obj.mode != "EDIT":
        return formation_points(context, obj)
    obj.update_from_editmode()
    mesh = obj.data
    count = len(mesh.vertices)
    co = np.empty(count * 3)
    mesh.vertices.foreach_get("co", co)
    sel = np.empty(count, dtype=bool)
    mesh.vertices.foreach_get("select", sel)
    if not sel.any():
        sel[:] = True
    matrix = np.array(obj.matrix_world)
    world = co.reshape(-1, 3)[sel] @ matrix[:3, :3].T + matrix[:3, 3]
    colors = attribute_colors(mesh)
    if colors is not None:
        colors = colors[sel]
    return world * unit_scale(context), colors


# ----------------------------------------------------------------------
# F-curves (works with layered actions of Blender 4.4+ and legacy actions)
# ----------------------------------------------------------------------


def _fcurve_collection(obj: bpy.types.Object):
    ad = obj.animation_data or obj.animation_data_create()
    if ad.action is None:
        ad.action = bpy.data.actions.new(f"{obj.name} Action")
    action = ad.action
    if hasattr(action, "layers"):
        slot = getattr(ad, "action_slot", None)
        if slot is None:
            slot = action.slots.new(id_type="OBJECT", name=obj.name)
            ad.action_slot = slot
        from bpy_extras import anim_utils

        return anim_utils.action_ensure_channelbag_for_slot(action, slot).fcurves
    return action.fcurves


def reset_fcurves(obj: bpy.types.Object, data_path: str, count: int) -> list:
    fcurves = _fcurve_collection(obj)
    result = []
    for index in range(count):
        fc = fcurves.find(data_path, index=index)
        if fc is not None:
            fcurves.remove(fc)
        result.append(fcurves.new(data_path, index=index))
    return result


def _write_keys(fc, frames, values, left, right, interpolation) -> None:
    n = len(frames)
    points = fc.keyframe_points
    points.add(n)
    points.foreach_set("co", np.column_stack([frames, values]).astype(np.float32).ravel())
    points.foreach_set("handle_left", np.asarray(left, dtype=np.float32).ravel())
    points.foreach_set("handle_right", np.asarray(right, dtype=np.float32).ravel())
    points.foreach_set("handle_left_type", np.full(n, _HANDLE_FREE, dtype=np.int32))
    points.foreach_set("handle_right_type", np.full(n, _HANDLE_FREE, dtype=np.int32))
    points.foreach_set("interpolation", np.asarray(interpolation, dtype=np.int32))
    fc.update()


def _trajectory_keys(traj, *, fps: float, frame_start: float, scale: float):
    """Keyframes reproducing a trajectory: every segment becomes one F-curve
    segment whose handles sit at one and two thirds of the segment in time, so
    Blender evaluates exactly the same time-parametrised cubic curve."""
    pts = traj.points
    frames = np.array([frame_start + p.t * fps for p in pts])
    pos = np.array([p.pos for p in pts]) / scale
    n = len(pts)
    left = np.zeros((n, 3, 2))
    right = np.zeros((n, 3, 2))
    for k in range(n):
        left[k, :, 0] = frames[k] - (frames[k] - frames[k - 1]) / 3 if k else frames[k] - 1
        left[k, :, 1] = pos[k]
        right[k, :, 0] = frames[k] + (frames[k + 1] - frames[k]) / 3 if k + 1 < n else frames[k] + 1
        right[k, :, 1] = pos[k]
    for k in range(1, n):
        cps = engine.bezier.elevate_to_cubic(pts[k - 1].pos, pts[k].controls, pts[k].pos) / scale
        right[k - 1, :, 1] = cps[1]
        left[k, :, 1] = cps[2]
    return frames, pos, left, right, np.full(n, _INTERPOLATION["BEZIER"])


def _light_keys(program, *, fps: float, frame_start: float):
    frames: list[float] = []
    values: list[tuple[float, float, float]] = []
    interp: list[int] = []
    for kf in program.keyframes:
        frame = frame_start + kf.t * fps
        color = tuple(c / 255.0 for c in kf.color)
        if frames:
            if frame <= frames[-1] + 1e-4:
                # F-curves cannot hold two keys on one frame: switch a hair later
                interp[-1] = _INTERPOLATION["CONSTANT"]
                frame = frames[-1] + 0.01
            else:
                interp[-1] = _INTERPOLATION["LINEAR" if kf.fade else "CONSTANT"]
        frames.append(frame)
        values.append(color)
        interp.append(_INTERPOLATION["CONSTANT"])
    f = np.array(frames)
    v = np.array(values).reshape(-1, 3)
    handles = [np.column_stack([f, v[:, c]]) for c in range(3)]
    return f, v, handles, np.array(interp)


def bake_trajectory(obj, traj, *, fps: float, frame_start: float, scale: float = 1.0) -> None:
    """Replaces the ``location`` animation with a trajectory."""
    fcurves = reset_fcurves(obj, "location", 3)
    if not traj.points:
        return
    frames, pos, left, right, interp = _trajectory_keys(
        traj, fps=fps, frame_start=frame_start, scale=scale
    )
    for axis, fc in enumerate(fcurves):
        _write_keys(fc, frames, pos[:, axis], left[:, axis], right[:, axis], interp)
    obj.location = tuple(pos[0])


def bake_lights(obj, program, *, fps: float, frame_start: float) -> None:
    """Replaces the object colour animation with a light program."""
    fcurves = reset_fcurves(obj, "color", 3)
    if not program.keyframes:
        obj.color = (0.0, 0.0, 0.0, 1.0)
        return
    f, v, handles, interp = _light_keys(program, fps=fps, frame_start=frame_start)
    for channel, fc in enumerate(fcurves):
        _write_keys(fc, f, v[:, channel], handles[channel], handles[channel], interp)
    obj.color = (*v[0], 1.0)


def _fcurves(obj, data_path: str, count: int) -> list:
    fcurves = _fcurve_collection(obj)
    return [
        fcurves.find(data_path, index=i) or fcurves.new(data_path, index=i) for i in range(count)
    ]


def _merge_keys(fc, frames, values, left, right, interp) -> None:
    """Keeps the keys before ``frames[0]`` and replaces everything after it."""
    points = fc.keyframe_points
    n = len(points)
    co = np.empty(2 * n, dtype=np.float32)
    hl = np.empty(2 * n, dtype=np.float32)
    hr = np.empty(2 * n, dtype=np.float32)
    it = np.empty(n, dtype=np.int32)
    if n:
        points.foreach_get("co", co)
        points.foreach_get("handle_left", hl)
        points.foreach_get("handle_right", hr)
        points.foreach_get("interpolation", it)
    co, hl, hr = co.reshape(-1, 2), hl.reshape(-1, 2), hr.reshape(-1, 2)
    f0 = float(frames[0])
    keep = co[:, 0] < f0 - 1e-3
    left = np.array(left, dtype=float)
    same = np.flatnonzero(np.abs(co[:, 0] - f0) <= 1e-3)
    if len(same):
        left[0] = hl[same[0]]
    points.clear()
    _write_keys(
        fc,
        np.concatenate([co[keep, 0], frames]),
        np.concatenate([co[keep, 1], values]),
        np.concatenate([hl[keep], left]),
        np.concatenate([hr[keep], right]),
        np.concatenate([it[keep], interp]),
    )


def append_animation(obj, drone, *, fps: float, frame_start: float, scale: float) -> None:
    """Continues the drone animation with a trajectory and light program that
    start at the current point in time; later keys are replaced."""
    traj = drone.trajectory
    if traj.points:
        frames, pos, left, right, interp = _trajectory_keys(
            traj, fps=fps, frame_start=frame_start, scale=scale
        )
        for axis, fc in enumerate(_fcurves(obj, "location", 3)):
            _merge_keys(fc, frames, pos[:, axis], left[:, axis], right[:, axis], interp)
    if drone.lights.keyframes:
        f, v, handles, interp = _light_keys(drone.lights, fps=fps, frame_start=frame_start)
        for channel, fc in enumerate(_fcurves(obj, "color", 3)):
            _merge_keys(fc, f, v[:, channel], handles[channel], handles[channel], interp)


def bake_show(context, show, drones, *, frame_start: int | None = None) -> None:
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base
    start = scene.frame_start if frame_start is None else frame_start
    scale = unit_scale(context)
    wm = context.window_manager
    wm.progress_begin(0, len(drones))
    try:
        for i, (obj, drone) in enumerate(zip(drones, show.drones)):
            bake_trajectory(obj, drone.trajectory, fps=fps, frame_start=start, scale=scale)
            bake_lights(obj, drone.lights, fps=fps, frame_start=start)
            wm.progress_update(i)
    finally:
        wm.progress_end()


def set_markers(context, cues, *, frame_start: int) -> None:
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base
    for marker in list(scene.timeline_markers):
        if marker.name.startswith(MARKER_PREFIX):
            scene.timeline_markers.remove(marker)
    for cue in cues:
        scene.timeline_markers.new(
            MARKER_PREFIX + cue.name, frame=int(round(frame_start + cue.time * fps))
        )


# ----------------------------------------------------------------------
# Sampling the scene into a show
# ----------------------------------------------------------------------


def sample_drones(
    context, drones, *, fps: float | None = None, frame_range: tuple[int, int] | None = None
):
    """Samples world positions (metres) and object colours (0-255) of the
    drones; returns ``(times, positions[k, n, 3], colors[k, n, 3])``."""
    scene = context.scene
    scene_fps = scene.render.fps / scene.render.fps_base
    first, last = frame_range or (scene.frame_start, scene.frame_end)
    step = scene_fps / fps if fps else 1.0
    frames = np.arange(first, last + 1e-6, step)
    if frames[-1] < last - 1e-6:
        frames = np.append(frames, last)
    scale = unit_scale(context)
    positions = np.zeros((len(frames), len(drones), 3))
    colors = np.zeros((len(frames), len(drones), 3))
    current = (scene.frame_current, scene.frame_subframe)
    wm = context.window_manager
    wm.progress_begin(0, len(frames))
    try:
        for k, frame in enumerate(frames):
            whole = int(np.floor(frame))
            scene.frame_set(whole, subframe=float(frame - whole))
            for j, obj in enumerate(drones):
                positions[k, j] = obj.matrix_world.translation
                colors[k, j] = obj.color[:3]
            wm.progress_update(k)
    finally:
        scene.frame_set(current[0], subframe=current[1])
        wm.progress_end()
    times = (frames - first) / scene_fps
    return times, positions * scale, np.clip(colors * 255.0, 0, 255).round()


def show_from_scene(context, settings, *, fps: float | None = None):
    """Builds a :class:`murmura.Show` from the current drone animation."""
    drones = get_drones(context)
    if not drones:
        raise ValueError(tr("there are no drones in the 'Drones' collection"))
    scene = context.scene
    scene_fps = scene.render.fps / scene.render.fps_base
    times, positions, colors = sample_drones(
        context, drones, fps=fps or settings.sample_fps or None
    )
    light_step = 1
    if len(times) > 1 and settings.light_fps > 0:
        light_step = max(1, int(round(1.0 / settings.light_fps / (times[1] - times[0]))))
    show_drones = []
    for j, obj in enumerate(drones):
        traj = engine.Trajectory.from_samples(
            times, positions[:, j], tolerance=settings.fit_tolerance
        )
        idx = np.unique(np.append(np.arange(0, len(times), light_step), len(times) - 1))
        keys = [
            engine.LightKeyframe(float(times[k]), tuple(int(c) for c in colors[k, j]), True)
            for k in idx
        ]
        lights = engine.LightProgram(keys).simplified(2.0)
        show_drones.append(engine.Drone(name=obj.name, trajectory=traj, lights=lights))
    cues = []
    for marker in sorted(scene.timeline_markers, key=lambda m: m.frame):
        if scene.frame_start <= marker.frame <= scene.frame_end:
            name = (
                marker.name[len(MARKER_PREFIX) :]
                if marker.name.startswith(MARKER_PREFIX)
                else marker.name
            )
            cues.append(engine.model.Cue((marker.frame - scene.frame_start) / scene_fps, name))
    return engine.Show(
        drones=show_drones,
        title=settings.show_title or bpy.path.display_name(bpy.data.filepath) or tr("Blender show"),
        limits=settings.limits(),
        cues=cues,
    )


# ----------------------------------------------------------------------
# Colours of formations
# ----------------------------------------------------------------------

# colour attributes written by Murmura, Pointille / dronegen and Blender itself
COLOR_ATTRIBUTES = (COLOR_ATTRIBUTE, "drone_color", "Col", "Color")


def attribute_colors(mesh) -> np.ndarray | None:
    """Per-vertex colours (0-255, sRGB) from the first known colour attribute,
    or the active one."""
    attrs = mesh.color_attributes
    attr = next((attrs[n] for n in COLOR_ATTRIBUTES if attrs.get(n) is not None), None)
    if attr is None:
        attr = attrs.active_color
    if attr is None:
        return None
    count = len(mesh.vertices)
    rgba = np.empty(len(attr.data) * 4)
    attr.data.foreach_get("color_srgb", rgba)
    rgba = rgba.reshape(-1, 4)[:, :3]
    if attr.domain == "POINT" and len(rgba) == count:
        colors = rgba
    elif attr.domain == "CORNER" and len(rgba) == len(mesh.loops):
        vertex = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", vertex)
        colors = np.zeros((count, 3))
        hits = np.zeros(count)
        np.add.at(colors, vertex, rgba)
        np.add.at(hits, vertex, 1)
        colors /= np.maximum(hits, 1)[:, None]
    else:
        return None
    return np.clip(colors * 255.0, 0, 255).round()


def _to_srgb(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)


_IMAGE_CACHE: dict[str, np.ndarray] = {}


def _image_pixels(image) -> np.ndarray | None:
    key = f"{image.name}:{image.size[0]}x{image.size[1]}"
    if key not in _IMAGE_CACHE:
        w, h = image.size
        if not w or not h:
            return None
        pixels = np.empty(w * h * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        pixels = pixels.reshape(h, w, 4)[:, :, :3]
        _IMAGE_CACHE[key] = _to_srgb(pixels) if image.is_float else pixels
    return _IMAGE_CACHE[key]


def _base_color_source(material):
    """(image, default colour in sRGB) feeding the base colour of a material."""
    if material is None:
        return None, np.array([1.0, 1.0, 1.0])
    fallback = _to_srgb(np.array(material.diffuse_color[:3]))
    tree = material.node_tree
    if tree is None:
        return None, fallback
    for node in tree.nodes:
        socket = node.inputs.get("Base Color") or node.inputs.get("Color")
        if node.type in {"BSDF_PRINCIPLED", "BSDF_DIFFUSE", "EMISSION"} and socket is not None:
            if socket.is_linked:
                source = socket.links[0].from_node
                if source.type == "TEX_IMAGE" and source.image is not None:
                    return source.image, fallback
            return None, _to_srgb(np.array(socket.default_value[:3]))
    return None, fallback


def surface_colors(context, obj, points_m: np.ndarray) -> np.ndarray | None:
    """Colour of the surface of ``obj`` nearest to every point: its vertex
    colours, else the texture or base colour of its material."""
    if obj is None or obj.type != "MESH":
        return None
    from mathutils.bvhtree import BVHTree

    evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        if not mesh.polygons:
            return None
        mesh.calc_loop_triangles()
        co = np.empty(len(mesh.vertices) * 3)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        count = len(mesh.loop_triangles)
        tris = np.empty(count * 3, dtype=np.int32)
        loops = np.empty(count * 3, dtype=np.int32)
        mats = np.empty(count, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", tris)
        mesh.loop_triangles.foreach_get("loops", loops)
        mesh.loop_triangles.foreach_get("material_index", mats)
        tris, loops = tris.reshape(-1, 3), loops.reshape(-1, 3)
        bvh = BVHTree.FromPolygons(co.tolist(), tris.tolist())
        inverse = np.array(evaluated.matrix_world.inverted())
        local = (points_m / unit_scale(context)) @ inverse[:3, :3].T + inverse[:3, 3]
        vertex_colors = attribute_colors(mesh)
        uv = None
        if mesh.uv_layers.active is not None:
            uv = np.empty(len(mesh.loops) * 2)
            mesh.uv_layers.active.data.foreach_get("uv", uv)
            uv = uv.reshape(-1, 2)
        sources = [_base_color_source(slot.material) for slot in evaluated.material_slots] or [
            (None, np.array([1.0, 1.0, 1.0]))
        ]
        out = np.zeros((len(local), 3))
        for k, point in enumerate(local):
            hit, _, index, _ = bvh.find_nearest(point)
            if index is None:
                continue
            a, b, c = co[tris[index]]
            weights = _barycentric(np.array(hit), a, b, c)
            if vertex_colors is not None:
                out[k] = weights @ vertex_colors[tris[index]]
                continue
            image, base = sources[min(mats[index], len(sources) - 1)]
            pixels = _image_pixels(image) if image is not None and uv is not None else None
            if pixels is None:
                out[k] = base * 255.0
                continue
            u, v = (weights @ uv[loops[index]]) % 1.0
            h, w = pixels.shape[:2]
            out[k] = pixels[min(int(v * h), h - 1), min(int(u * w), w - 1)] * 255.0
        return np.clip(out, 0, 255).round()
    finally:
        evaluated.to_mesh_clear()


def _barycentric(p, a, b, c) -> np.ndarray:
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
    d20, d21 = v2 @ v0, v2 @ v1
    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-12:
        return np.array([1.0, 0.0, 0.0])
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    return np.clip(np.array([1.0 - v - w, v, w]), 0.0, 1.0)


def lift_dark(colors: np.ndarray, minimum: float) -> np.ndarray:
    """Brightens colours whose brightest channel is below ``minimum`` (0-1)
    so that dark parts of a figure still glow."""
    colors = np.asarray(colors, dtype=float).copy()
    floor = minimum * 255.0
    peak = colors.max(axis=1)
    black = peak < 1.0
    colors[black] = floor
    dim = ~black & (peak < floor)
    colors[dim] *= (floor / peak[dim])[:, None]
    return np.clip(colors, 0, 255).round()


# ----------------------------------------------------------------------
# Points of a storyboard entry
# ----------------------------------------------------------------------


def _object_points(context, obj) -> tuple[np.ndarray, np.ndarray | None]:
    if obj.type == "MESH" and len(obj.data.vertices):
        return formation_points(context, obj)
    return np.array([tuple(obj.matrix_world.translation)]) * unit_scale(context), None


def _group_points(context, obj, group_name: str) -> tuple[np.ndarray, np.ndarray | None]:
    group = obj.vertex_groups.get(group_name)
    if group is None:
        raise ValueError(
            tr("vertex group '{group}' not found on '{name}'", group=group_name, name=obj.name)
        )
    mesh = obj.data
    index = group.index
    members = [
        v.index for v in mesh.vertices if any(g.group == index and g.weight > 0 for g in v.groups)
    ]
    co = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    matrix = np.array(obj.matrix_world)
    world = co.reshape(-1, 3)[members] @ matrix[:3, :3].T + matrix[:3, 3]
    colors = attribute_colors(mesh)
    return world * unit_scale(context), (colors[members] if colors is not None else None)


def entry_points(context, entry, drones) -> tuple[np.ndarray, np.ndarray | None]:
    """Target points (metres) and their colours (0-255 or ``None``)."""
    skip = set(drones)
    if entry.source == "COLLECTION":
        if entry.collection is None:
            raise ValueError(tr("storyboard entry '{name}' has no formation", name=entry.name))
        parts = [
            _object_points(context, o)
            for o in entry.collection.all_objects
            if o not in skip and not o.name.endswith(" marker")
        ]
        if not parts:
            return np.zeros((0, 3)), None
        points = np.vstack([p for p, _ in parts])
        if all(c is not None for _, c in parts):
            return points, np.vstack([c for _, c in parts])
        return points, None
    obj = entry.target
    if obj is None:
        raise ValueError(tr("storyboard entry '{name}' has no formation", name=entry.name))
    if entry.source == "VERTEX_GROUP" and obj.type == "MESH":
        return _group_points(context, obj, entry.vertex_group)
    return _object_points(context, obj)


def entry_colors(
    context, entry, points: np.ndarray, colors: np.ndarray | None
) -> np.ndarray | None:
    """Colours for the "object colours" light mode."""
    if colors is None:
        source = entry.color_object
        if source is None and entry.target is not None:
            target = entry.target
            has_faces = target.type == "MESH" and len(target.data.polygons) > 0
            source = target if has_faces else target.parent
        colors = surface_colors(context, source, points)
    if colors is None:
        return None
    return lift_dark(colors, entry.min_brightness)
