"""Operators."""

import tempfile
import time
from pathlib import Path

import bpy
import numpy as np
from bpy.props import BoolProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import scene as sc
from .core import engine
from .i18n import localize, tr
from .props import SHAPES


def _settings(context):
    return context.scene.murmura


def _drone_count_check(self, context) -> list:
    drones = sc.get_drones(context)
    if not drones:
        self.report({"ERROR"}, tr("Create drones first (Murmura > Drones)"))
    return drones


# ----------------------------------------------------------------------
# Drones
# ----------------------------------------------------------------------


class MURMURA_OT_create_drones(bpy.types.Operator):
    """Create drones on a takeoff grid in the 'Drones' collection"""

    bl_idname = "murmura.create_drones"
    bl_label = "Create Drones"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = _settings(context)
        sc.remove_drones(context)
        home = engine.formations.grid(
            s.drone_count, spacing=s.grid_spacing, columns=s.grid_columns or None
        )
        sc.create_drones(context, home / sc.unit_scale(context), size=s.drone_size)
        sc.led_material()
        space = getattr(context, "space_data", None)
        if space is not None and getattr(space, "type", "") == "VIEW_3D":
            space.shading.color_type = "OBJECT"
        self.report({"INFO"}, tr("Created {count} drones", count=s.drone_count))
        return {"FINISHED"}


class MURMURA_OT_select_drones(bpy.types.Operator):
    """Select all drones"""

    bl_idname = "murmura.select_drones"
    bl_label = "Select Drones"
    bl_options = {"REGISTER", "UNDO"}

    names: StringProperty(default="", options={"SKIP_SAVE"})

    def execute(self, context):
        wanted = set(filter(None, self.names.split("\n"))) if self.names else None
        for obj in context.view_layer.objects:
            obj.select_set(False)
        selected = 0
        for obj in sc.get_drones(context):
            if wanted is None or obj.name in wanted:
                obj.select_set(True)
                context.view_layer.objects.active = obj
                selected += 1
        self.report({"INFO"}, tr("Selected {count} drones", count=selected))
        return {"FINISHED"}


# ----------------------------------------------------------------------
# Formations
# ----------------------------------------------------------------------


class MURMURA_OT_add_formation(bpy.types.Operator):
    """Create a new mesh with one point per drone (then add it as a formation)"""

    bl_idname = "murmura.add_formation"
    bl_label = "Create Shape Mesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = _settings(context)
        n = len(sc.get_drones(context)) or s.drone_count
        center = [float(v) * sc.unit_scale(context) for v in s.center]
        spec: dict = {"shape": s.shape, "center": center}
        size = float(s.size) * sc.unit_scale(context)
        planar = {
            "circle",
            "heart",
            "star",
            "polygon",
            "spiral",
            "line",
            "rectangle",
            "disc",
            "text",
            "svg",
            "image",
        }
        if s.shape in planar:
            spec["plane"] = s.plane
        if s.shape in {"circle", "polygon", "star", "spiral", "disc", "sphere", "torus", "helix"}:
            spec["radius"] = size
        elif s.shape in {"heart", "cube", "svg", "image"}:
            spec["size"] = size
        elif s.shape == "line":
            spec["length"] = size
        elif s.shape == "rectangle":
            spec.update(width=size, height=size / 2)
        elif s.shape == "grid":
            spec = {
                "shape": "grid",
                "spacing": max(s.min_distance * 1.2, size / 5),
                "center": center,
            }
        elif s.shape == "text":
            spec.update(text=s.text or "?", height=size)
        if s.shape in {"svg", "image"}:
            path = bpy.path.abspath(s.filepath)
            if not path or not Path(path).is_file():
                self.report({"ERROR"}, tr("Choose an SVG or image file first"))
                return {"CANCELLED"}
            spec["file"] = path
        try:
            points, colors = engine.formations.make_formation(spec, n)
        except (ValueError, OSError, RuntimeError) as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        if s.auto_scale:
            spacing = engine.formations.min_spacing(points)
            if spacing < s.min_distance * 1.15:
                points = engine.formations.scale_to_spacing(points, s.min_distance * 1.15)
                self.report(
                    {"INFO"},
                    tr(
                        "Formation enlarged to keep {spacing:.2f} m spacing",
                        spacing=s.min_distance * 1.15,
                    ),
                )
        floor = s.min_nav_altitude + 1.0
        if points[:, 2].min() < floor:
            points[:, 2] += floor - points[:, 2].min()
        name = s.text if s.shape == "text" else tr({i[0]: i[1] for i in SHAPES}[s.shape])
        obj = sc.create_formation_object(name, points / sc.unit_scale(context), colors)
        for other in context.view_layer.objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


