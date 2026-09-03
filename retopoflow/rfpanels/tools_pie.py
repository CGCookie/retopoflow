import bpy, os
from bpy.types import Menu
from bpy.utils import previews

from ..rftool_polypen.polypen import PolyPen_Insert_Modes
# from ..rftool_patches.patches import Patches_Orientations



class RFMenu_MT_ToolPie(Menu):
    bl_idname = 'RF_MT_Tools'
    bl_label = 'Retopoflow Tools Pie Menu'

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_MESH':
            return False
        from ..preferences import RF_Prefs
        prefs = RF_Prefs.get_prefs(context)
        if prefs.pie_tool_context == 'ANY_TOOL':
            return True
        if prefs.pie_tool_context == 'RF_TOOL':
            tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
            return tool is not None and tool.idname.split('.')[0] == 'retopoflow'
        return False

    def draw_bottom_menu(self, context, pie):
        scene_props = context.scene.retopoflow
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        pie_emboss = 'PIE_MENU' if bpy.app.version >= (5,0,0) else 'RADIAL_MENU'

        back = pie.box().column(align=True)

        row = back.row()
        row.emboss = pie_emboss
        row.label(text='Clean Up')
        section = back.box().column()
        row = section.split(align=True)
        row.operator('retopoflow.meshcleanup', text='Selected').affect_all=False
        row.operator('retopoflow.meshcleanup', text='All').affect_all=True
        section.separator(type='LINE', factor=0.5)
        row = section.row(align=False)
        row.operator_context = 'INVOKE_REGION_WIN' # So ops below can seed their defaults from the RF scene settings
        row.operator('retopoflow.space_evenly', text='Even')
        row.operator('retopoflow.relax_selected', text='Relax')

        if tool.idname == 'retopoflow.polypen':
            props = tool.operator_properties(tool.idname)
            row = back.row()
            row.emboss = pie_emboss
            row.label(text='Poly Pen Insert Mode')
            section = back.box().column()
            section.ui_units_x = 8
            grid = section.grid_flow(even_columns=True, even_rows=True)
            row = grid.row(align=True)
            col = row.column(align=True)
            col.operator('retopoflow.polypen_setinsertmode_edgeonly', text='Edge')
            col.operator('retopoflow.polypen_setinsertmode_triquad', text='Tri/Quad')
            col = row.column(align=True)
            col.operator('retopoflow.polypen_setinsertmode_trionly', text='Triangle')
            col.operator('retopoflow.polypen_setinsertmode_quadonly', text='Quad')
            if PolyPen_Insert_Modes.insert_mode == 4:
                row = section.row()
                row.emboss = pie_emboss
                row.label(text='Quad Stability')
                row = section.row(align=True)
                row.operator('retopoflow.polypen_quad_stability_quarter', text='0.25')
                row.operator('retopoflow.polypen_quad_stability_half', text='0.50')
                row.operator('retopoflow.polypen_quad_stability_threequarters', text='0.75')
                row.operator('retopoflow.polypen_quad_stability_full', text='1.00')

        elif tool.idname == 'retopoflow.polystrips':
            props = tool.operator_properties(tool.idname)
            row = back.row()
            row.emboss = pie_emboss
            row.label(text='PolyStrips')
            section = back.box().column()
            section.ui_units_x = 8
            grid = section.grid_flow(even_columns=True, even_rows=True)
            row = grid.row(align=True)
            col = row.column(align=False)
            col.prop(props, 'brush_radius')
            col.prop(props, 'split_angle')

        elif tool.idname == 'retopoflow.strokes':
            props = tool.operator_properties(tool.idname)
            row = back.row()
            row.emboss = pie_emboss
            row.label(text='Strokes')
            section = back.box().column()
            section.ui_units_x = 10
            grid = section.grid_flow(even_columns=True, even_rows=True)
            row = grid.row(align=True)
            col = row.column(align=False)
            col.row(align=True).prop(props, 'span_insert_mode', expand=True)
            if props.span_insert_mode == 'FIXED':
                col.prop(props, 'cut_count', text="Count")
            else:
                col.prop(props, 'brush_radius', text="Radius")
            col.prop(props, 'smooth_angle', text='Blending', slider=True)
            col.row(align=True).prop(props, 'extrapolate_mode', expand=True)

        elif tool.idname == 'retopoflow.contours':
            props = tool.operator_properties(tool.idname)
            row = back.row()
            row.emboss = pie_emboss
            row.label(text='Contours')
            section = back.box().column()
            section.ui_units_x = 8
            col = section.column(align=False)
            col.prop(props, 'span_count')
            col = section.column(align=True)
            col.prop(props, 'process_source_method', expand=True)

        elif tool.idname == 'retopoflow.tweak' or tool.idname == 'retopoflow.relax':
            tool_name = 'Tweak' if tool.idname == 'retopoflow.tweak' else 'Relax'
            props = tool.operator_properties(tool.idname)
            row = back.row()
            row.emboss = pie_emboss
            row.label(text=tool_name)
            section = back.box().column()
            section.ui_units_x = 9
            grid = section.grid_flow(even_columns=True, even_rows=True)
            row = grid.row(align=True)
            col = row.column(align=False)
            col.prop(props, 'brush_radius')
            col.prop(props, 'brush_strength', slider=True)
            col.prop(props, 'brush_falloff', slider=True)

            split = col.row().split(factor=0.4, align=True)
            split.label(text='Selected')
            split.prop(scene_props, 'mask_selected', expand=True, icon_only=True)
            split = col.row().split(factor=0.4, align=True)
            split.label(text='Boundary')
            split.prop(scene_props, 'mask_boundary', expand=True, icon_only=True)
            split = col.row().split(factor=0.4, align=True)
            split.label(text='Seams')
            split.prop(scene_props, 'mask_seams', expand=True, icon_only=True)

            row = col.row(align=True)
            row.prop(scene_props, 'include_corners')
            row.prop(scene_props, 'include_pinned')

        elif tool.idname == 'retopoflow.legacy_patches':
            from ..rftool_legacy_patches.legacy_patches import draw_patches_props
            props = tool.operator_properties(tool.idname)
            row = back.row()
            row.emboss = pie_emboss
            row.label(text='Patches')
            section = back.box().column()
            section.ui_units_x = 8
            draw_patches_props(section, props, header=False)



    def draw(self, context):
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        layout = self.layout
        pie = layout.menu_pie()

        # West
        _ = pie.operator(
            'retopoflow.switch_to_polystrips',
            text='PolyStrips',
            icon_value=RF_icons['POLYSTRIPS'].icon_id,
            depress=tool.idname=='retopoflow.polystrips'
        )

        # East
        _ = pie.operator(
            'retopoflow.switch_to_tweak',
            text='Tweak',
            icon_value=RF_icons['TWEAK'].icon_id,
            depress=tool.idname=='retopoflow.tweak'
        )

        # South
        self.draw_bottom_menu(context, pie)

        # North
        _ = pie.operator(
            'retopoflow.switch_to_contours',
            text='Contours',
            icon_value=RF_icons['CONTOURS'].icon_id,
            depress=tool.idname=='retopoflow.contours'
        )

        # Northwest
        _ = pie.operator(
            'retopoflow.switch_to_strokes',
            text='Strokes',
            icon_value=RF_icons['STROKES'].icon_id,
            depress=tool.idname=='retopoflow.strokes'
        )

        # Northeast
        _ = pie.operator(
            'retopoflow.switch_to_legacy_patches',
            text='Patches',
            icon_value=RF_icons['PATCHES'].icon_id,
            depress=tool.idname=='retopoflow.legacy_patches',
        )

        # Southwest
        _ = pie.operator(
            'retopoflow.switch_to_polypen',
            text='PolyPen',
            icon_value=RF_icons['POLYPEN'].icon_id,
            depress=tool.idname=='retopoflow.polypen'
        )

        # Southeast
        _ = pie.operator(
            'retopoflow.switch_to_relax',
            text='Relax',
            icon_value=RF_icons['RELAX'].icon_id,
            depress=tool.idname=='retopoflow.relax'
        )



