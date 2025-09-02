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

import bpy
import re

from ..common.operator import create_operator

def key_type(k): return re.sub(r'(ctrl|shift|alt|oskey)\+', '', k, flags=re.IGNORECASE)
def ctrl(k):     return 1 if 'ctrl+'  in k.lower() else 0
def shift(k):    return 1 if 'shift+' in k.lower() else 0
def alt(k):      return 1 if 'alt+'   in k.lower() else 0
def oskey(k):    return 1 if 'oskey+' in k.lower() else 0

def create_launch_browser_operator(name, idname, label, url, *, rf_keymaps=None, rf_keymap_press=None, **kwargs):
    help = {
        'retopoflow.polypen': 'https://docs.retopoflow.com/v4/polypen.html',
        'retopoflow.polystrips': 'https://docs.retopoflow.com/v4/polystrips.html',
        'retopoflow.strokes': 'https://docs.retopoflow.com/v4/strokes.html',
        'retopoflow.contours': 'https://docs.retopoflow.com/v4/contours.html',
        'retopoflow.tweak': 'https://docs.retopoflow.com/v4/tweak.html',
        'retopoflow.relax': 'https://docs.retopoflow.com/v4/relax.html',
    }

    def launch(context):
        from ..rfcore import RFCore
        active_tool = RFCore.selected_RFTool_idname
        if name == 'RFOperator_Launch_Help' and 'retopoflow' in active_tool:
            bpy.ops.wm.url_open(url=help[active_tool])
        else:
            bpy.ops.wm.url_open(url=url)
        return {'FINISHED'}

    op = create_operator(name, idname, label, fn_exec=launch, **kwargs)

    op.rf_keymaps = rf_keymaps or []
    if rf_keymap_press:
        op.rf_keymaps.append((
            idname, {
                'type':  key_type(rf_keymap_press),
                'value': 'PRESS',
                'ctrl':  ctrl(rf_keymap_press),
                'shift': shift(rf_keymap_press),
                'alt':   alt(rf_keymap_press),
                'oskey': oskey(rf_keymap_press),
            },
            None,
        ))

    return op

RFOperator_Launch_NewIssue = create_launch_browser_operator(
    'RFOperator_Launch_NewIssue',
    'retopoflow.launch_newissue',
    'Report a new issue with RetopoFlow',
    'https://github.com/CGCookie/retopoflow/issues/new/choose',
    rf_keymap_press='F2',
)

RFOperator_Launch_Help = create_launch_browser_operator(
    'RFOperator_Launch_Help',
    'retopoflow.launch_help',
    'Launch Help Docs',
    'https://docs.retopoflow.com/index.html',
    rf_keymap_press='F1',
)