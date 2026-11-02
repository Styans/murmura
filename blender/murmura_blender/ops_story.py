"""Storyboard, drone group and painting operators."""

import time

import bpy
import numpy as np
from bpy.props import EnumProperty

from . import scene as sc
from . import storyboard
from .core import engine
from .i18n import localize, tr
from .ops import _store_report

FORMATIONS_PARENT = "Murmura formations"


def _settings(context):
    return context.scene.murmura


def _insert_entry(settings, kind: str, name: str):
    """Adds an entry right after the active one and makes it active."""
    entry = settings.storyboard.add()
    entry.kind, entry.name = kind, name
    last = len(settings.storyboard) - 1
    target = min(settings.storyboard_index + 1, last) if last else 0
    if target != last:
        settings.storyboard.move(last, target)
    settings.storyboard_index = target
    return settings.storyboard[target]


def _selected_drones(context) -> list:
    drones = set(sc.get_drones(context))
    return [o for o in context.selected_objects if o in drones]


# ----------------------------------------------------------------------
# Storyboard
# ----------------------------------------------------------------------


class MURMURA_OT_add_takeoff(bpy.types.Operator):
    """Add a smooth, battery-friendly takeoff from the pad"""

    bl_idname = "murmura.add_takeoff"
    bl_label = "Add Takeoff"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _insert_entry(_settings(context), "TAKEOFF", tr("Takeoff"))
        return {"FINISHED"}


class MURMURA_OT_add_landing(bpy.types.Operator):
    """Add a return above the pad and a landing"""

    bl_idname = "murmura.add_landing"
    bl_label = "Add Return and Landing"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _insert_entry(_settings(context), "LAND", tr("Return and land"))
        return {"FINISHED"}


class MURMURA_OT_add_selection(bpy.types.Operator):
    """Add a formation from the selection: selected vertices (Edit Mode), one object, or several objects"""

    bl_idname = "murmura.add_selection"
    bl_label = "Add Formation from Selection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = _settings(context)
        drones = set(sc.get_drones(context))
        obj = context.active_object

        if obj is not None and obj.mode == "EDIT" and obj.type == "MESH":
            obj.update_from_editmode()
            picked = [v.index for v in obj.data.vertices if v.select]
            if not picked:
                self.report({"ERROR"}, tr("Select some vertices first"))
                return {"CANCELLED"}
            name = f"Murmura {len(obj.vertex_groups) + 1}"
            bpy.ops.object.mode_set(mode="OBJECT")
            obj.vertex_groups.new(name=name).add(picked, 1.0, "REPLACE")
            bpy.ops.object.mode_set(mode="EDIT")
            entry = _insert_entry(s, "FORMATION", f"{obj.name} · {len(picked)}")
            entry.source, entry.target, entry.vertex_group = "VERTEX_GROUP", obj, name
            self.report({"INFO"}, tr("Formation from {count} vertices", count=len(picked)))
            return {"FINISHED"}

        chosen = [
            o
            for o in context.selected_objects
            if o not in drones and not o.name.endswith(" marker")
        ]
        if not chosen:
            # nothing selected: the collection active in the Outliner
            coll = context.view_layer.active_layer_collection.collection
            if coll is context.scene.collection or coll.name == sc.DRONES_COLLECTION:
                self.report({"ERROR"}, tr("Select a mesh with the target points first"))
                return {"CANCELLED"}
            entry = _insert_entry(s, "FORMATION", coll.name)
            entry.source, entry.collection = "COLLECTION", coll
            self._report_points(context, entry, drones)
            return {"FINISHED"}
        if len(chosen) == 1:
            entry = _insert_entry(s, "FORMATION", chosen[0].name)
            entry.source, entry.target = "OBJECT", chosen[0]
            self._report_points(context, entry, drones)
            return {"FINISHED"}

        parent = sc.ensure_collection(FORMATIONS_PARENT)
        coll = sc.ensure_collection(f"{tr('Formation')} {len(parent.children) + 1}", parent)
        for o in chosen:
            if o.name not in coll.objects:
                coll.objects.link(o)
        entry = _insert_entry(s, "FORMATION", coll.name)
        entry.source, entry.collection = "COLLECTION", coll
        entry.target = obj if obj in chosen else chosen[0]
        self._report_points(context, entry, drones)
        return {"FINISHED"}

    def _report_points(self, context, entry, drones) -> None:
        try:
            points, _ = sc.entry_points(context, entry, drones)
        except ValueError as ex:
            self.report({"WARNING"}, str(ex))
            return
        count, available = len(points), len(drones)
        text = tr(
            "Formation '{name}': {points} points, {drones} drones",
            name=entry.name,
            points=count,
            drones=available,
        )
        if available and count > available:
            text += " - " + tr("an even subset of points will be used")
        elif count < available:
            text += " - " + tr("{count} drones will wait with lights off", count=available - count)
        self.report({"INFO"}, text)


