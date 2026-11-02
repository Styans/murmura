"""Murmura for Blender: drone show choreography and .skyc export.

Three sidebar tabs in the 3D viewport, like Skybrush Studio:

* Murmura - create drones, turn the selected objects, vertices or collection
  into formations, order them on the storyboard and recalculate the show:
  takeoff, collision-aware transitions and landing are baked as keyframes
* Murmura LEDs - lights of the selected formation, painting drones
* Murmura Export - safety limits, validation, ``.skyc`` export and import

The interface is available in English and Russian (see the add-on
preferences).
"""

bl_info = {
    "name": "Murmura",
    "author": "Murmura contributors",
    "version": (0, 1, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Murmura",
    "description": "Drone show choreography with collision-aware transitions and .skyc export",
    "category": "Animation",
}

if "bpy" in locals():  # support "Reload Scripts"
    import importlib

    for _module in ("i18n", "prefs", "props", "scene", "storyboard", "ops", "ops_story", "ui"):
        if _module in locals():
            importlib.reload(locals()[_module])

import bpy  # noqa: E402,F401

from . import i18n, ops, ops_story, prefs, props, ui  # noqa: E402

_MODULES = (props, ops, ops_story, ui)


def register():
    prefs.register()
    i18n.apply_language()
    for module in _MODULES:
        module.register()


def unregister():
    for module in reversed(_MODULES):
        module.unregister()
    prefs.unregister()


def reload_language():
    """Re-registers the interface in the currently selected language."""
    for module in reversed(_MODULES):
        module.unregister()
    i18n.apply_language()
    for module in _MODULES:
        module.register()
    for window in getattr(bpy.context.window_manager, "windows", []):
        for area in window.screen.areas:
            area.tag_redraw()
    return None
