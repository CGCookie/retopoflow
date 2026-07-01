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

from __future__ import annotations

import platform
from typing import cast

import bpy
from bpy.types import Context, AddonPreferences, UILayout
from .common.interface import update_toolbar, draw_section_header, draw_section_indent, draw_keymap_options
from .rfoperators.pinning import toggle_pinning
from ..config.theme import Theme
from ..config.keymaps import get_user_keymap_item
from ..addon_common.autosave.autosave import AutoSave

assert __package__, 'Do not run this Python file directly'
addon_name = __package__.rsplit('.', 1)[0]

class RF_Prefs(AddonPreferences):
    # Grabs the full extension name regardless of which library it is in
    # Since this file is in a subfolder, it needs the last folder name removed
    bl_idname : str = addon_name

    @staticmethod
    def get_prefs(context : Context) -> RF_Prefs:
        addon = context.preferences.addons[addon_name]
        addon_prefs = addon.preferences
        assert addon_prefs
        return cast(RF_Prefs, addon_prefs)

    """ RF AutoSave """
    enable_autosave: bpy.props.BoolProperty(
        name='Edit Mode Auto-Save',
        description=(
            "Automatically save a backup every few minutes while in Edit Mode. "
            "Blender's Auto-Save does not work in Edit Mode, so this feature is needed to recover long modeling sessions."
            "\n\n"
            "Disable if you have another auto save add-on enabled or if you notice a "
            "significant slow down and do not want to auto save while working in Edit Mode."
        ),
        default=True,
        update=lambda self, _context: AutoSave.property_update_enabled(self.enable_autosave)
        # do not use set and get, otherwise value of property is not stored in Blender's preferences
    )

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
        update=lambda self, context: update_toolbar()
    )
    expand_offset: bpy.props.BoolProperty(
        name='Expand Overlay Offset',
        description=('Displays the retopology overlay offset in the tool header'),
        default=True,
        update=lambda self, context: update_toolbar()
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
        update=lambda self, context: Theme.set_theme(context, str(self.theme))
    )
    #endregion

    """ Hotkeys """
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
    tweaking_update_normals: bpy.props.BoolProperty(
        name='Update Normals',
        description='Update the normals of the affected faces to try to keep them facing outwards',
        default=True
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

    def draw(self, context : Context):
        layout : UILayout = self.layout

        from .rfpanels.autosave_panel import draw_autosave
        header, panel = layout.panel(idname='autosave_prefs', default_closed=True)
        header.label(text='Auto-Save')
        if panel:
            draw_autosave(self, context, panel)

        from .rfpanels.hotkeys_panel import draw_hotkeys
        header, panel = layout.panel(idname='hotkey_panel_prefs', default_closed=True)
        header.label(text="Hotkeys")
        if panel:
            draw_hotkeys(self, context, panel)

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
            box.label(text="If you encounter lag issues while using a tablet, consider switching")
            box.label(text="to WinTab API in [ Blender Preferences > Input > Tablet > Tablet API ].")
            row = box.row()
            row.alignment = 'RIGHT'
            row.operator('wm.url_open', text='Blender Report').url = 'https://projects.blender.org/blender/blender/issues/144139'
            row.operator('wm.url_open', text='Retopoflow Report').url = 'https://github.com/CGCookie/retopoflow/issues/1574'


def register():
    bpy.utils.register_class(RF_Prefs)

def unregister():
    bpy.utils.unregister_class(RF_Prefs)
