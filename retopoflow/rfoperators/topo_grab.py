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
import json
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
from ..common.raycast import raycast_point_valid_sources, vec_right

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import Frame
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.colors import Color4


"""

Topo Grab shifts selected topology around.

Idea:

- perimeter and interior verts are handled separately
- interior verts move around just like regular grab
- perimeter verts **slide** along outgoing edges
- if perimeter verts are moved "far enough", then a topo shift happens
    - the selected topo is separated, shifted, and glued back in
    - but the surrounding geo is changed depending on the shift
    - if one of both verts of perimeter edge moves along unselected edge, then that face is




given offset, find best slide percentage (largest normalized dot product of all linked edges)
find best perimeter or exterior edge, not interior (largest absolute normalized dot product)

if still sliding (has not slid far enough to shift, ex: percentage < 0.5), then
for each perimeter vert: slide vert along best edge by best slide percentage

however, if shifting, then separate entire patch and for each perimeter vert...
- if vert's best edge is perimeter, merge with other vert
- if vert's best edge is exterior and dot product of movement is...
    - positive (same direction), delete edge (and adj faces) and merge into next vert
    - negative (opposite direction), add edge
after going through all verts, for each perimeter edge
- if still on boundary, bridge with corresponding edge

use spring-mass to move interior verts and relax perimeter


"""


def pretty_print(o):
    def convert(o):
        if type(o) is dict:
            return { str(k): convert(v) for (k,v) in o.items() }
        if type(o) is list:
            return [ convert(i) for i in o ]
        if type(o) is tuple:
            return [ convert(i) for i in o ]
        if type(o) is Vector:
            return f'Vector({o.x:0.3f}, {o.y:0.3f}, {o.z:0.3f})'
        return str(o)
    print(json.dumps(convert(o), indent=2))



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

def find_duplicate(bmv0, other_bmvs, *, threshold=0.0001) -> BMVert | None:
    if not other_bmvs: return None
    bmv1 = min(other_bmvs, key=lambda bmv1:(bmv0.co - bmv1.co).length)
    return bmv1 if (bmv0.co - bmv1.co).length <= threshold else None


