import bpy, os
from bpy.types import Menu
from bpy.utils import previews


class RFMenu_MT_ToolPie(Menu):
    bl_idname = 'RF_MT_Tools'
    bl_label = 'RetopoFlow Tools'

    @classmethod
    def poll(self, context):
        tools = bpy.context.workspace.tools
        return (
            context.mode == 'EDIT_MESH' and
            tools.from_space_view3d_mode('EDIT_MESH', create=False).idname.split('.')[0] == 'retopoflow'
        )
    
    def draw_bottom_menu(self, pie):
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False).idname
        box = pie.column()
        box.emboss = 'RADIAL_MENU'

        if active_tool == 'retopoflow.polypen':
            row = box.row()
            row.emboss = 'NONE'
            row.label(text='Insert Mode')
            grid = box.grid_flow(even_columns=True, even_rows=True)
            row = grid.row(align=True)
            col = row.column()
            col.operator('retopoflow.polypen_setinsertmode_edgeonly', text='Edge')
            col.operator('retopoflow.polypen_setinsertmode_trionly', text='Triangle')
            col = row.column()
            col.operator('retopoflow.polypen_setinsertmode_triquad', text='Tri/Quad')
            col.operator('retopoflow.polypen_setinsertmode_quadonly', text='Quad')

        row = box.row()
        row.emboss = 'NONE'
        row.separator(type='SPACE')
        row = box.row()
        row.emboss = 'NONE'
        row.label(text='Clean Up')
        box.operator('retopoflow.meshcleanup', text='Selected')

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie() 

        for x in range(0):
            pie.separator()
            pie.separator()
            self.draw_bottom_menu(pie)
            pie.separator()
            pie.separator()
            pie.separator()
            pie.separator()
            pie.separator()

        # West   
        pie.operator('wm.tool_set_by_id', text='Poly Strips', icon_value=RF_icons['POLYSTRIPS'].icon_id).name='retopoflow.polystrips'

        # East
        pie.operator('wm.tool_set_by_id', text='Tweak', icon_value=RF_icons['TWEAK'].icon_id).name='retopoflow.tweak'

        # South
        self.draw_bottom_menu(pie)

        # North 
        pie.operator('wm.tool_set_by_id', text='Contours', icon_value=RF_icons['CONTOURS'].icon_id).name='retopoflow.contours'

        # Northwest
        pie.operator('wm.tool_set_by_id', text='Strokes', icon_value=RF_icons['STROKES'].icon_id).name='retopoflow.strokes'

        # Northeast
        pie.operator('wm.tool_set_by_id', text='Patches', icon_value=RF_icons['PATCHES'].icon_id).name='retopoflow.strokes'

        # Southwest
        pie.operator('wm.tool_set_by_id', text='Poly Pen', icon_value=RF_icons['POLYPEN'].icon_id).name='retopoflow.polypen'

        # Southeast 
        pie.operator('wm.tool_set_by_id', text='Relax', icon_value=RF_icons['RELAX'].icon_id).name='retopoflow.relax'


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
