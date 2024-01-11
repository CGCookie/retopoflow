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

import numpy as np
import bpy
import bmesh
from bmesh.types import BMVert, BMEdge, BMFace

from ..rftool_base import RFTool_Base
from ..common.operator import invoke_operator, execute_operator, operators
from ..common.raycast import raycast_mouse_valid_sources
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.blender_cursors import Cursors


visualizing = False
reseter = Reseter()
translate_options = {
    'snap': True,
    'use_snap_project': True,
    'use_snap_self': False, # True,
    'use_snap_edit': False, # True,
    'use_snap_nonedit': True,
    'use_snap_selectable': True,
    'snap_elements': {'FACE_PROJECT', 'FACE_NEAREST'}, #, 'VERTEX'},
    'snap_target': 'CLOSEST',
    # 'release_confirm': True,
}


def get_all_selected(bm):
    return {
        BMVert: get_all_selected_bmverts(bm),
        BMEdge: get_all_selected_bmedges(bm),
        BMFace: get_all_selected_bmfaces(bm),
    }

def get_all_selected_bmverts(bm):
    return { bmv for bmv in bm.verts if bmv.select and not bmv.hide }
def get_all_selected_bmedges(bm):
    return { bme for bme in bm.edges if bme.select and not bme.hide }
def get_all_selected_bmfaces(bm):
    return { bmf for bmf in bm.faces if bmf.select and not bmf.hide }

def deselect_all(bm):
    for bmv in bm.verts: bmv.select_set(False)

def flush_selection(bm, emesh):
    bm.select_flush(True)
    bm.select_flush(False)
    bmesh.update_edit_mesh(emesh)



class RETOPOFLOW_OT_PolyPen(bpy.types.Operator):
    bl_idname = f"retopoflow.polypen"
    bl_label = f'PolyPen'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        print(f'STARTING')

        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(text='PolyPen\tInsert')

        self._select_next = False

        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if self._select_next:
            emesh = context.active_object.data
            bm = bmesh.from_edit_mesh(emesh)
            sellayer = bm.verts.layers.int.get('rf: select after move')
            for bmv in bm.verts:
                if bmv[sellayer] == 0: continue
                bmv.select_set(True)
                bmv[sellayer] = 0
            flush_selection(bm, emesh)
            self._select_next = False

        if not event.alt:
            print(F'LEAVING')
            context.workspace.status_text_set(None)
            return {'FINISHED'}

        if event.type == 'LEFTMOUSE':
            self.insert(context, event)
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    def insert(self, context, event):
        global visualizing
        print('INSERT!')

        hit = raycast_mouse_valid_sources(context, event)
        if not hit: return

        # make sure artist can see the vert
        bpy.ops.mesh.select_mode(type='VERT', use_extend=True, action='ENABLE')

        emesh = context.active_object.data
        bm = bmesh.from_edit_mesh(emesh)
        selected = get_all_selected(bm)
        sellayer = bm.verts.layers.int.get('rf: select after move')

        # print(selected)
        nactive = None
        nselected = set()
        self._select_next = False

        if len(selected[BMVert]) == 1:
            bmv0 = selected[BMVert].pop()
            bmv = bm.verts.new(hit)
            bme = bm.edges.new((bmv0, bmv))

            nactive = bmv
            nselected.add(bmv)
            for bme_v in bme.verts:
                bme_v[sellayer] = 1
            self._select_next = True

        elif len(selected[BMVert]) == 2 and len(selected[BMEdge]) == 1:
            bmv0,bmv1 = selected[BMEdge].pop().verts
            bmv = bm.verts.new(hit)
            bmf = bm.faces.new((bmv0,bmv1,bmv))

            nactive = bmv
            nselected.add(bmv)
            for bmf_v in bmf.verts:
                bmf_v[sellayer] = 1
            self._select_next = True

        deselect_all(bm)
        for bmelem in nselected:
            bmelem.select_set(True)
        flush_selection(bm, emesh)

        visualizing = False

        bpy.ops.transform.transform('INVOKE_DEFAULT', mode='TRANSLATION', **translate_options)

operators.append(RETOPOFLOW_OT_PolyPen)



class RFTool_PolyPen(RFTool_Base):
    bl_idname = "retopoflow.polypen"
    bl_label = "PolyPen"
    bl_description = "PolyPen"
    bl_icon = "ops.generic.select_circle"
    bl_widget = None

    bl_keymap = (
        ('retopoflow.polypen', {'type': 'LEFT_ALT', 'value': 'PRESS'}, None),
        # (pp_insert.bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS', 'alt': True}, None),
        # (pp_mousemove.bl_idname, {'type': 'MOUSEMOVE', 'value': 'NOTHING'}, None),
        # (pp_mousemove.bl_idname, {'type': 'MOUSEMOVE', 'value': 'NOTHING', 'alt': True}, None),
        # (pp_mousemove.bl_idname, {'type': 'LEFT_ALT', 'value': 'PRESS'}, None),
        # (pp_mousemove.bl_idname, {'type': 'LEFT_ALT', 'value': 'RELEASE'}, None),
        # ('transform.translate', {'type': 'LEFTMOUSE', 'value': 'CLICK_DRAG'}, {'properties':list(translate_options.items())}),
    )

    @classmethod
    def activate(cls, context):
        reseter['context.scene.tool_settings.use_mesh_automerge'] = True
        reseter['context.scene.tool_settings.double_threshold'] = 0.01
        # reseter['context.scene.tool_settings.snap_elements_base'] = {'VERTEX'}
        reseter['context.scene.tool_settings.snap_elements_individual'] = {'FACE_PROJECT', 'FACE_NEAREST'}

    @classmethod
    def deactivate(cls, context):
        reseter.reset()