# ----------------------------------------------------------------------
# Storyboard
# ----------------------------------------------------------------------


def _store_report(settings, report, headline: str, notes: list[str] | None = None) -> None:
    lines: list[tuple[str, bool]] = [(headline, True)]
    for note in notes or []:
        lines.append((note, not engine.i18n.is_warning(note)))
    lines.extend(report.summary_rows()[1:])
    settings.set_report(report.title, lines)
    if report.violations:
        first = min(report.violations, key=lambda v: v.time)
        settings.first_violation = first.time
        names = {v.drone for v in report.violations if abs(v.time - first.time) < 1e-6}
        names |= {v.other for v in report.violations if v.other and abs(v.time - first.time) < 1e-6}
        settings.violation_drones = "\n".join(sorted(names))
    else:
        settings.first_violation = -1.0
        settings.violation_drones = ""


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------


class MURMURA_OT_validate(bpy.types.Operator):
    """Sample the drone animation and check it against the safety limits"""

    bl_idname = "murmura.validate"
    bl_label = "Validate Show"

    def execute(self, context):
        s = _settings(context)
        if not _drone_count_check(self, context):
            return {"CANCELLED"}
        started = time.perf_counter()
        try:
            show = sc.show_from_scene(context, s)
        except ValueError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        report = engine.validate_show(show, dt=1.0 / max(1.0, s.sample_fps or 8.0))
        _store_report(
            s, report, tr("Validated in {seconds:.1f} s", seconds=time.perf_counter() - started)
        )
        self.report(
            {"INFO"} if report.passed else {"WARNING"},
            tr("Safety check passed") if report.passed else tr("Safety check FAILED"),
        )
        return {"FINISHED"}


class MURMURA_OT_goto_violation(bpy.types.Operator):
    """Jump to the first safety violation and select the drones involved"""

    bl_idname = "murmura.goto_violation"
    bl_label = "Go to First Problem"

    @classmethod
    def poll(cls, context):
        return context.scene.murmura.first_violation >= 0

    def execute(self, context):
        s = _settings(context)
        scene = context.scene
        fps = scene.render.fps / scene.render.fps_base
        scene.frame_set(scene.frame_start + int(round(s.first_violation * fps)))
        bpy.ops.murmura.select_drones(names=s.violation_drones)
        return {"FINISHED"}


# ----------------------------------------------------------------------
# Import / export
# ----------------------------------------------------------------------


class MURMURA_OT_export_skyc(bpy.types.Operator, ExportHelper):
    """Export the drone animation as a compiled .skyc show"""

    bl_idname = "murmura.export_skyc"
    bl_label = "Export .skyc"
    filename_ext = ".skyc"
    filter_glob: StringProperty(default="*.skyc", options={"HIDDEN"})

    validate: BoolProperty(name="Validate", default=True)
    preview: BoolProperty(
        name="Open in viewer", description="Send the show to a running show viewer", default=False
    )

    def execute(self, context):
        s = _settings(context)
        if not _drone_count_check(self, context):
            return {"CANCELLED"}
        started = time.perf_counter()
        try:
            show = sc.show_from_scene(context, s)
        except ValueError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        engine.write_skyc(show, self.filepath)
        message = tr(
            "Exported {drones} drones, {duration:.1f} s to {file}",
            drones=show.num_drones,
            duration=show.duration,
            file=Path(self.filepath).name,
        )
        if self.validate:
            report = engine.validate_show(show)
            _store_report(
                s, report, tr("Exported in {seconds:.1f} s", seconds=time.perf_counter() - started)
            )
            message += tr(" - safety OK") if report.passed else tr(" - safety FAILED")
        if self.preview:
            _send_to_viewer(self, self.filepath)
        self.report({"INFO"}, message)
        return {"FINISHED"}


class MURMURA_OT_export_csv(bpy.types.Operator, ExportHelper):
    """Export the drone animation as CSV files (one per drone, zipped)"""

    bl_idname = "murmura.export_csv"
    bl_label = "Export CSV"
    filename_ext = ".zip"
    filter_glob: StringProperty(default="*.zip", options={"HIDDEN"})
    fps: FloatProperty(name="Rows per second", default=4.0, min=0.5)

    def execute(self, context):
        s = _settings(context)
        if not _drone_count_check(self, context):
            return {"CANCELLED"}
        show = sc.show_from_scene(context, s)
        Path(self.filepath).write_bytes(engine.csvio.write_csv_zip(show, fps=self.fps))
        self.report({"INFO"}, tr("Exported CSV for {drones} drones", drones=show.num_drones))
        return {"FINISHED"}


