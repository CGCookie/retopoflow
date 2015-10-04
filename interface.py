import bpy

from .lib import common_utilities
from .lib.common_utilities import bversion

if bversion() >= '002.076.000':
    from .icons import load_icons

class CGCOOKIE_OT_retopoflow_panel(bpy.types.Panel):
    '''RetopoFlow Tools'''
    bl_category = "Retopology"
    bl_label = "RetopoFlow"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    def draw(self, context):
        layout = self.layout

        settings = common_utilities.get_settings()
        
        
        if bversion() < '002.076.00':
            col = layout.column(align=True)
            col.label('Error: Retopoflow requires')
            col.label('Blender 2.76+')
            return
        

        col = layout.column(align=True)

        col.label("Source Object:")

        col = layout.column(align=True)

        if context.mode == 'OBJECT':
            row = col.row(align=True)
            scene = context.scene
            row.prop_search(settings, "source_object", scene, "objects", text='')

            sub = row.row(align=True)
            sub.scale_x = 0.1
            sub.operator("cgcookie.eye_dropper", icon='EYEDROPPER').target_prop = 'source_object'
        elif context.mode == 'EDIT_MESH':
            row = col.row(align=True)
            scene = context.scene
            row.prop_search(settings, "source_object", scene, "objects", text='')

            sub = row.row(align=True)
            sub.scale_x = 0.1
            sub.operator("cgcookie.eye_dropper", icon='EYEDROPPER').target_prop = 'source_object'

        if context.mode != 'EDIT_MESH':

            col = layout.column(align=True)
            col.label("Target Object:")

            row = col.row(align=True)
            scene = context.scene
            row.prop_search(settings, "target_object", scene, "objects", text='')

            sub = row.row(align=True)
            sub.scale_x = 0.1
            sub.operator("cgcookie.eye_dropper", icon='EYEDROPPER').target_prop = 'target_object'

        col = layout.column(align=True)

        col.label("Tools:")
        if bversion() > '002.074.004':
            icons = load_icons()
            contours_icon = icons.get("rf_contours_icon")
            col.operator("cgcookie.contours", icon_value=contours_icon.icon_id)
        else:
            col.operator("cgcookie.contours", icon='IPO_LINEAR')

        if bversion() > '002.074.004':
            polystrips_icon = icons.get("rf_polystrips_icon")
            col.operator("cgcookie.polystrips", icon_value=polystrips_icon.icon_id)
        else:
            col.operator("cgcookie.polystrips", icon='IPO_BEZIER')
        
        if context.mode =='EDIT_MESH':
            if bversion() > '00.2.074.004':
                tweaK_icon = icons.get("rf_tweak_icon")
                loop_cut_icon = icons.get("rf_loopcut_icon")
                edgeslide_icon = icons.get("rf_edgeslide_icon")

                col.operator("cgcookie.tweak", icon_value=tweaK_icon.icon_id)
                col.operator("cgcookie.loop_cut", text='Loop Cut', icon_value=loop_cut_icon.icon_id)
                col.operator("cgcookie.edge_slide", text='Edge Slide', icon_value=edgeslide_icon.icon_id)

        col = layout.column(align=True)
        col.label("Tool Settings:")

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

        if bversion() > '002.074.004':
            icons = load_icons()
            contours_icon = icons.get("rf_contours_icon")
            polystrips_icon = icons.get("rf_polystrips_icon")

            layout.operator("cgcookie.contours", icon_value=contours_icon.icon_id)
            layout.operator("cgcookie.polystrips", icon_value=polystrips_icon.icon_id)

        else:
            layout.operator("cgcookie.contours", icon="IPO_LINEAR")
            layout.operator("cgcookie.polystrips", icon="IPO_BEZIER")

        if context.mode =='EDIT_MESH':
            if bversion() > '002.074.004':
                icons = load_icons()
                loopcut_icon = icons.get("rf_loopcut_icon")
                edgeslide_icon = icons.get("rf_edgeslide_icon")
                tweak_icon = icons.get("rf_tweak_icon")

                layout.operator("cgcookie.tweak", icon_value=tweak_icon.icon_id)
                layout.operator("cgcookie.loop_cut", text="Loop Cut", icon_value=loopcut_icon.icon_id)
                layout.operator("cgcookie.edge_slide", text="Edge Slide", icon_value=edgeslide_icon.icon_id)
            else:
                layout.operator("cgcookie.tweak", icon="HAND")
                layout.operator("cgcookie.loop_cut", text='Loop Cut', icon='EDGESEL')

