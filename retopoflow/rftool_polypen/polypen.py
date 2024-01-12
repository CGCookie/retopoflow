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
import bmesh
from bmesh.types import BMVert, BMEdge, BMFace

from enum import Enum

from ..rftool_base import RFTool_Base
from ..common.operator import invoke_operator, execute_operator, RFOperator
from ..common.raycast import raycast_mouse_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.reseter import Reseter


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

class PP_Action(Enum):
    NONE = -1
    VERT = 0
    VERT_EDGE = 1
    EDGE_TRIANGLE = 2


class PP_Logic:
    def __init__(self, context, event):
        self.em = context.active_object.data
        self.bm = bmesh.from_edit_mesh(self.em)
        self.layer_sel_vert = self.bm.verts.layers.int.get('rf: select after move')
        self.layer_sel_edge = self.bm.edges.layers.int.get('rf: select after move')
        self.layer_sel_face = self.bm.faces.layers.int.get('rf: select after move')
        self.update_selection = False
        self.get_selection = True
        self.update(context, event)

    def update(self, context, event):
        # update previsualization and commit data structures with mouse position
        # ex: if triangle is selected, determine which edge to split to make quad

        if self.update_selection:
            for bmv in self.bm.verts:
                bmv.select_set(bmv[self.layer_sel_vert] == 1)
                bmv[self.layer_sel_vert] = 0
            for bme in self.bm.edges:
                if bme[self.layer_sel_edge] == 0: continue
                for bmv in bme.verts:
                    bmv.select_set(True)
                bme[self.layer_sel_edge] = 0
            for bmf in self.bm.faces:
                if bmf[self.layer_sel_face] == 0: continue
                for bmv in bmf.verts:
                    bmv.select_set(True)
                bmf[self.layer_sel_face] = 0
            bmops.flush_selection(self.bm, self.em)
            self.get_selection = True
            self.update_selection = False

        if self.get_selection:
            self.selected = bmops.get_all_selected(self.bm)

        # update commit data structure with mouse position
        self.state = PP_Action.NONE
        self.hit = raycast_mouse_valid_sources(context, event)
        if not self.hit: return

        # TODO: update previsualizations

        if len(self.selected[BMVert]) == 0:
            self.state = PP_Action.VERT

        elif len(self.selected[BMVert]) == 1:
            self.state = PP_Action.VERT_EDGE
            self.bmv = next(iter(self.selected[BMVert]), None)

        elif len(self.selected[BMVert]) == 2 and len(self.selected[BMEdge]) == 1:
            self.state = PP_Action.EDGE_TRIANGLE
            self.bme = next(iter(self.selected[BMEdge]), None)

    def draw(self, context):
        # draw previsualization
        pass

    def commit(self, context, event):
        # apply the change

        if self.state == PP_Action.NONE: return

        # make sure artist can see the vert
        bpy.ops.mesh.select_mode(type='VERT', use_extend=True, action='ENABLE')

        select_now = []     # to be selected before move
        select_later = []   # to be selected after move

        match self.state:
            case PP_Action.VERT:
                bmv = self.bm.verts.new(self.hit)
                select_now = [bmv]

            case PP_Action.VERT_EDGE:
                bmv0 = self.bmv
                bmv1 = self.bm.verts.new(self.hit)
                bme = self.bm.edges.new((bmv0, bmv1))
                select_now = [bmv1]
                select_later = [bme]

            case PP_Action.EDGE_TRIANGLE:
                bmv0, bmv1 = self.bme.verts
                bmv = self.bm.verts.new(self.hit)
                bmf = self.bm.faces.new((bmv0,bmv1,bmv))
                select_now = [bmv]
                select_later = [bmf]

            case _:
                assert False, f'Unhandled PolyPen state {self.state}'

        bmops.deselect_all(self.bm)
        for bmelem in select_now:
            bmelem.select_set(True)
        for bmelem in select_later:
            match bmelem:
                case BMVert():
                    bmelem[self.layer_sel_vert] = 1
                case BMEdge():
                    bmelem[self.layer_sel_edge] = 1
                    for bmv in bmelem.verts:
                        bmv[self.layer_sel_vert] = 1
                case BMFace():
                    bmelem[self.layer_sel_face] = 1
                    for bmv in bmelem.verts:
                        bmv[self.layer_sel_vert] = 1
        self.update_selection = bool(select_later)

        bmops.flush_selection(self.bm, self.em)
        bpy.ops.transform.transform('INVOKE_DEFAULT', mode='TRANSLATION', **translate_options)
        # NOTE: the select-later property is _not_ transferred to the vert into which the moved vert is auto-merged...
        #       this is handled if a BMEdge or BMFace is to be selected later, but it is not handled if only a BMVert
        #       is created and then merged into existing geometry


class RETOPOFLOW_OT_PolyPen(RFOperator):
    bl_idname = "retopoflow.polypen"
    bl_label = 'PolyPen'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    @classmethod
    def get_keymap(cls):
        return {'type': 'LEFT_ALT', 'value': 'PRESS'}

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        print(f'STARTING')

        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(text='PolyPen\tInsert')
        self.logic = PP_Logic(context, event)

        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        self.logic.update(context, event)

        if not event.alt:
            print(F'LEAVING')
            context.workspace.status_text_set(None)
            return {'FINISHED'}

        if event.type == 'LEFTMOUSE':
            self.logic.commit(context, event)
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}


class RFTool_PolyPen(RFTool_Base):
    bl_idname = "retopoflow.polypen"
    bl_label = "PolyPen"
    bl_description = "PolyPen"
    bl_icon = "ops.generic.select_circle"
    bl_widget = None

    bl_keymap = (
        (RETOPOFLOW_OT_PolyPen.bl_idname, RETOPOFLOW_OT_PolyPen.get_keymap(), None),
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