class MURMURA_OT_import_skyc(bpy.types.Operator, ImportHelper):
    """Import a .skyc show: drones, trajectories, lights and cues"""

    bl_idname = "murmura.import_skyc"
    bl_label = "Import .skyc"
    filename_ext = ".skyc"
    filter_glob: StringProperty(default="*.skyc", options={"HIDDEN"})

    def execute(self, context):
        try:
            show = engine.read_skyc(self.filepath)
        except (ValueError, OSError) as ex:
            self.report({"ERROR"}, tr("Could not read the show: {error}", error=ex))
            return {"CANCELLED"}
        scene = context.scene
        scale = sc.unit_scale(context)
        sc.remove_drones(context)
        homes = np.array([d.home_position for d in show.drones]) / scale
        drones = sc.create_drones(context, homes, [d.name for d in show.drones])
        sc.led_material()
        sc.bake_show(context, show, drones)
        fps = scene.render.fps / scene.render.fps_base
        scene.frame_end = scene.frame_start + int(np.ceil(show.end_time * fps))
        sc.set_markers(context, show.cues, frame_start=scene.frame_start)
        s = _settings(context)
        s.show_title = show.title
        s.min_distance = show.limits.min_distance
        s.max_velocity_xy = show.limits.max_velocity_xy
        s.max_velocity_z = show.limits.max_velocity_z
        s.max_acceleration = min(show.limits.max_acceleration_xy, show.limits.max_acceleration_z)
        s.max_altitude = show.limits.max_altitude
        self.report(
            {"INFO"},
            tr(
                "Imported {drones} drones, {duration:.1f} s",
                drones=show.num_drones,
                duration=show.duration,
            ),
        )
        return {"FINISHED"}


def _send_to_viewer(operator, path: str) -> bool:
    try:
        url = engine.viewer.send_to_viewer(Path(path).read_bytes(), title=Path(path).name)
    except (RuntimeError, OSError) as ex:
        operator.report({"WARNING"}, tr("Preview failed: {error}", error=ex))
        return False
    operator.report({"INFO"}, tr("Show sent to the viewer at {url}", url=url))
    return True


class MURMURA_OT_preview(bpy.types.Operator):
    """Export to a temporary file and open it in a running show viewer"""

    bl_idname = "murmura.preview"
    bl_label = "Open in Viewer"

    def execute(self, context):
        s = _settings(context)
        if not _drone_count_check(self, context):
            return {"CANCELLED"}
        show = sc.show_from_scene(context, s)
        path = Path(tempfile.gettempdir()) / "murmura-preview.skyc"
        engine.write_skyc(show, path)
        return {"FINISHED"} if _send_to_viewer(self, str(path)) else {"CANCELLED"}


class MURMURA_OT_clear_animation(bpy.types.Operator):
    """Remove the baked animation from all drones"""

    bl_idname = "murmura.clear_animation"
    bl_label = "Clear Drone Animation"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        drones = sc.get_drones(context)
        home = sc.home_positions(context, drones) / sc.unit_scale(context) if drones else []
        for obj, pos in zip(drones, home):
            obj.animation_data_clear()
            obj.location = tuple(pos)
            obj.color = (1.0, 1.0, 1.0, 1.0)
        context.scene.frame_set(context.scene.frame_start)
        return {"FINISHED"}


CLASSES = (
    MURMURA_OT_create_drones,
    MURMURA_OT_select_drones,
    MURMURA_OT_add_formation,
    MURMURA_OT_validate,
    MURMURA_OT_goto_violation,
    MURMURA_OT_export_skyc,
    MURMURA_OT_export_csv,
    MURMURA_OT_import_skyc,
    MURMURA_OT_preview,
    MURMURA_OT_clear_animation,
)


def menu_export(self, context):
    self.layout.operator(MURMURA_OT_export_skyc.bl_idname, text=tr("Drone show (.skyc)"))


def menu_import(self, context):
    self.layout.operator(MURMURA_OT_import_skyc.bl_idname, text=tr("Drone show (.skyc)"))


def register():
    for cls in CLASSES:
        localize(cls)
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
