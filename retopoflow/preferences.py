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

import bpy
from .common.interface import update_toolbar


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
    highlight_color: bpy.props.FloatVectorProperty(
        name='Highlight Color',
        description=('The color used by the insert tools when adding new geometry'),
        subtype='COLOR',
        default=[1, 1, 0],
        min=0,
        max=1,
    )
    #endregion

    """ Hotkeys """
    enable_help_hotkey: bpy.props.BoolProperty(
        name='F1 - Launch Tool Help',
        description=('Enables F1 to launch the tool help while using a Retopoflow tool'),
        default=True
    )
    enable_issue_hotkey: bpy.props.BoolProperty(
        name='F2 - Report an Issue',
        description=('Enables F1 to launch the tool help while using a Retopoflow tool'),
        default=True
    )
    enable_pie_hotkey: bpy.props.BoolProperty(
        name='W - Retopoflow Pie Menu',
        description=('Enables W to bring up the Retopoflow pie menu while in a Retopoflow tool'),
        default=True
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

    def draw(self, context):
        layout = self.layout

        header, panel = layout.panel(idname='hotkey_panel_prefs', default_closed=True)
        header.label(text="Hotkeys")
        if panel:
            panel.use_property_split = True
            panel.use_property_decorate = True
            panel.prop(self, 'enable_pie_hotkey')
            panel.prop(self, 'enable_help_hotkey')
            panel.prop(self, 'enable_issue_hotkey')

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
            panel.label(text='New at Cursor')
            panel.prop(self, 'name_new', text='Name')
            panel.label(text='New from Active')
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


def register():
    bpy.utils.register_class(RF_Prefs)

def unregister():
    bpy.utils.unregister_class(RF_Prefs)