keymaps = []
RF_icons = None


def register():
    bpy.utils.register_class(RFMenu_MT_ToolPie)

    wm = bpy.context.window_manager
    keyconfigs = wm.keyconfigs.addon
    if keyconfigs:
        keymap = keyconfigs.keymaps.new(name='3D View', space_type='VIEW_3D')
        keymap_item = keymap.keymap_items.new('wm.call_menu_pie', 'W', 'PRESS', ctrl=False, shift=False, alt=False)
        keymap_item.properties.name =  RFMenu_MT_ToolPie.bl_idname
        keymaps.append((keymap, keymap_item))

    global RF_icons
    RF_icons = previews.new()
    icons_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, 'icons'))
    RF_icons.load('POLYPEN', os.path.join(icons_dir, 'polypen-icon.png'), 'IMAGE')
    RF_icons.load('POLYSTRIPS', os.path.join(icons_dir, 'polystrips-icon.png'), 'IMAGE')
    RF_icons.load('STROKES', os.path.join(icons_dir, 'strokes-icon.png'), 'IMAGE')
    RF_icons.load('CONTOURS', os.path.join(icons_dir, 'contours-icon.png'), 'IMAGE')
    RF_icons.load('PATCHES', os.path.join(icons_dir, 'patches-icon.png'), 'IMAGE')
    RF_icons.load('TWEAK', os.path.join(icons_dir, 'tweak-icon.png'), 'IMAGE')
    RF_icons.load('RELAX', os.path.join(icons_dir, 'relax-icon.png'), 'IMAGE')

def unregister():
    bpy.utils.unregister_class(RFMenu_MT_ToolPie)

    for keymap, keymap_item in keymaps:
        keymap.keymap_items.remove(keymap_item)
    keymaps.clear()

    global RF_icons
    previews.remove(RF_icons)
