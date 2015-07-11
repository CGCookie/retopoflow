import bpy

from .lib import common_utilities
from .lib.common_utilities import bversion
from .icons import load_icons

class CGCOOKIE_OT_retopoflow_panel(bpy.types.Panel):
    '''RetopoFlow Tools'''
    bl_category = "Retopology"
    bl_label = "RetopoFlow"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    @classmethod
    def poll(cls, context):
        mode = bpy.context.mode
        obj = context.active_object
        return (obj and obj.type == 'MESH' and mode in ('OBJECT', 'EDIT_MESH'))

    def draw(self, context):
        layout = self.layout

        settings = common_utilities.get_settings()

        col = layout.column(align=True)
        view = context.space_data

        col.label("Source Object:")
        col.prop(settings, 'source_object', icon_only=True)

        col = layout.column(align=True)

        if bversion() > '002.074.004':
            icons = load_icons()
            contours_icon = icons.get("rf_contours_icon")
            col.operator("cgcookie.contours", icon_value=contours_icon.icon_id)
        else:
            col.operator("cgcookie.contours", icon='IPO_LINEAR')

        box = layout.box()
        row = box.row()

        row.prop(settings, "contour_panel_settings")

        if settings.contour_panel_settings:
            col = box.column()
            col.prop(settings, "vertex_count")

            col.label("Guide Mode:")
            col.prop(settings, "ring_count")

            col.label("Cache:")
            col.prop(settings, "recover", text="Recover")

            if settings.recover:
                col.prop(settings, "recover_clip")

            col.operator("cgcookie.contours_clear_cache", text = "Clear Cache", icon = 'CANCEL')

        col = layout.column(align=True)
        if bversion() > '002.074.004':
            polystrips_icon = icons.get("rf_polystrips_icon")
            col.operator("cgcookie.polystrips", icon_value=polystrips_icon.icon_id)
        else:
            col.operator("cgcookie.polystrips", icon='IPO_BEZIER')



        box = layout.box()
        row = box.row()

        row.prop(settings, "polystrips_panel_settings")

        if settings.polystrips_panel_settings:
            col = box.column()
            col.prop(settings, "symmetry_plane", text ="Symmetry Plane")


class CGCOOKIE_OT_retopoflow_menu(bpy.types.Menu):  
    bl_label = "Retopology"
    bl_space_type = 'VIEW_3D'
    bl_idname = "object.retopology_menu"

    def draw(self, context):
        layout = self.layout

        layout.operator_context = 'INVOKE_DEFAULT'

        layout.operator("cgcookie.contours", icon="IPO_LINEAR")
        layout.operator("cgcookie.polystrips", icon="IPO_BEZIER")