class MURMURA_OT_storyboard_remove(bpy.types.Operator):
    """Remove the selected storyboard entry"""

    bl_idname = "murmura.storyboard_remove"
    bl_label = "Remove Storyboard Entry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = _settings(context)
        if 0 <= s.storyboard_index < len(s.storyboard):
            s.storyboard.remove(s.storyboard_index)
            s.storyboard_index = max(0, s.storyboard_index - 1)
        return {"FINISHED"}


class MURMURA_OT_storyboard_move(bpy.types.Operator):
    """Move the selected storyboard entry"""

    bl_idname = "murmura.storyboard_move"
    bl_label = "Move Storyboard Entry"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])

    def execute(self, context):
        s = _settings(context)
        i = s.storyboard_index
        j = i - 1 if self.direction == "UP" else i + 1
        if 0 <= i < len(s.storyboard) and 0 <= j < len(s.storyboard):
            s.storyboard.move(i, j)
            s.storyboard_index = j
        return {"FINISHED"}


class MURMURA_OT_storyboard_duplicate(bpy.types.Operator):
    """Duplicate the selected storyboard entry"""

    bl_idname = "murmura.storyboard_duplicate"
    bl_label = "Duplicate Storyboard Entry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = _settings(context)
        if not 0 <= s.storyboard_index < len(s.storyboard):
            return {"CANCELLED"}
        source = s.storyboard[s.storyboard_index]
        entry = _insert_entry(s, source.kind, source.name)
        for prop in source.bl_rna.properties:
            key = prop.identifier
            if key in {"rna_type", "overrides"} or prop.is_readonly:
                continue
            setattr(entry, key, getattr(source, key))
        for override in source.overrides:
            copy = entry.overrides.add()
            copy.members, copy.color = override.members, override.color
        return {"FINISHED"}


class MURMURA_OT_follow_auto(bpy.types.Operator):
    """Bind the drones to the vertices from the moment they arrive (recalculate to apply)"""

    bl_idname = "murmura.follow_auto"
    bl_label = "Bind at Arrival"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = _settings(context)
        if 0 <= s.storyboard_index < len(s.storyboard):
            s.storyboard[s.storyboard_index].follow_manual = False
        return {"FINISHED"}


class MURMURA_OT_storyboard_jump(bpy.types.Operator):
    """Jump to the start of the selected entry"""

    bl_idname = "murmura.storyboard_jump"
    bl_label = "Go to Entry"

    def execute(self, context):
        s = _settings(context)
        if 0 <= s.storyboard_index < len(s.storyboard):
            context.scene.frame_set(s.storyboard[s.storyboard_index].frame_start)
        return {"FINISHED"}


class MURMURA_OT_recalculate(bpy.types.Operator):
    """Plan takeoff, formations, lights, return and landing from the storyboard and write the animation"""

    bl_idname = "murmura.recalculate"
    bl_label = "Recalculate Show"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = _settings(context)
        scene = context.scene
        started = time.perf_counter()
        if context.window:
            context.window.cursor_set("WAIT")
        try:
            show, builder = storyboard.recalculate(context)
        except ValueError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        finally:
            if context.window:
                context.window.cursor_set("DEFAULT")
        drones = sc.get_drones(context)
        sc.bake_show(context, show, drones)
        fps = scene.render.fps / scene.render.fps_base
        scene.frame_end = scene.frame_start + int(np.ceil(show.end_time * fps))
        sc.set_markers(context, show.cues, frame_start=scene.frame_start)
        report = engine.validate_show(show)
        _store_report(
            s,
            report,
            tr("Built in {seconds:.1f} s", seconds=time.perf_counter() - started),
            builder.log,
        )
        self.report(
            {"INFO"} if report.passed else {"WARNING"},
            tr(
                "Show built: {drones} drones, {duration:.1f} s, safety {status}",
                drones=len(drones),
                duration=show.duration,
                status=tr("OK") if report.passed else tr("FAILED"),
            ),
        )
        return {"FINISHED"}


# ----------------------------------------------------------------------
# Drone groups
# ----------------------------------------------------------------------


