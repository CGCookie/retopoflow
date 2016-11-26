import bpy

from .lib import common_utilities
from .lib.common_utilities import bversion
from . import addon_updater_ops

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

        # explicitly call to check for update in background
        # note: built-in checks ensure it runs at most once
        addon_updater_ops.check_for_update_background(context)

        settings = common_utilities.get_settings()
        
        
        if bversion() < '002.076.00':
            col = layout.column(align=True)
            col.label('ERROR: upgrade needed', icon='ERROR')
            col.label('RetopoFlow requires Blender 2.76+')
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

        icons = load_icons()
        contours_icon = icons.get("rf_contours_icon")
        col.operator("cgcookie.contours", icon_value=contours_icon.icon_id)

        polystrips_icon = icons.get("rf_polystrips_icon")
        col.operator("cgcookie.polystrips", icon_value=polystrips_icon.icon_id)

        polypen_icon = icons.get("rf_polypen_icon")
        col.operator("cgcookie.polypen", icon_value=polypen_icon.icon_id)

        if context.mode =='EDIT_MESH':
            tweaK_icon = icons.get("rf_tweak_icon")
            loop_cut_icon = icons.get("rf_loopcut_icon")
            loopslide_icon = icons.get("rf_loopslide_icon")

            col.operator("cgcookie.tweak", icon_value=tweaK_icon.icon_id)
            col.operator("cgcookie.loop_cut", text='Loop Cut', icon_value=loop_cut_icon.icon_id)
            col.operator("cgcookie.loop_slide", text='Loop Slide', icon_value=loopslide_icon.icon_id)

        col = layout.column(align=True)
        col.label("Tool Settings:")

        box = layout.box()
        row = box.row()

        row.prop(settings, "retopoflow_panel_settings")

        if settings.retopoflow_panel_settings:
            col = box.column()
            col.label("CONTOURS:")

            col.prop(settings, "vertex_count")

            col.label("Guide Mode:")
            col.prop(settings, "ring_count")

            col.label("Cache:")
            col.prop(settings, "recover", text="Recover")

            if settings.recover:
                col.prop(settings, "recover_clip")

            #col.operator("cgcookie.contours_clear_cache", text = "Clear Cache", icon = 'CANCEL')


            col = box.column()
            col.label("POLYSTRIPS:")
            col.prop(settings, "symmetry_plane", text ="Symmetry Plane")

        col = layout.column(align=True)
        col.label("Debug:")
        col.operator("wm.open_log", "Open Error Log")

        addon_updater_ops.update_notice_box_ui(self, context)
        

class CGCOOKIE_OT_retopoflow_menu(bpy.types.Menu):  
    bl_label = "Retopology"
    bl_space_type = 'VIEW_3D'
    bl_idname = "object.retopology_menu"

    def draw(self, context):
        layout = self.layout

        layout.operator_context = 'INVOKE_DEFAULT'

        icons = load_icons()
        contours_icon = icons.get("rf_contours_icon")
        polystrips_icon = icons.get("rf_polystrips_icon")
        polypen_icon = icons.get("rf_polypen_icon")

        layout.operator("cgcookie.contours", icon_value=contours_icon.icon_id)
        layout.operator("cgcookie.polystrips", icon_value=polystrips_icon.icon_id)
        layout.operator("cgcookie.polypen", icon_value=polypen_icon.icon_id)


        if context.mode =='EDIT_MESH':
            icons = load_icons()
            loopcut_icon = icons.get("rf_loopcut_icon")
            loopslide_icon = icons.get("rf_loopslide_icon")
            tweak_icon = icons.get("rf_tweak_icon")

            layout.operator("cgcookie.tweak", icon_value=tweak_icon.icon_id)
            layout.operator("cgcookie.loop_cut", text="Loop Cut", icon_value=loopcut_icon.icon_id)
            layout.operator("cgcookie.loop_slide", text="Loop Slide", icon_value=loopslide_icon.icon_id)

