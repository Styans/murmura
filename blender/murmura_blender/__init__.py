"""Murmura for Blender: drone show choreography and .skyc export.

Sidebar tab "Murmura" in the 3D viewport:

* Drones - create a takeoff grid of drones lit by their object colour
* Formations - generate formations (shapes, text, SVG, images) or use any mesh
* Storyboard - order formations, hold times, light effects and motions, then
  build the show: takeoff, collision-aware transitions and landing are baked
  as keyframes onto the drones
* Safety & Export - validate the animation and export / import ``.skyc`` files

The interface is available in English and Russian (see the add-on
preferences or the language selector in the Drones panel).
"""

bl_info = {
    "name": "Murmura",
    "author": "Murmura contributors",
    "version": (0, 1, 0),
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