class MURMURA_OT_group_add(bpy.types.Operator):
    """Create a drone group from the selected drones"""

    bl_idname = "murmura.group_add"
    bl_label = "New Group from Selection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = _settings(context)
        picked = _selected_drones(context)
        if not picked:
            self.report({"ERROR"}, tr("Select some drones first"))
            return {"CANCELLED"}
        group = s.groups.add()
        group.name = f"{tr('Group')} {len(s.groups)}"
        group.members = "\n".join(o.name for o in picked)
        s.group_index = len(s.groups) - 1
        self.report({"INFO"}, tr("Group with {count} drones", count=len(picked)))
        return {"FINISHED"}


class MURMURA_OT_group_remove(bpy.types.Operator):
    """Delete the selected drone group (the drones stay)"""

    bl_idname = "murmura.group_remove"
    bl_label = "Delete Group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = _settings(context)
        if 0 <= s.group_index < len(s.groups):
            s.groups.remove(s.group_index)
            s.group_index = max(0, s.group_index - 1)
        return {"FINISHED"}


class MURMURA_OT_group_assign(bpy.types.Operator):
    """Add the selected drones to the group, or remove them from it"""

    bl_idname = "murmura.group_assign"
    bl_label = "Assign to Group"
    bl_options = {"REGISTER", "UNDO"}

    action: EnumProperty(items=[("ADD", "Add", ""), ("REMOVE", "Remove", "")])

    def execute(self, context):
        s = _settings(context)
        if not 0 <= s.group_index < len(s.groups):
            return {"CANCELLED"}
        group = s.groups[s.group_index]
        names = group.names()
        picked = {o.name for o in _selected_drones(context)}
        names = names | picked if self.action == "ADD" else names - picked
        group.members = "\n".join(sorted(names, key=engine.utils.natural_key))
        return {"FINISHED"}


class MURMURA_OT_group_select(bpy.types.Operator):
    """Select the drones of the group"""

    bl_idname = "murmura.group_select"
    bl_label = "Select Group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = _settings(context)
        if not 0 <= s.group_index < len(s.groups):
            return {"CANCELLED"}
        return bpy.ops.murmura.select_drones(names="\n".join(s.groups[s.group_index].names()))


# ----------------------------------------------------------------------
# Painting
# ----------------------------------------------------------------------


def _entry_for_painting(context):
    s = _settings(context)
    frame = context.scene.frame_current
    for entry in s.storyboard:
        if (
            entry.kind == "FORMATION"
            and entry.frame_start <= frame <= entry.frame_end
            and entry.frame_end
        ):
            return entry
    if 0 <= s.storyboard_index < len(s.storyboard):
        entry = s.storyboard[s.storyboard_index]
        if entry.kind == "FORMATION":
            return entry
    return None


class MURMURA_OT_paint(bpy.types.Operator):
    """Paint the selected drones in the formation shown on the current frame (or the selected entry)"""

    bl_idname = "murmura.paint"
    bl_label = "Paint Selected Drones"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = _settings(context)
        picked = _selected_drones(context)
        entry = _entry_for_painting(context)
        if not picked:
            self.report({"ERROR"}, tr("Select some drones first"))
            return {"CANCELLED"}
        if entry is None:
            self.report({"ERROR"}, tr("Select a formation in the storyboard first"))
            return {"CANCELLED"}
        override = entry.overrides.add()
        override.members = "\n".join(o.name for o in picked)
        override.color = s.paint_color
        for obj in picked:  # instant preview until the next recalculation
            obj.color = (*s.paint_color, 1.0)
        self.report(
            {"INFO"},
            tr(
                "{count} drones painted in '{name}' - press Recalculate",
                count=len(picked),
                name=entry.name,
            ),
        )
        return {"FINISHED"}


class MURMURA_OT_paint_clear(bpy.types.Operator):
    """Remove the painting of the selected storyboard entry"""

    bl_idname = "murmura.paint_clear"
    bl_label = "Clear Painting"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        entry = _entry_for_painting(context)
        if entry is not None:
            entry.overrides.clear()
        return {"FINISHED"}


CLASSES = (
    MURMURA_OT_add_takeoff,
    MURMURA_OT_add_landing,
    MURMURA_OT_add_selection,
    MURMURA_OT_storyboard_remove,
    MURMURA_OT_storyboard_move,
    MURMURA_OT_storyboard_duplicate,
    MURMURA_OT_storyboard_jump,
    MURMURA_OT_follow_auto,
    MURMURA_OT_recalculate,
    MURMURA_OT_group_add,
    MURMURA_OT_group_remove,
    MURMURA_OT_group_assign,
    MURMURA_OT_group_select,
    MURMURA_OT_paint,
    MURMURA_OT_paint_clear,
)


def register():
    for cls in CLASSES:
        localize(cls)
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
