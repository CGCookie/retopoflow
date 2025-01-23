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


class RF_Prefs(bpy.types.AddonPreferences):
    # Grabs the top level folder name regardless of this file's location
    bl_idname = __name__.split('.')[0]

    @staticmethod
    def get_prefs(context):
        bl_idname = __name__.split('.')[0]
        return context.preferences.addons[bl_idname].preferences


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

    """ Cleaning """
    #region
    cleaning_use_snap: bpy.props.BoolProperty(
        name='Snap to Surface',
        default=True
    )
    cleaning_use_merge: bpy.props.BoolProperty(
        name='Merge by Distance',
        default=True
    )
    cleaning_merge_threshold: bpy.props.FloatProperty(
        name='Merge Threshold',
        precision=4,
        default=0.0001,
        step=0.1,
        min=0
    )
    cleaning_use_delete_loose: bpy.props.BoolProperty(
        name='Delete Loose Verts',
        default=True
    )
    cleaning_use_fill_holes: bpy.props.BoolProperty(
        name='Fill Holes',
        default=True
    )
    cleaning_use_recalculate_normals: bpy.props.BoolProperty(
        name='Recalculate Normals',
        default=True
    )
    #endregion

    def draw(self, context):
        layout = self.layout

        from .rfpanels.tweaking_panel import draw_tweaking_options
        header, panel = layout.panel(idname='tweak_panel_prefs', default_closed=True)
        header.label(text="Tweaking")
        if panel:
            draw_tweaking_options(context, panel)

        from .rfpanels.mesh_cleanup_panel import draw_cleanup_options
        header, panel = layout.panel(idname='cleanup_panel_prefs', default_closed=True)
        header.label(text="Clean Up")
        if panel:
            draw_cleanup_options(context, panel, draw_operators=False)

def register():
    bpy.utils.register_class(RF_Prefs)

def unregister():
    bpy.utils.unregister_class(RF_Prefs)