class RFOperator_TopoGrab(RFOperator):
    bl_idname = 'retopoflow.topograb'
    bl_label = 'Topo Grab'
    bl_description = 'Topologically grabs (translates) the selected patch'
    bl_space_type = 'VIEW_3d'
    bl_region_type = 'TOOLS'
    bl_options = { 'REGISTER', 'UNDO' }

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'G', 'value': 'PRESS', 'alt': True}, None),
    ]
    rf_status = ['LMB: Commit', 'MMB: (nothing)', 'RMB: Cancel']


    offset: bpy.props.FloatVectorProperty(
        name='Offset',
        description='...',
        default=(0.0, 0.0),
        size=2,
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
        if not perimeter: return  # should never happen
        self.count : int = len(perimeter)

        # before ripping patch away, determine which directions each perimeter vert can go
        perimeter_bmverts = { bmv for bme in perimeter for bmv in bme.verts }
        self.slides = {}
        for bmv in perimeter_bmverts:
            has_interior = any(
                all(bmf in self.bmfaces for bmf in bme.link_faces)
                for bme in bmv.link_edges
            )
            self.slides[bmv] = []
            bmes = set(bmv.link_edges)
            bme = bmes.pop()
            seen = set()
            while bme:
                is_interior = all(bmf in self.bmfaces for bmf in bme.link_faces)
                if not is_interior:
                    bmv_to = bme_other_bmv(bme, bmv)
                    vec_to = bmv_to.co - bmv.co
                    is_perimeter = not is_interior and any(bmf in self.bmfaces for bmf in bme.link_faces)
                    self.slides[bmv].append({
                        'co_from': Vector(bmv.co),
                        'co_to':   Vector(bmv_to.co),
                        'vec_to':  vec_to,
                        'len_to':  vec_to.length,
                        'dir_to':  vec_to.normalized(),
                        'perimeter':  is_perimeter,
                        'has_interior': has_interior,
                        'can_negate': not has_interior and not is_perimeter,
                    })
                bmf = next(iter(set(bme.link_faces) - seen), None)
                seen.add(bmf)
                bme = next(iter(set(bmf.edges) & bmes), None)
                bmes.discard(bme)
        print(self.slides)

        # rip the patch away!
        res = bmesh.ops.split_edges(self.bm, edges=perimeter)
        all_bmedges = set(res['edges'])

        bmesh.update_edit_mesh(self.em)
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, self.bmfaces)
        bmops.select_iter(self.bm, all_bmedges)
        bmops.flush_selection(self.bm, self.em)

        # grab inner perimeter and outer perimiter of ripped faces again, because there are new edges
        self.perimeter0 = get_perimeter_bmedges(self.bmfaces)
        self.perimeter0_bmverts = [ bmes_shared_bmv(bme0, bme1) for (bme0, bme1) in iter_pairs(self.perimeter0, True) ]
        # rotate perimeter so first entry in inner perimeter has match in outer perimeter
        perimeter1 = all_bmedges - set(self.perimeter0)
        perimeter1_bmverts = { bmv for bme in perimeter1 for bmv in bme.verts }
        if len(perimeter1_bmverts) < len(self.perimeter0_bmverts):
            # special case where patch is along boundary or is entire island
            perimeter1_bmverts = [
                find_duplicate(bmv0, perimeter1_bmverts)
                for bmv0 in self.perimeter0_bmverts
            ]
            new_bmverts = [bmv is None for bmv in perimeter1_bmverts]
            self.perimeter1_bmverts = [
                bmv1 if bmv1 is not None else self.bm.verts.new(bmv0.co)
                for (bmv0, bmv1) in zip(self.perimeter0_bmverts, perimeter1_bmverts)
            ]
            self.perimeter1 = []
            for (i0, bmv0) in enumerate(self.perimeter1_bmverts):
                i1 = (i0 + 1) % self.count
                bmv1 = self.perimeter1_bmverts[i1]
                if new_bmverts[i0] or new_bmverts[i1]:
                    self.bm.edges.new((bmv0, bmv1))
                self.perimeter1.append( bmvs_shared_bme(bmv0, bmv1) )
            print(self.perimeter1 )
        else:
            self.perimeter1_bmverts = [
                find_duplicate(bmv0, perimeter1_bmverts)
                for bmv0 in self.perimeter0_bmverts
            ]
            self.perimeter1 = [
                bmvs_shared_bme(bmv0, bmv1) for (bmv0, bmv1) in iter_pairs(self.perimeter1_bmverts, True)
            ]
        self.perimeter1 = self.perimeter1[1:] + self.perimeter1[:1]

        self.all_bmverts = { bmv for bmf in self.bmfaces for bmv in bmf.verts }
        self.perimeter_bmverts = set(self.perimeter0_bmverts)
        self.inner_bmverts = self.all_bmverts - self.perimeter_bmverts
        self.outer_bmverts = { bmv for bme in self.perimeter1 for bmv in bme.verts }

        self.all_bmedges = { bme for bmf in self.bmfaces for bme in bmf.edges }
        self.perimeter_bmedges = set(self.perimeter0)
        self.inner_bmedges = self.all_bmedges - self.perimeter_bmedges

        self.corresponding = {
            bmv: min(self.outer_bmverts, key=lambda bmvo:(bmv.co-bmvo.co).length_squared)
            for bmv in self.perimeter_bmverts
        }
        for (bmv0, bmv1) in list(self.corresponding.items()):
            self.corresponding[bmv1] = bmv0
        nslides = {}
        for bmv,slides in self.slides.items():
            if bmv in self.perimeter_bmverts:
                nslides[bmv] = slides
            else:
                nslides[self.corresponding[bmv]] = slides
        self.slides = nslides
        pretty_print(self.slides)

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
        # Nothing reads these after finish() but it can crash if released by Blender after the bmesh is gone.
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
        self.corresponding = {}
        self.slides = {}

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

        self.offset = self.mouse - self.mouse_start

        iterations = self.iterations
        spring_k = self.spring_k
        spring_c = self.spring_c
        TIMESTEP = 0.02

        for bmv in self.all_bmverts:
            co = self.M @ self.original_positions[bmv]
            pt = location_3d_to_region_2d(context.region, context.region_data, co) + Vector(self.offset)
            co = raycast_point_valid_sources(context, pt)
            if not co: continue
            bmv.co = self.Mi @ co

        print()
        best_slides = {}
        for (bmv, slides) in self.slides.items():
            best_slide, best_percent, best_percent_test = None, None, None
            for slide in slides:
                dir_new = (bmv.co - slide['co_from']).normalized()
                p = slide['dir_to'].dot(dir_new)
                if best_slide is None:
                    best_slide, best_percent, best_percent_test = slide, p, p
                    if slide['can_negate']: best_percent_test = abs(p)
                elif slide['perimeter']:
                    if p > best_percent_test:
                        best_slide, best_percent, best_percent_test = slide, p, p
                elif slide['can_negate']:
                    if abs(p) > best_percent_test:
                        best_slide, best_percent, best_percent_test = slide, p, p
                        if slide['can_negate']: best_percent_test = abs(p)
                else:
                    if p > best_percent_test:
                        best_slide, best_percent, best_percent_test = slide, p, p
                        if slide['can_negate']: best_percent_test = abs(p)
            best_slides[bmv] = best_slide
            per = best_percent
            print(bmv, best_slides[bmv]['dir_to'], per)
        #pretty_print(best_slides)
        slide_percents = [
            slide['dir_to'].dot(bmv.co - slide['co_from']) / slide['len_to']
            for (bmv, slide) in best_slides.items()
        ]
        best_slide_percent = max(slide_percents)
        # print(best_slide_percent, slide_percents)

        for (bmv, slide) in best_slides.items():
            sign = 1 if slide['dir_to'].dot(bmv.co - slide['co_from']) > 0 else -1
            bmv.co = slide['co_from'] + (sign * best_slide_percent) * slide['vec_to']

        # print(best_slides)

        # self.merging = {
        #     bmv0: self.perimeter1_bmverts[(i + offset) % self.count]
        #     for (i, bmv0) in enumerate(self.perimeter0_bmverts)
        # }

        # # set up mass-spring sim based on distances from perimeter (push verts towards original size)
        # springs = [
        #     (bmv, bmv1, (self.original_positions[bmv] - self.original_positions[bmv0]).length)
        #     for bmv in self.inner_bmverts
        #     for (bmv0, bmv1) in self.merging.items()
        # ]


        # # initially rotate points roughly to where they go
        # frame = self.frame.clone()
        # frame.rotate_about_z(delta_angle)
        # for (bmv, co) in self.original_positions_local.items():
        #     bmv.co = frame.l2w_point(co)

        # # move perimiter bmverts to the final position
        # for bmv0, bmv1 in self.merging.items():
        #     bmv0.co = bmv1.co

        # # now run the mass-spring simulation
        # vels = {
        #     bmv: Vector((0, 0, 0)) for bmv in self.inner_bmverts
        # }
        # for _ in range(iterations):
        #     forces = {
        #         bmv: Vector((0,0,0)) for bmv in self.inner_bmverts
        #     }
        #     for (bmv0, bmo1, length) in springs:
        #         p0 = bmv0.co
        #         p1 = bmo1.co if type(bmo1) is BMVert else bmf_midpoint(bmo1)
        #         vdiff = p1 - p0
        #         l = vdiff.length
        #         if l == 0: continue
        #         ddiff = vdiff / l
        #         f = ddiff * (length - l)
        #         if bmv0 in self.inner_bmverts:
        #             forces[bmv0] -= spring_k * f
        #         if bmo1 in self.inner_bmverts:
        #             forces[bmo1] += spring_k * f
        #     for (bmv, f) in forces.items():
        #         p = bmv.co + TIMESTEP * vels[bmv]
        #         bmv.co = self.Mi @ nearest_point_valid_sources(context, self.M @ p)
        #         vels[bmv] = TIMESTEP * forces[bmv] + (1 - spring_c) * vels[bmv]

        bmesh.update_edit_mesh(self.em)

        return {'RUNNING_MODAL'}

    def draw_postpixel(self, context):
        with Drawing.draw(context, CC_2D_LINES) as draw:
            draw.color(Color4((1,1,1,1)))
            draw.line_width(1)
            draw.stipple(pattern=[5,5], offset=0, color=Color4((1,1,1,0)))
            draw.vertex(self.patch_center).vertex(self.patch_center + Vector(self.offset))
