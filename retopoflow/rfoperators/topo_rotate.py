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
from collections.abc import Iterable

import bmesh
import bpy
from bmesh.types import BMVert, BMEdge, BMFace
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d

from ..common.bmesh import (
    bme_other_bmv, bmes_shared_bmv,
    bmvs_shared_bme,
    bmf_midpoint,
    get_bmesh_emesh,
)
from ..common.drawing import (
    Drawing,
    CC_2D_LINES,
)
from ..common.maths import Point
from ..common.operator import RFOperator, RFKeyMaps
from ..common.raycast import nearest_point_valid_sources, vec_right

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import Frame
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.colors import Color4


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

def get_perimeter_bmedges(bmfaces : Iterable[BMFace]) -> list[BMEdge]:
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
            return []
        bme = next(iter(potentials))
        bmv = bme_other_bmv(bme, bmv)
        if bme == perimeter[0]:
            break
        perimeter.append(bme)
        perimeter_bmverts.append(bmv)

    if len(perimeter) != len(perimeter_bmedges): return []

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

def find_duplicate(bmv0, other_bmvs, *, threshold=0.000001) -> BMVert | None:
    if not other_bmvs: return None
    bmv1 = min(other_bmvs, key=lambda bmv1:(bmv0.co - bmv1.co).length)
    return bmv1 if (bmv0.co - bmv1.co).length <= threshold else None


