'''
Copyright (C) 2025 CG Cookie
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

from ..common.operator import RFOperator
from ...addon_common.common.useractions import blenderop_to_kmis
from ..common.interface import show_message

class RFOperator_MaximizeWatcher(RFOperator):
    bl_idname = 'retopoflow.maximizewatcher'
    bl_label = 'Retopoflow: Maximize Watcher'
    bl_description = 'Watches for Maximize Area when Retopoflow tool is selected'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = {'INTERNAL'}

    rf_keymaps = [
        ('retopoflow.maximizewatcher', {
            'type':  kmi.type,
            'value': kmi.value,
            'ctrl':  kmi.ctrl_ui,
            'alt':   kmi.alt_ui,
            'shift': kmi.shift_ui,
            'oskey': kmi.oskey_ui,
        }, None)
        for kmi in blenderop_to_kmis('Screen | screen.screen_full_area')
    ]

    def init(self, context, event):
        print(f'ATTEMPTING TO FULLSCREEN')
        show_message(
            message="Maximizing an area with a Retopoflow tool selected can cause Blender to crash on some machines.\n" \
                    "While we work on a fix, we have temporarily disabled the Maximize Area operator to prevent loss of work.\n" \
                    "For now, please switch to another tool (like Move) first, maximize the area, then switch back to Retopoflow.", 
            title="Retopoflow", 
            icon="ERROR"
        )

    def update(self, context, event):
        return {'FINISHED'}
