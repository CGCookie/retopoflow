'''
Copyright (C) 2024 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import platform

import bpy
from .common.interface import update_toolbar, draw_section_header, draw_section_indent
from .rfoperators.pinning import toggle_pinning
from ..config.theme import Theme


class RF_Prefs(bpy.types.AddonPreferences):
    # Grabs the full extension name regardless of which library it is in
    # Since this file is in a subfolder, it needs the last folder name removed
    bl_idname = __package__.rsplit('.', 1)[0]

    @staticmethod
    def get_prefs(context):
        bl_idname = __package__.rsplit('.', 1)[0]
        return context.preferences.addons[bl_idname].preferences

    """ Display """
    #region
    expand_masking: bpy.props.BoolProperty(
        name='Expand Masking Options',
        description=(
            'Show masking options for brush tools directly in the 3D View tool header rather than in a menu. '
            'Useful when working on larger screens.'
        ),
        default=True,
    )
    expand_mirror: bpy.props.BoolProperty(
        name='Expand Mirror Axes',
        description=(
            'Show the X, Y, and Z axis toggles next to the mirror menu'
        ),
        default=True,
    )
    expand_tools: bpy.props.BoolProperty(
        name='Expand Tools',
        description=(
            'Shows all tools in the toolbar, which takes up more space but makes them more accessible'
        ),
        default=True,
        update=update_toolbar
    )
    expand_offset: bpy.props.BoolProperty(
        name='Expand Overlay Offset',
        description=('Displays the retopology overlay offset in the tool header'),
        default=True,
        update=update_toolbar
    )
    highlight_color: bpy.props.FloatVectorProperty(
        name='Highlight Color',
        description=('The color used by the insert tools when adding new geometry'),
        subtype='COLOR',
        default=[1, 1, 0],
        min=0,
        max=1,
    )
    vertex_size: bpy.props.IntProperty(
        name='Vertex Size',
        description='The visual size of each vertex in the viewport. This is only used when Component Size is enabled under Tool Switching',
        subtype='PIXEL',
        default=4,
        min=1,
        max=32,
        update=lambda self, context: setattr(context.preferences.themes[0].view_3d, 'vertex_size', self.vertex_size)
    )
    edge_width: bpy.props.IntProperty(
        name='Edge Width',
        description='The visual size of each edge in the viewport. This is only used when Component Size is enabled under Tool Switching',
        subtype='PIXEL',
        default=2,
        min=1,
        max=32,
        update=lambda self, context: setattr(context.preferences.themes[0].view_3d, 'edge_width', self.edge_width)
    )
    theme: bpy.props.EnumProperty(
        name="Theme",
        description="The color of mesh compenents while using Retopoflow",
        items=(
            ('none', "Blender", "The theme is not changed from your regular Blender preferences"),
            ('blue', "Blue", "Changes the color of components while using Retopoflow"),
            ('green', "Green", "Changes the color of components while using Retopoflow"),
            ('orange', "Orange", "Changes the color of components while using Retopoflow"),
            ('pink', "Pink", "Changes the color of components while using Retopoflow"),
            ('purple', "Purple", "Changes the color of components while using Retopoflow"),
        ),
        default='blue',
        update=lambda self, context: Theme.set_theme(context, self.theme)
    )
    #endregion

    """ Hotkeys """
    enable_help_hotkey: bpy.props.BoolProperty(
        name='Launch Tool Help',
        description=('Enables F1 to launch the tool help while using a Retopoflow tool'),
        default=True
    )
    enable_issue_hotkey: bpy.props.BoolProperty(
        name='Report an Issue',
        description=('Enables F1 to launch the tool help while using a Retopoflow tool'),
        default=True
    )
    enable_pie_hotkey: bpy.props.BoolProperty(
        name='Retopoflow Pie Menu',
        description=('Enables W to bring up the Retopoflow pie menu while in a Retopoflow tool'),
        default=True
    )
    pie_tool_context: bpy.props.EnumProperty(
        name="Pie Tool Context",
        description="The context in which the pie hotmenu will be shown",
        items=(
            ('ANY_TOOL', "Any Tool", "Can trigger the pie hotmenu from ANY tool"),
            ('RF_TOOL', "Retopoflow Tools", "Can trigger the pie hotmenu ONLY on Retopoflow tools"),
        ),
        default='ANY_TOOL'
    )

    """ Tool Switching """
    #region
    setup_automerge: bpy.props.BoolProperty(
        name='Auto Merge',
        description=("Automatically enables Auto Merge when using Retopoflow tools"),
        default=True,
    )
    setup_fade_inactive: bpy.props.BoolProperty(
        name='Fade Inactive',
        description=("Automatically enables Fade Inactive Geometry when using Retopoflow tools"),
        default=True,
    )
    setup_object_wires: bpy.props.BoolProperty(
        name='Object Wires',
        description=("Automatically enables wires for the active object when using Retopoflow tools, so you can see the result of modifiers"),
        default=False,
    )
    setup_retopo_overlay: bpy.props.BoolProperty(
        name='Retopology Overlay',
        description=("Automatically enables the retopology overlay when using Retopoflow tools"),
        default=True,
    )
    setup_selection_mode: bpy.props.BoolProperty(
        name='Selection Mode',
        description=("Automatically adjusts the selection mode for the selected Retopoflow tool"),
        default=True,
    )
    setup_snapping: bpy.props.BoolProperty(
        name='Snapping',
        description=("Automatically adjusts Blender's snapping settings for the selected Retopoflow tool"),
        default=True,
    )
    setup_component_size: bpy.props.BoolProperty(
        name='Component Size',
        description=("Use a separate size for vertices and edges when in Retopoflow tools"),
        default=True,
    )
    setup_selection_adjustments: bpy.props.BoolProperty(
        name='Selection Adjustments',
        description=("Alters the hotkeys for selection while Retopoflow is active. \n"
                    " - Loop selection gets stopped at inner corners for better use with Strokes. \n"
                    " - Pick Shortest Path with Shift has Fill Region disabled"
                    ),
        default=True,
    )
    setup_pinning: bpy.props.BoolProperty(
        name='Pinning via Creases',
        description=("Hijacks Blender's vertex crease system so we can display pins without any performance overhead. "
            "Disable this if you need to actively adjust creases while in Retopoflow mode. \n\n"
            "WARNING: Disabling will remove all current pins"),
        default=True,
        update=lambda self, context: toggle_pinning(context, self.setup_pinning)
    )
    #endregion

    """ Tweaking """
    #region
    tweaking_distance: bpy.props.IntProperty(
        name='Select Distance',
        description='Distance on screen to select geometry',
        subtype='PIXEL',
        default=20,
        min=1,
        max=100,
    )
    tweaking_move_hovered_mouse: bpy.props.BoolProperty(
        name='Mouse Auto Select',
        description='Selects the geometry under the cursor, if any, before transforming using the mouse',
        default=True,
    )
    tweaking_move_hovered_keyboard: bpy.props.BoolProperty(
        name='Keyboard Auto Select',
        description='Selects the geometry under the cursor, if any, before transforming using keyboard shortcuts',
        default=False,
    )
    tweaking_use_native: bpy.props.BoolProperty(
        name='Use Native Transform',
        description=(
            "Uses Blender's transform for tweaking rather than Retopoflow's. "
            "This allows you to use all of Blender's built-in features, but means that snapping will affect the source and retopology objects the same. "
            "\n\n"
            "For example, using the native transform with vertex snapping means that the selection will snap to the individual vertices of the high poly source, "
            "while using it without vertex snapping means that you will not be able to snap the vertices of the low poly retopology object to each other."
        ),
        default=False,
    )
    #endregion

    """ Naming """
    #region
    name_new: bpy.props.StringProperty(
        name='New Object Name',
        description='The name of the new retopology object when creating one at the 3D Cursor',
        default='Retopology'
    )
    name_search: bpy.props.StringProperty(
        name='Search',
        description='The text to find and replace in the active object name. Not case sensative',
        default='_High'
    )
    name_replace: bpy.props.StringProperty(
        name='Replace',
        description='The text that replaces the searched for text when creating a new retopology object from the active object',
        default='_Low'
    )
    name_suffix: bpy.props.StringProperty(
        name='From Active Suffix',
        description=(
            'When creating a new retopo object from the active object, the new object will inherit the active object name with this added at the end. '
            'Only used when the searched for text is not found'
        ),
        default='_Retopology'
    )
    #endregion

    """ Warnings """
    warn_no_sources: bpy.props.BoolProperty(
        name='No Sources Detected',
        description='Warns when starting Retopoflow with no sources detected',
        default=True,
    )

    def draw(self, context):
        layout = self.layout

        header, panel = layout.panel(idname='hotkey_panel_prefs', default_closed=True)
        header.label(text="Hotkeys")
        if panel:
            panel.use_property_split = True
            panel.use_property_decorate = False

            row = panel.row(heading='Retopoflow Pie Menu')
            row.prop(self, 'enable_pie_hotkey', text=' W')
            row = panel.row()
            row.enabled = self.enable_pie_hotkey
            row.prop(self, 'pie_tool_context', text='Triggers From', expand=False)
            panel.separator()
            row = panel.row(heading='Open Docs')
            row.prop(self, 'enable_help_hotkey', text=' F1')
            row = panel.row(heading='Report Issue')
            row.prop(self, 'enable_issue_hotkey', text=' F2')

            panel.separator(type='SPACE')
            panel.separator(type='LINE', factor=1)
            panel.separator(type='SPACE')
            draw_section_header(context, panel, 'You can change the hotkey for any action by:', icon='INFO')
            row = panel.row(align=True)
            draw_section_indent(context, row)
            draw_section_indent(context, row)
            col = row.column()
            col.label(text=("1. Opening Blender's keymap preferences"))
            col.label(text=('2. Searching for Retopoflow'))
            col.label(text=('3. Changing the keymap'))
            col.label(text=('3. Saving Preferences'))
            draw_section_header(context, panel, 'Not all custom adjustments can be guaranteed to work')
            panel.separator(type='SPACE')
            panel.separator(type='LINE', factor=1)

        from .rfpanels.interface_panel import draw_ui_options
        header, panel = layout.panel(idname='RF_interface_prefs', default_closed=True)
        header.label(text="Interface")
        if panel:
            draw_ui_options(context, panel)

        header, panel = layout.panel(idname='naming_panel_prefs', default_closed=True)
        header.label(text="Naming")
        if panel:
            panel.use_property_split = True
            panel.use_property_decorate = True
            draw_section_header(context, panel, 'New at Cursor')
            panel.prop(self, 'name_new', text='Name')
            draw_section_header(context, panel, 'New from Active')
            panel.prop(self, 'name_search', text='Try to Replace')
            panel.prop(self, 'name_replace', text='With')
            panel.separator()
            panel.prop(self, 'name_suffix', text='Fallback Suffix')

        from .rfpanels.tool_switching_panel import draw_tool_switching_options
        header, panel = layout.panel(idname='switching_prefs', default_closed=True)
        header.label(text="Tool Switching")
        if panel:
            draw_tool_switching_options(context, panel)

        from .rfpanels.tweaking_panel import draw_tweaking_options
        header, panel = layout.panel(idname='tweak_panel_prefs', default_closed=True)
        header.label(text="Tweaking")
        if panel:
            draw_tweaking_options(context, panel)

        header, panel = layout.panel(idname='warning_panel_prefs', default_closed=True)
        header.label(text="Warnings")
        if panel:
            panel.use_property_split = True
            panel.use_property_decorate = False
            panel.prop(self, 'warn_no_sources')

        if bpy.app.version >= (4,5,0) and context.preferences.inputs.tablet_api != 'WINTAB' and platform.system() == 'Windows':
            box = layout.box().column(align=True)
            box.label(text="Notice for Windows users:", icon='ERROR')
            box.label(text="If you encounter lagg issues while using a tablet, consider switching")
            box.label(text="to WinTab API in [ Blender Preferences > Input > Tablet > Tablet API ].")
            row = box.row()
            row.alignment = 'RIGHT'
            row.operator('wm.url_open', text='Blender Report').url = 'https://projects.blender.org/blender/blender/issues/144139'
            row.operator('wm.url_open', text='Retopoflow Report').url = 'https://github.com/CGCookie/retopoflow/issues/1574'


def register():
    bpy.utils.register_class(RF_Prefs)

def unregister():
    bpy.utils.unregister_class(RF_Prefs)
