"""Add-on preferences."""

import bpy
from bpy.props import EnumProperty

from .i18n import LANGUAGES


def _language_changed(self, context):
    from . import reload_language

    # re-register outside of the property update to keep the UI responsive
    bpy.app.timers.register(reload_language, first_interval=0.01)


class MURMURA_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    language: EnumProperty(
        name="Language / Язык",
        items=LANGUAGES,
        default="AUTO",
        update=_language_changed,
    )

    def draw(self, context):
        self.layout.prop(self, "language")


def preferences():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


def register():
    bpy.utils.register_class(MURMURA_Preferences)


def unregister():
    bpy.utils.unregister_class(MURMURA_Preferences)
