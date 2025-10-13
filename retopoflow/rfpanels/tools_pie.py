import bpy, os
from bpy.types import Menu, Operator
from bpy.utils import previews

from ..rftool_polypen.polypen import PolyPen_Insert_Modes


class RFTool_OT_SwitchToPatches(Operator):
    bl_idname = 'retopoflow.switch_to_patches'
    bl_label = 'Switch to Patches'
    bl_description = 'Temporary operator to show that patches cannot be switched to'

    @classmethod
    def poll(self, context):
        return False

    def execute(self, context):
        return {'FINISHED'}


class RFMenu_MT_ToolPie(Menu):
    bl_idname = 'RF_MT_Tools'
    bl_label = 'RetopoFlow Tools'

    @classmethod
    def poll(self, context):
        from ..preferences import RF_Prefs
        tools = bpy.context.workspace.tools
        return (
            RF_Prefs.get_prefs(context).enable_pie_hotkey and
            context.mode == 'EDIT_MESH'
            # and tools.from_space_view3d_mode('EDIT_MESH', create=False).idname.split('.')[0] == 'retopoflow'
        )

    def draw_bottom_menu(self, pie):
        tool = bpy.context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        back = pie.box().column(align=True)

        row = back.row()
        row.emboss = 'RADIAL_MENU'
        row.label(text='Clean Up')
        section = back.box().column()
        row = section.row(align=True)
        row.operator('retopoflow.meshcleanup', text='Selected').affect_all=False
        row.operator('retopoflow.meshcleanup', text='All').affect_all=True

        if tool.idname == 'retopoflow.polypen':
            props = tool.operator_properties(tool.idname)
            row = back.row()
            row.emboss = 'RADIAL_MENU'
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
                row.emboss = 'RADIAL_MENU'
                row.label(text='Quad Stability')
                row = section.row(align=True)
                row.operator('retopoflow.polypen_quad_stability_quarter', text='0.25')
                row.operator('retopoflow.polypen_quad_stability_half', text='0.50')
                row.operator('retopoflow.polypen_quad_stability_threequarters', text='0.75')
                row.operator('retopoflow.polypen_quad_stability_full', text='1.00')

        elif tool.idname == 'retopoflow.polystrips':
            props = tool.operator_properties(tool.idname)
            row = back.row()
            row.emboss = 'RADIAL_MENU'
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
            row.emboss = 'RADIAL_MENU'
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
            row.emboss = 'RADIAL_MENU'
            row.label(text='Contours')
            section = back.box().column()
            section.ui_units_x = 8
            grid = section.grid_flow(even_columns=True, even_rows=True)
            row = grid.row(align=True)
            col = row.column(align=False)
            col.prop(props, 'span_count')
            col.row(align=True).prop(props, 'process_source_method', expand=True)

        elif tool.idname == 'retopoflow.tweak' or tool.idname == 'retopoflow.relax':
            tool_name = 'Tweak' if tool.idname == 'retopoflow.tweak' else 'Relax'
            props = tool.operator_properties(tool.idname)
            row = back.row()
            row.emboss = 'RADIAL_MENU'
            row.label(text=tool_name)
            section = back.box().column()
            section.ui_units_x = 9
            grid = section.grid_flow(even_columns=True, even_rows=True)
            row = grid.row(align=True)
            col = row.column(align=False)
            col.prop(props, 'brush_radius')
            col.prop(props, 'brush_strength', slider=True)
            col.prop(props, 'brush_falloff', slider=True)
            col.row(align=True, heading='Selected').prop(props, 'mask_selected', expand=True, icon_only=True)
            col.row(align=True, heading='Boundary').prop(props, 'mask_boundary', expand=True, icon_only=True)
            row = col.row(align=True)
            row.prop(props, 'include_corners')
            row.prop(props, 'include_occluded')



    def draw(self, context):
        tool = bpy.context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        layout = self.layout
        pie = layout.menu_pie()

        # West
        pie.operator(
            'retopoflow.switch_to_polystrips',
            text='PolyStrips',
            icon_value=RF_icons['POLYSTRIPS'].icon_id,
            depress=tool.idname=='retopoflow.polystrips'
        )

        # East
        pie.operator(
            'retopoflow.switch_to_tweak',
            text='Tweak',
            icon_value=RF_icons['TWEAK'].icon_id,
            depress=tool.idname=='retopoflow.tweak'
        )

        # South
        self.draw_bottom_menu(pie)

        # North
        pie.operator(
            'retopoflow.switch_to_contours',
            text='Contours',
            icon_value=RF_icons['CONTOURS'].icon_id,
            depress=tool.idname=='retopoflow.contours'
        )

        # Northwest
        pie.operator(
            'retopoflow.switch_to_strokes',
            text='Strokes',
            icon_value=RF_icons['STROKES'].icon_id,
            depress=tool.idname=='retopoflow.strokes'
        )

        # Northeast
        pie.operator(
            'retopoflow.switch_to_patches',
            text='Patches',
            icon_value=RF_icons['PATCHES'].icon_id,
            depress=tool.idname=='retopoflow.patches'
        )

        # Southwest
        pie.operator(
            'retopoflow.switch_to_polypen',
            text='PolyPen',
            icon_value=RF_icons['POLYPEN'].icon_id,
            depress=tool.idname=='retopoflow.polypen'
        )

        # Southeast
        pie.operator(
            'retopoflow.switch_to_relax',
            text='Relax',
            icon_value=RF_icons['RELAX'].icon_id,
            depress=tool.idname=='retopoflow.relax'
        )


keymaps = []
RF_icons = None


def register():
    bpy.utils.register_class(RFTool_OT_SwitchToPatches)
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
    bpy.utils.unregister_class(RFTool_OT_SwitchToPatches)
    bpy.utils.unregister_class(RFMenu_MT_ToolPie)

    for keymap, keymap_item in keymaps:
        keymap.keymap_items.remove(keymap_item)
    keymaps.clear()

    global RF_icons
    previews.remove(RF_icons)