class RFOperator_TopoRotate(RFOperator):
    bl_idname = 'retopoflow.toporotate'
    bl_label = 'Topo Rotate'
    bl_description = 'Topologically rotates the selected patch'
    bl_space_type = 'VIEW_3d'
    bl_region_type = 'TOOLS'
    bl_options = { 'REGISTER', 'UNDO' }

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'R', 'value': 'PRESS', 'alt': True}, None),
    ]
    rf_status = ['LMB: Commit', 'MMB: (nothing)', 'RMB: Cancel']


    offset: bpy.props.IntProperty(
        name='Offset',
        description='Number of edges to offset (positive: clockwise, negative: counter-clockwise)',
        default=0,
    )

    iterations: bpy.props.IntProperty(
        name='Iterations',
        description='Iterations of mass-spring simulation',
        default=100,
        min=0,
        max=10000,
    )
    spring_k: bpy.props.FloatProperty(
        name='Spring K',
        description='Spring force',
        default=5.0,
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

    perimeter0: list[BMEdge]
    perimeter0_bmverts: list[BMVert]
    perimeter1: list[BMEdge]
    perimeter1_bmverts: list[BMVert]
    frame: Frame
    mouse: Vector
    mouse_down: Vector
    patch_center: Vector

    @classmethod
    def can_start(cls, context):
        bm, em = get_bmesh_emesh(context, ensure_lookup_tables=False)
        bmfaces = bmops.get_all_selected_bmfaces(bm)
        if len(bmfaces) <= 1: return False
        perimeter = get_perimeter_bmedges(bmfaces)
        return bool(perimeter)


    def init(self, context, event):
        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        self.M = context.edit_object.matrix_world
        self.Mi = self.M.inverted_safe()
        self.bmfaces : set[BMFace] = bmops.get_all_selected_bmfaces(self.bm)

        perimeter = get_perimeter_bmedges(self.bmfaces)
        if not perimeter: return
        self.count : int = len(perimeter)
        is_boundary = [bme.is_boundary for bme in perimeter]

        # rip the patch away!
        res = bmesh.ops.split_edges(self.bm, edges=perimeter)
        all_bmedges = set(res['edges'])

        bmesh.update_edit_mesh(self.em)
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, self.bmfaces)
        bmops.flush_selection(self.bm, self.em)

        # grab inner perimeter and outer perimiter of ripped faces again, because there are new edges
        self.perimeter0 = get_perimeter_bmedges(self.bmfaces)
        self.perimeter0_bmverts = [ bmes_shared_bmv(bme0, bme1) for (bme0, bme1) in iter_pairs(self.perimeter0, True) ]
        perimeter1 = all_bmedges - set(self.perimeter0)
        perimeter1_bmverts = { bmv for bme in perimeter1 for bmv in bme.verts }
        perimeter1_bmverts = [
            find_duplicate(bmv0, perimeter1_bmverts)
            for bmv0 in self.perimeter0_bmverts
        ]
        self.perimeter1_bmverts = [
            bmv1 if bmv1 is not None else self.bm.verts.new(bmv0.co)
            for (bmv0, bmv1) in zip(self.perimeter0_bmverts, perimeter1_bmverts)
        ]
        self.perimeter1 = []
        for (i0, bmv0) in enumerate(self.perimeter1_bmverts):
            i1 = (i0 + 1) % self.count
            bmv1 = self.perimeter1_bmverts[i1]
            bme = next(iter(set(bmv0.link_edges) & set(bmv1.link_edges)), None)
            if not bme: bme = self.bm.edges.new((bmv0, bmv1))
            self.perimeter1.append(bme)
        self.perimeter1 = self.perimeter1[1:] + self.perimeter1[:1]

        self.all_bmverts = { bmv for bmf in self.bmfaces for bmv in bmf.verts }
        self.perimeter_bmverts = set(self.perimeter0_bmverts)
        self.inner_bmverts = self.all_bmverts - self.perimeter_bmverts
        self.outer_bmverts = { bmv for bme in self.perimeter1 for bmv in bme.verts }

        self.all_bmedges = { bme for bmf in self.bmfaces for bme in bmf.edges }
        self.perimeter_bmedges = set(self.perimeter0)
        self.inner_bmedges = self.all_bmedges - self.perimeter_bmedges

        o = Point.average(bmv.co for bmv in self.perimeter0_bmverts)
        z = compute_average_normal(self.perimeter0_bmverts)
        self.frame = Frame(o, z=z)
        self.original_positions = {
            bmv: Vector(bmv.co)
            for bmv in self.all_bmverts
        }
        self.original_positions_local = {
            bmv: self.frame.w2l_point(bmv.co)
            for bmv in self.all_bmverts
        }

        pts = [
            pt
            for bmv in self.all_bmverts
            if (pt := location_3d_to_region_2d(context.region, context.region_data, self.M @ bmv.co)) is not None
        ]
        self.patch_center = sum(pts, Vector((0,0))) / len(pts)
        self.mouse_start = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse_angle = math.atan2(self.mouse_start.y - self.patch_center.y, self.mouse_start.x - self.patch_center.x)

    def finish(self, context):
        # Drop every BMesh reference while the bmesh is still alive.
        self.bm, self.em = None, None
        self.bmfaces = set()
        self.all_bmverts = set()
        self.all_bmedges = set()
        self.inner_bmverts = set()
        self.inner_bmedges = set()
        self.outer_bmverts = set()
        self.perimeter0 = []
        self.perimeter1 = []
        self.perimeter0_bmverts = []
        self.perimeter1_bmverts = []
        self.perimeter_bmverts = set()
        self.perimeter_bmedges = set()
        self.original_positions = {}
        self.original_positions_local = {}
        self.merging = {}

    def revert_to_original(self):
        # undo everything
        self.merging = {
            bmv0: bmv1
            for (bmv0, bmv1) in zip(self.perimeter0_bmverts, self.perimeter1_bmverts)
        }
        for bmv in self.all_bmverts:
            bmv.co = self.original_positions[bmv]

    def update(self, context, event):
        cancelled = event.type in {'ESC', 'RIGHTMOUSE'}
        committed = event.type in {'ENTER', 'LEFTMOUSE'}
        if cancelled or committed:
            if cancelled: self.revert_to_original()

            # zip the patch back in
            bmesh.ops.weld_verts(self.bm, targetmap=self.merging)

            bmesh.update_edit_mesh(self.em)
            bmops.deselect_all(self.bm)
            bmops.select_iter(self.bm, self.bmfaces)
            bmops.flush_selection(self.bm, self.em)
            return {'FINISHED'} if committed else {'CANCELLED'}

        if event.type != 'MOUSEMOVE': return {'RUNNING_MODAL'}

        context.area.tag_redraw()
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        angle = math.atan2(self.mouse.y - self.patch_center.y, self.mouse.x - self.patch_center.x)
        delta_angle = self.mouse_angle - angle
        offset = round(delta_angle / (2.0 * math.pi) * self.count)
        # if offset == self.offset:
        #     return {'RUNNING_MODAL'}

        self.offset = offset
        iterations = self.iterations
        spring_k = self.spring_k
        spring_c = self.spring_c
        TIMESTEP = 0.02

        self.merging = {
            bmv0: self.perimeter1_bmverts[(i + offset) % self.count]
            for (i, bmv0) in enumerate(self.perimeter0_bmverts)
        }

        # set up mass-spring sim based on distances from perimeter (push verts towards original size)
        springs = [
            (bmv, bmv1, (self.original_positions[bmv] - self.original_positions[bmv0]).length)
            for bmv in self.inner_bmverts
            for (bmv0, bmv1) in self.merging.items()
        ]


        # initially rotate points roughly to where they go
        frame = self.frame.clone()
        frame.rotate_about_z(delta_angle)
        for (bmv, co) in self.original_positions_local.items():
            bmv.co = frame.l2w_point(co)

        # move perimiter bmverts to the final position
        for bmv0, bmv1 in self.merging.items():
            bmv0.co = bmv1.co

        # now run the mass-spring simulation
        vels = {
            bmv: Vector((0, 0, 0)) for bmv in self.inner_bmverts
        }
        for _ in range(iterations):
            forces = {
                bmv: Vector((0,0,0)) for bmv in self.inner_bmverts
            }
            for (bmv0, bmo1, length) in springs:
                p0 = bmv0.co
                p1 = bmo1.co if type(bmo1) is BMVert else bmf_midpoint(bmo1)
                vdiff = p1 - p0
                l = vdiff.length
                if l == 0: continue
                ddiff = vdiff / l
                f = ddiff * (length - l)
                if bmv0 in self.inner_bmverts:
                    forces[bmv0] -= spring_k * f
                if bmo1 in self.inner_bmverts:
                    forces[bmo1] += spring_k * f
            for (bmv, f) in forces.items():
                p = bmv.co + TIMESTEP * vels[bmv]
                if snapped := nearest_point_valid_sources(context, self.M @ p, respect_clip_planes=True):
                    bmv.co = self.Mi @ snapped
                vels[bmv] = TIMESTEP * forces[bmv] + (1 - spring_c) * vels[bmv]

        bmesh.update_edit_mesh(self.em)

        return {'RUNNING_MODAL'}

    def draw_postpixel(self, context):
        with Drawing.draw(context, CC_2D_LINES) as draw:
            draw.color(Color4((1,1,1,1)))
            draw.line_width(1)
            draw.stipple(pattern=[5,5], offset=0, color=Color4((1,1,1,0)))
            draw.vertex(self.patch_center).vertex(self.mouse)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, 'offset')
        layout.prop(self, 'iterations')
        layout.prop(self, 'spring_k')
        layout.prop(self, 'spring_c')
