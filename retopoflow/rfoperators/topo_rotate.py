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

import math
import time

import bmesh
import bpy
from bmesh.types import BMVert, BMEdge, BMFace
from mathutils import Vector

from ..common.bmesh import (
    bme_other_bmv, bmes_shared_bmv,
    bmf_midpoint,
    get_bmesh_emesh,
)
from ..common.maths import Point
from ..common.operator import RFOperator_Execute
from ..common.raycast import nearest_point_valid_sources, vec_right

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import Frame
from ...addon_common.common.utils import iter_pairs


def is_perimeter(bme, bmfaces):
    bmfs = list(bme.link_faces)
    if len(bmfs) == 1: return True
    if len([bmf for bmf in bmfs if bmf in bmfaces]) == 1: return True
    return False

def compute_average_normal(bmverts : list[BMVert]) -> Vector:
    normal : Vector = sum(( bmv.normal for bmv in bmverts ), Vector((0,0,0)))
    return normal.normalized()

def compute_perimeter_normal(bmverts : list[BMVert]) -> Vector:
    center = Vector(Point.average(bmv.co for bmv in bmverts))
    normal : Vector = sum(
        (
            (center - bmv0.co).cross(bmv1.co - bmv0.co).normalized() * (bmv1.co - bmv0.co).length
            for (bmv0, bmv1) in iter_pairs(bmverts, True)
        ),
        Vector((0,0,0))
    )
    return normal.normalized()

def get_perimeter_bmedges(bmfaces):
    bmedges = { bme for bmf in bmfaces for bme in bmf.edges }
    perimeter_bmedges = { bme for bme in bmedges if is_perimeter(bme, bmfaces) }

    perimeter = [ next(iter(perimeter_bmedges)) ]
    bmv = perimeter[-1].verts[0]
    perimeter_bmverts = [bmv]

    while True:
        potentials = {
            bme
            for bme in bmv.link_edges
            if bme in perimeter_bmedges and bme != perimeter[-1]
        }
        if len(potentials) != 1:
            print(f'{potentials=} but len not 1')
            return None
        bme = next(iter(potentials))
        bmv = bme_other_bmv(bme, bmv)
        if bme == perimeter[0]:
            break
        perimeter.append(bme)
        perimeter_bmverts.append(bmv)

    n0 = compute_average_normal(perimeter_bmverts)
    n1 = compute_perimeter_normal(perimeter_bmverts)
    if n0.dot(n1) < 0:
        perimeter.reverse()

    return perimeter

def same_bmedges(bme0, bme1):
    THRESHOLD = 0.000001
    bmv00, bmv01 = bme0.verts
    bmv10, bmv11 = bme1.verts
    co00, co01 = bmv00.co, bmv01.co
    co10, co11 = bmv10.co, bmv11.co
    if (co00 - co10).length < THRESHOLD and (co01 - co11).length < THRESHOLD: return True
    if (co00 - co11).length < THRESHOLD and (co01 - co10).length < THRESHOLD: return True
    return False

