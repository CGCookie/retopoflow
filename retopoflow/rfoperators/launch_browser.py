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
from ..rfglobals import RFGlobals
from ..common.operator import RFRegisterClass


class RFOperator_Launch_Help(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.launch_help"
    bl_label = 'Launch Retopoflow Docs'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    @classmethod
    def poll(self, context):
        from ..rfcore import RFCore
        return RFCore.is_running

    def execute(self, context):
        RFCore = RFGlobals.RFCore_None
        if not RFCore: return {'CANCELLED'}

        active_tool = RFCore.selected_RFTool_idname
        help = {
            'retopoflow.polypen': 'https://docs.retopoflow.com/v4/polypen.html',
            'retopoflow.polystrips': 'https://docs.retopoflow.com/v4/polystrips.html',
            'retopoflow.strokes': 'https://docs.retopoflow.com/v4/strokes.html',
            'retopoflow.contours': 'https://docs.retopoflow.com/v4/contours.html',
            'retopoflow.tweak': 'https://docs.retopoflow.com/v4/tweak.html',
            'retopoflow.relax': 'https://docs.retopoflow.com/v4/relax.html',
        }
        if 'retopoflow' in active_tool:
            bpy.ops.wm.url_open(url=help[active_tool])
        else:
            bpy.ops.wm.url_open(url='https://docs.retopoflow.com/index.html')
        return {'FINISHED'}


class RFOperator_Launch_NewIssue(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.launch_newissue"
    bl_label = 'Report Retopoflow Issue'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    @classmethod
    def poll(self, context):
        RFCore = RFGlobals.RFCore_None
        return RFCore and RFCore.is_running

    def execute(self, context):
        bpy.ops.wm.url_open(url='https://github.com/CGCookie/retopoflow/issues/new/choose')
        return {'FINISHED'}


keymaps = []

def register():
    keyconfigs = bpy.context.window_manager.keyconfigs.addon
    if keyconfigs:
        km = keyconfigs.keymaps.new(name='3D View', space_type='VIEW_3D')
        kmi = km.keymap_items.new('retopoflow.launch_help', 'F1', 'PRESS', ctrl=False, shift=False, alt=False)
        keymaps.append((km, kmi))

        km = keyconfigs.keymaps.new(name='3D View', space_type='VIEW_3D')
        kmi = km.keymap_items.new('retopoflow.launch_newissue', 'F1', 'PRESS', ctrl=False, shift=False, alt=True)
        keymaps.append((km, kmi))

def unregister():
    for km, kmi in keymaps:
        km.keymap_items.remove(kmi)
    keymaps.clear()


# Previous operator was generated to be unique to every tool
r"""
from ..common.operator import create_operator

def key_type(k): return re.sub(r'(ctrl|shift|alt|oskey)\+', '', k, flags=re.IGNORECASE)
def ctrl(k):     return 1 if 'ctrl+'  in k.lower() else 0
def shift(k):    return 1 if 'shift+' in k.lower() else 0
def alt(k):      return 1 if 'alt+'   in k.lower() else 0
def oskey(k):    return 1 if 'oskey+' in k.lower() else 0


def create_launch_browser_operator(name, idname, label, url, *, fn_poll=None, fn_launch=None, rf_keymaps=None, rf_keymap_press=None, **kwargs):
    def launch_browser(context):
        bpy.ops.wm.url_open(url=url)
        return {'FINISHED'}

    if fn_launch == None:
        fn_launch = launch_browser

    op = create_operator(name, idname, label, fn_poll=fn_poll, fn_exec=fn_launch, **kwargs)

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


def poll_report_issue(context):
    from ..preferences import RF_Prefs
    return RF_Prefs.get_prefs(context).enable_issue_hotkey

RFOperator_Launch_NewIssue = create_launch_browser_operator(
    'RFOperator_Launch_NewIssue',
    'retopoflow.launch_newissue',
    'Report a new issue with RetopoFlow',
    'https://github.com/CGCookie/retopoflow/issues/new/choose',
    rf_keymap_press='F2',
    fn_poll=poll_report_issue,
)


def poll_help(context):
    from ..preferences import RF_Prefs
    return RF_Prefs.get_prefs(context).enable_help_hotkey

def launch_help(context):
    RFCore = RFGlobals.RFCore
    if not RFCore: return {'CANCELLED}
    active_tool = RFCore.selected_RFTool_idname
    help = {
        'retopoflow.polypen': 'https://docs.retopoflow.com/v4/polypen.html',
        'retopoflow.polystrips': 'https://docs.retopoflow.com/v4/polystrips.html',
        'retopoflow.strokes': 'https://docs.retopoflow.com/v4/strokes.html',
        'retopoflow.contours': 'https://docs.retopoflow.com/v4/contours.html',
        'retopoflow.tweak': 'https://docs.retopoflow.com/v4/tweak.html',
        'retopoflow.relax': 'https://docs.retopoflow.com/v4/relax.html',
    }
    if 'retopoflow' in active_tool:
        bpy.ops.wm.url_open(url=help[active_tool])
    else:
        bpy.ops.wm.url_open(url='https://docs.retopoflow.com/index.html')
    return {'FINISHED'}

RFOperator_Launch_Help = create_launch_browser_operator(
    'RFOperator_Launch_Help',
    'retopoflow.launch_help',
    'Launch Help Docs',
    'https://docs.retopoflow.com/index.html',
    fn_poll=poll_help,
    fn_launch=launch_help,
    rf_keymap_press='F1',
)
"""