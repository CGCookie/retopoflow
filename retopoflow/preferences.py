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
        default=15,
        min=1,
        max=100,
    )
    tweaking_move_hovered_mouse: bpy.props.BoolProperty(
        name='Mouse Auto Select',
        description=('Selects the geometry under the cursor, if any, before transforming using the mouse'),
        default=True,
    )
    tweaking_move_hovered_keyboard: bpy.props.BoolProperty(
        name='Keyboard Auto Select',
        description=('Selects the geometry under the cursor, if any, before transforming using keyboard shortcuts'),
        default=False,
    )
    #endregion

    def draw(self, context):
        layout = self.layout

        from .rfpanels.general_panel import draw_general_options
        header, panel = layout.panel(idname='general_panel_prefs', default_closed=True)
        header.label(text="General")
        if panel:
            draw_general_options(context, panel)

        header, panel = layout.panel(idname='switching_prefs', default_closed=True)
        header.label(text="Tool Switching")
        if panel:
            panel.use_property_split = True
            row = panel.row(heading='Automatic')
            row.prop(self, 'setup_automerge')
            panel.prop(self, 'setup_fade_inactive')
            panel.prop(self, 'setup_object_wires')
            panel.prop(self, 'setup_retopo_overlay')
            panel.prop(self, 'setup_selection_mode')
            panel.prop(self, 'setup_snapping')
            panel.separator()
            panel.label(text=('You can assign a custom hotkey for any tool by:'), icon='INFO')
            row=panel.split(factor=0.4)
            row.separator()
            col = row.column()
            col.label(text=('1. Right Clicking'))
            col.label(text=('2. Choosing Assign Shortcut'))
            col.label(text=('3. Saving Preferences'))
            panel.separator()

        from .rfpanels.tweaking_panel import draw_tweaking_options
        header, panel = layout.panel(idname='tweak_panel_prefs', default_closed=True)
        header.label(text="Tweaking")
        if panel:
            draw_tweaking_options(context, panel)
            

def register():
    bpy.utils.register_class(RF_Prefs)

def unregister():
    bpy.utils.unregister_class(RF_Prefs)