# TODO: turn into propert Operator with redo params!
def rip_rotate_zip(context, ITERATIONS, SPRING_K, SPRING_C, OFFSET, *, undo=False):
    TIMESTEP = 0.02
    MASS = 0.1

    if undo:
        bpy.ops.ed.undo_push(message=f'Rip Rotate Zip commit {time.time()}')

    bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
    M = context.edit_object.matrix_world
    Mi = M.inverted()
    bmfaces = bmops.get_all_selected_bmfaces(bm)

    perimeter = get_perimeter_bmedges(bmfaces)
    if not perimeter: return

    # rip the patch away!
    res = bmesh.ops.split_edges(bm, edges=perimeter)
    all_bmedges = set(res['edges'])

    bmesh.update_edit_mesh(em)
    bmops.deselect_all(bm)
    bmops.select_iter(bm, bmfaces)
    bmops.flush_selection(bm, em)

    perimeter0 = get_perimeter_bmedges(bmfaces)
    if not perimeter0: return
    perimeter1 = all_bmedges - set(perimeter0)
    perimeter1 = [
        next((bme1 for bme1 in perimeter1 if same_bmedges(bme0, bme1)), None)
        for bme0 in perimeter0
    ]
    l = len(perimeter0)

    merging = {}
    for i in range(l):
        i0, i1 = i, (i + 1) % l
        bme0, bme1 = perimeter0[i0], perimeter0[i1]
        bmv0 = bmes_shared_bmv(bme0, bme1)
        i0, i1 = (i + OFFSET) % l, (i + 1 + OFFSET) % l
        bme0, bme1 = perimeter1[i0], perimeter1[i1]

        if bme0 is None or bme1 is None  # <----
            # handle this case!

        bmv1 = bmes_shared_bmv(bme0, bme1)
        merging[bmv0] = bmv1

    all_bmverts = { bmv for bmf in bmfaces for bmv in bmf.verts }
    perimeter_bmverts = { bmv for bme in perimeter0 for bmv in bme.verts }
    inner_bmverts = all_bmverts - perimeter_bmverts

    all_bmedges = { bme for bmf in bmfaces for bme in bmf.edges }
    perimeter_bmedges = perimeter0
    inner_bmedges = all_bmedges - set(perimeter_bmedges)


    # set up mass-spring sim based on distances from perimeter (push verts towards original size)
    springs = []
    for bmv in inner_bmverts:
        for (bmv0, bmv1) in merging.items():
            springs.append( (bmv, bmv1, (bmv.co - bmv0.co).length) )


    # rough xform using rotation only
    angle = 2.0 * math.pi * OFFSET / len(merging)
    o = Point.average(bmv.co for bmv in merging)
    z = compute_average_normal(merging.keys())
    f0 = Frame(o, z=z)
    f1 = f0.clone()
    f1.rotate_about_z(angle)
    for bmv in inner_bmverts:
        bmv.co = f1.l2w_point(f0.w2l_point(bmv.co))

    # move perimiter bmverts to the final position
    for bmv0, bmv1 in merging.items():
        bmv0.co = bmv1.co

    # now run the mass-spring simulation
    vels = {
        bmv: Vector((0, 0, 0)) for bmv in inner_bmverts
    }
    for _ in range(ITERATIONS):
        forces = {
            bmv: Vector((0,0,0)) for bmv in inner_bmverts
        }
        positions = {}
        for bmv0, bmo1, _ in springs:
            if bmv0 not in positions:
                positions[bmv0] = bmv0.co
            if bmo1 not in positions:
                positions[bmo1] = bmo1.co if type(bmo1) is BMVert else bmf_midpoint(bmo1)
        for (bmv0, bmo1, length) in springs:
            p0, p1 = positions[bmv0], positions[bmo1]
            vdiff = p1 - p0
            l = vdiff.length
            if l == 0: continue
            ddiff = vdiff / l
            f = ddiff * (length - l)
            if bmv0 in inner_bmverts:
                forces[bmv0] -= SPRING_K * f
            if bmo1 in inner_bmverts:
                forces[bmo1] += SPRING_K * f
        for (bmv, f) in forces.items():
            p = bmv.co + TIMESTEP * vels[bmv]
            bmv.co = Mi @ nearest_point_valid_sources(context, M @ p)
            vels[bmv] = TIMESTEP * forces[bmv] + (1 - SPRING_C) * vels[bmv]

    # zip the patch back in
    bmesh.ops.weld_verts(bm, targetmap=merging)

    bmesh.update_edit_mesh(em)
    bmops.deselect_all(bm)
    bmops.select_iter(bm, bmfaces)
    bmops.flush_selection(bm, em)



class RFOperator_TopoRotate(RFOperator_Execute):
    bl_idname = 'retopoflow.toporotate'
    bl_label = 'Topo Rotate'
    bl_description = 'Topologically rotates the selected patch'
    bl_space_type = 'VIEW_3d'
    bl_region_type = 'TOOLS'
    bl_options = { 'REGISTER', 'UNDO' }

    rf_keymaps = [
        (bl_idname, {'type': 'R', 'value': 'PRESS', 'alt': True}, None),
    ]
    rf_status = ['LMB: Commit', 'MMB: (nothing)', 'RMD: Cancel']


    offset: bpy.props.IntProperty(
        name='Offset',
        description='Number of edges to offset (positive: clockwise, negative: counter-clockwise)',
        default=1,
    )

    iterations: bpy.props.IntProperty(
        name='Iterations',
        description='Iterations of mass-spring simulation',
        default=1000,
        min=0,
        max=10000,
    )
    spring_k: bpy.props.FloatProperty(
        name='Spring K',
        description='Spring force',
        default=10.0,
        min=0.0,
        max=1000.0,
    )
    spring_c: bpy.props.FloatProperty(
        name='Spring C',
        description='Spring damping constant (0.0 no damping, 1.0 full damping)',
        default=0.95,
        min=0.0,
        max=1.0,
    )


    def execute(self, context):
        rip_rotate_zip(context, self.iterations, self.spring_k, self.spring_c, self.offset)
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, 'offset')
        layout.prop(self, 'iterations')
        layout.prop(self, 'spring_k')
        layout.prop(self, 'spring_c')
