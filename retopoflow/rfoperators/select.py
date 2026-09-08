'''
Copyright (C) 2026 CG Cookie
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
from bpy.types import Context, Event

from ..rfglobals import RFGlobals
from ..preferences import RF_Prefs
from ..common.selection import hovered_bmelem
from ..common.bmesh import get_bmesh_emesh, NearestBMVert, NearestBMEdge, NearestBMFace
from ..common.operator import RFRegisterClass, RFKeyMaps
from ..common.bpy_helper import BPY_OP_RETURN
from ...addon_common.common import bmesh_ops as bmops

DEBUG = False


class RFOperator_ClickSelect(RFRegisterClass, bpy.types.Operator):
    ''' Clears the selection on a click that lands further than the tweaking Distance from any
    geometry, so click-deselect and drag-grab have the same radius. '''

    bl_idname : str = 'retopoflow.click_select'
    bl_label : str = 'Click Deselect'
    bl_description : str = 'Clear the selection when a click lands further than the tweaking distance from any geometry'
    bl_options : set[str] = {'INTERNAL'}

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK'}, None),
    ]

    @classmethod
    def poll(cls, context : Context) -> bool:
        RFCore = RFGlobals.RFCore_None
        if not RFCore or not RFCore.is_running: return False
        if not context.edit_object or context.edit_object.type != 'MESH': return False
        return True

    def invoke(self, context : Context, event : Event) -> BPY_OP_RETURN:
        distance2d = RF_Prefs.get_prefs(context).tweaking_distance
        try:
            bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
            M = context.edit_object.matrix_world
            Mi = M.inverted_safe()
            bmelem, co = hovered_bmelem(
                context, event, distance2d,
                NearestBMVert(bm, M, Mi, ensure_lookup_tables=False),
                NearestBMEdge(bm, M, Mi, ensure_lookup_tables=False),
                NearestBMFace(bm, M, Mi, ensure_lookup_tables=False),
            )
        except Exception as e:
            print(f'RFOperator_ClickSelect: caught Exception in hover pick: {e}')
            return {'PASS_THROUGH'}
        if DEBUG: print(f'click_select: {bmelem=} {co=}')

        # no source hit means nothing to measure against, which also keeps target geometry past
        # the source silhouette clickable
        if co is None: return {'PASS_THROUGH'}
        # something in reach, so Blender's own click select handles it
        if bmelem is not None: return {'PASS_THROUGH'}
        if not em.total_vert_sel: return {'PASS_THROUGH'}
        bmops.deselect_all(bm)
        bmops.flush_selection(bm, em)
        bpy.ops.ed.undo_push(message='Deselect')
        if context.area: context.area.tag_redraw()
        return {'FINISHED'}
