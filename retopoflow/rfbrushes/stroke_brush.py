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
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from ..rftool_base import RFTool_Base
from ..rfbrush_base import RFBrush_Base
from ..common.bmesh import get_bmesh_emesh, nearest_bmv_world, nearest_bme_world, NearestBMVert, NearestBMEdge, NearestBMFace
from ..common.bmesh_maths import is_bmvert_hidden
from ..common.drawing import (
    Drawing,
    CC_2D_POINTS,
    CC_2D_LINES,
    CC_2D_LINE_STRIP,
    CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES,
    CC_2D_TRIANGLE_FAN,
    CC_3D_TRIANGLES,
)
from ..common.icons import get_path_to_blender_icon
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, size2D_to_size, vec_forward, mouse_from_event
from ..common.maths import view_forward_direction, lerp, bvec_point_to_bvec4
from ..common.operator import (
    invoke_operator, execute_operator,
    RFOperator, RFRegisterClass,
    chain_rf_keymaps, wrap_property,
)
from ..common.easing import CubicEaseOut
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, mouse_from_event, nearest_point_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common import gpustate
from ...addon_common.common.blender import event_modifier_check
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.maths import Color, Frame
from ...addon_common.common.maths import clamp, Direction, Vec, Point, Point2D, Vec2D, sign_threshold, all_combinations, closest_point_segment
from ...addon_common.common.timerhandler import TimerHandler
from ...addon_common.common.utils import iter_pairs

import math
from time import time
from itertools import chain


#########################################################
# TODO: This RFBrush is a mess!  rewrite using states?
#########################################################

def filter_bmvs(bmvs):
    return [ bmv for bmv in bmvs if bmv.is_boundary or bmv.is_wire ]

def create_stroke_brush(idname, label, *, smoothing=0.5, snap=(True,False,False), radius=50, draw_leftright=False):
    snap_verts, snap_edges, snap_faces = snap
    snap_any = snap_verts or snap_edges or snap_faces
    if snap_edges:
        print(f'RFBrush_Stroke Warning')
        print(f'    NOT HANDLING SNAPPED EDGES IN STROKE BRUSH, YET!')

    class RFBrush_Stroke(RFBrush_Base):
        # brush settings
        stroke_radius = radius

        snap_distance  = 10  # pixel distance when to consider snapping to vert or stroke end (cycle) or mirrored vert
        far_distance   = 20  # mouse must move this far away from stroke start to start considering cycle

        # brush visualization settings
        outer_color         = Color((1, 1, 1, 0.75))
        below_alpha         = Color((1, 1, 1, 0.25))
        inner_color         = Color((1, 1, 1, 0.10))
        miss_color          = Color((1, 0, 0, 1.00))
        snap_color          = Color((1, 1, 0, 1.00))
        cycle_color         = Color((1, 1, 0, 1.00))
        stroke_color        = Color((1, 1, 0, 1.00))
        stroke_mirror_color = Color((1, 1, 0, 0.25))
        mouse_mirror_color  = Color((1, 1, 0, 0.50))
        mouse_mirror_radius = 7
        push_above          = 0.01
        shrink_below        = 0.80
        stroke_smooth       = smoothing  # [0,1], higher => more smoothing

        # hack to know which areas the mouse is in
        mouse_areas = set()  # TODO: make sure this actually works with multiple areas / quad

        @classmethod
        def get_stroke_smooth(cls):
            return cls.stroke_smooth
        @classmethod
        def set_stroke_smooth(cls, value):
            cls.stroke_smooth = clamp(value, 0.00, 1.00)

        def init(self):
            self.mouse = None

            self.shift_held = False

            self.matrix_world = None
            self.matrix_world_inv = None
            self.matrix_world_ti = None
            self.nearest_bmv = None
            self.nearest_bme = None
            self.nearest_bmf = None

            self.hit = False
            self.hit_p = None
            self.hit_n = None
            self.hit_pl = None
            self.hit_nl = None
            self.hit_scale = None
            self.hit_depth = None
            self.hit_x = None
            self.hit_y = None
            self.hit_z = None
            self.hit_rmat = None

            self.mirror = set()
            self.mirror_clip = False
            self.mirror_threshold = 0
            # self.snap_mirror_ratio = 0.90  # [0,1] ratio of stroke near mirror to snap whole stroke

            # reset snap to nearest
            self.reset()

            self.clear_stroke()

            self.operator = None

            self.timer = None

        def set_operator(self, operator):
            # this is called whenever operator using brush is started
            # note: artist just used another operator, so the data likely changed.
            #       reset nearest info so that we can rebuild structure!
            self.operator = operator

        def reset(self):
            self.nearest_bmv = None
            self.snap_bmv0 = None
            self.snap_bmv1 = None
            self.nearest_bme = None
            self.snap_bme_back, self.co_back = None, None
            self.snap_bme_left, self.co_left = None, None
            self.snap_bme_front, self.co_front = None, None
            self.snap_bme_right, self.co_right = None, None
            self.nearest_bmf = None
            self.snap_bmf0 = None
            self.snap_bmf1 = None


        def reset_nearest(self, context):
            # Clear nearest references
            self.nearest_bmv = None
            self.nearest_bme = None
            self.nearest_bmf = None

            # Clear snap references
            self.snap_bmv0 = None
            self.snap_bmv1 = None
            self.snap_bmf0 = None
            self.snap_bmf1 = None

            bm = get_bmesh_emesh(context, ensure_lookup_tables=True)[0] if context.edit_object else None
            if bm is not None and bm.is_valid:
                # Update matrices.
                self.matrix_world = context.edit_object.matrix_world
                self.matrix_world_inv = self.matrix_world.inverted()
                self.matrix_world_ti = self.matrix_world.inverted().transposed()

                if snap_verts:
                    self.nearest_bmv = NearestBMVert(bm, self.matrix_world, self.matrix_world_inv)
                if snap_edges:
                    self.nearest_bme = NearestBMEdge(bm, self.matrix_world, self.matrix_world_inv)
                if snap_faces:
                    self.nearest_bmf = NearestBMFace(bm, self.matrix_world, self.matrix_world_inv)
            else:
                print('Warning: Could not get valid BMesh')

                # No edit object available
                self.matrix_world = None
                self.matrix_world_inv = None
                self.matrix_world_ti = None

            if not self.operator:
                self.reset()


        def get_scaled_radius(self):
            return self.hit_scale * self.stroke_radius

        def is_stroking(self):
            return self.stroke is not None

        def update_snap(self, context, mouse):
            if not self.operator or not self.operator.is_active(): return

            if snap_any and not (self.nearest_bmv or self.nearest_bmf):
                self.reset_nearest(context)

            hit = raycast_valid_sources(context, mouse)
            if not hit: return

            if self.nearest_bmv:
                self.nearest_bmv.update(
                    context,
                    hit['co_local'],
                    filter_fn=(lambda bmv: (bmv.is_boundary or bmv.is_wire) and not is_bmvert_hidden(context, bmv)),
                    distance2d=self.snap_distance - 3,
                )
                if not self.is_stroking():
                    self.snap_bmv0 = self.nearest_bmv.bmv
                    self.snap_bmv1 = None
                    self.snap_mirror_0 = self.get_snap_mirror(context, hit['co_local'])
                    self.snap_mirror_1 = None
                    self.snap_mirror_all = False
                elif self.snap_bmv0 != self.nearest_bmv.bmv:
                    self.snap_bmv1 = self.nearest_bmv.bmv
                else:
                    self.snap_bmv1 = None
                self.snap_mirror_1 = self.get_snap_mirror(context, hit['co_local'])

            if self.nearest_bmf:
                self.nearest_bmf.update(
                    context,
                    hit['co_local'],
                    filter_fn=(lambda bmf: any(len(bme.link_faces)==1 for bme in bmf.edges) and not any(map(lambda bmv:is_bmvert_hidden(context, bmv), bmf.verts))),
                )
                if not self.is_stroking():
                    self.snap_bmf0 = self.nearest_bmf.bmf
                    self.snap_bmf1 = None
                else:
                    self.snap_bmf1 = self.nearest_bmf.bmf


        def update(self, context, event):
            if not self.RFCore.is_current_area(context):
                self.reset()
                return

            if self.shift_held != event.shift:
                self.shift_held = event.shift
                context.area.tag_redraw()

            if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
                self.clear_stroke()
                self.reset()
                if self.timer: self.timer.stop()
                self.timer = None
                context.area.tag_redraw()
                return

            self._update(context)

            self.mirror = set()
            self.mirror_clip = False
            self.mirror_threshold = 0
            for mod in context.edit_object.modifiers:
                if mod.type != 'MIRROR': continue
                if not mod.use_clip: continue
                if mod.use_axis[0]: self.mirror.add('x')
                if mod.use_axis[1]: self.mirror.add('y')
                if mod.use_axis[2]: self.mirror.add('z')
                self.mirror_threshold = mod.merge_threshold
                self.mirror_clip = mod.use_clip
            self.snap_mirror = self.get_snap_mirror(context, self.hit_pl)

            if self.snap_bmv0 and not self.snap_bmv0.is_valid: self.snap_bmv0 = None
            if self.snap_bmv1 and not self.snap_bmv1.is_valid: self.snap_bmv1 = None
            # TODO: Implement for bme if needed
            if self.snap_bmf0 and not self.snap_bmf0.is_valid: self.snap_bmf0 = None
            if self.snap_bmf1 and not self.snap_bmf1.is_valid: self.snap_bmf1 = None

            if not self.is_stroking():
                if not event.ctrl or not self.operator:
                    if self.mouse:
                        self.mouse = None
                        self.hit = False
                        context.area.tag_redraw()
                    return

            # mouse and self.mouse will be the same as long as we hit a source
            # otherwise, mouse is current spot and self.mouse is last spot we hit
            mouse = mouse_from_event(event)
            self.update_snap(context, mouse)

            if event.type == 'LEFTMOUSE':
                if event.value == 'PRESS':
                    if event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
                        if self.add_stroke_point(context, Point2D(self.mouse)):
                            self.mouse = mouse
                            self.mousedown = mouse
                            self.stroke_far = False
                            self.stroke_cycle = False
                            self.last_time = time()
                            self.timer = TimerHandler(120, context=context, enabled=True)

                elif event.value == 'RELEASE':
                    if self.is_stroking():
                        # only add final mouse position if it is over source
                        self.add_stroke_point(context, Point2D(self.mouse))

                        self.process_stroke(context)

                        self.clear_stroke()
                        self.reset()

                        self.timer.stop()
                        self.timer = None

                context.area.tag_redraw()

            if self.mouse and event.type not in {'MOUSEMOVE','TIMER'}:
                return

            if self.is_stroking(): # and event.type == 'TIMER':
                pre = self.stroke_original[-1]
                cur = Point2D(mouse)
                delta_t = time() - self.last_time
                smoothing_mapped = CubicEaseOut(duration=1.5).ease(RFBrush_Stroke.stroke_smooth)
                smoothing_factor = 1.0 - smoothing_mapped ** (delta_t * 50)
                pt = pre + (cur - pre) * smoothing_factor
                self.add_stroke_point(context, pt)
                if (self.stroke_original[0] - self.stroke_original[-1]).length > Drawing.scale(self.far_distance):
                    self.stroke_far = True
                if self.stroke_far and not self.snap_bmv0 and not self.snap_bmv1:
                    self.stroke_cycle = (self.stroke_original[0] - self.stroke_original[-1]).length < Drawing.scale(self.snap_distance)

            if self.operator.is_active() or RFOperator_StrokeBrush_Adjust.is_active():
                # artist is actively stroking or adjusting brush properties, so always consider us inside if we're in the same area
                active_op = RFOperator.active_operator()
                mouse_inside = (context.area == active_op.working_area) and (context.window == active_op.working_window)
            else:
                mouse_inside = (0 <= mouse[0] < context.area.width) and (0 <= mouse[1] < context.area.height)

            if not mouse_inside:
                if context.area in self.mouse_areas:
                    # we were inside this area, but not anymore.  tag for redraw to remove brush
                    self.mouse_areas.remove(context.area)
                    context.area.tag_redraw()
                return

            if context.area not in self.mouse_areas:
                # we were outside this area before, but now we're in
                self.mouse_areas.add(context.area)

            self.mouse = mouse
            context.area.tag_redraw()
            self.last_time = time()

        def clear_stroke(self):
            self.stroke_original = None
            self.stroke3D_original = None
            self.stroke_normal = None
            self.stroke_dist = None

            self.stroke = None
            self.stroke3D = None

            self.stroke_far = False    # True when stroke has gone "far enough" away to consider cycle
            self.stroke_cycle = False  # True when stroke has formed a cycle with self
            self.snap_mirror_0 = False
            self.snap_mirror_1 = False

            # left and right sides, used to previz brush for PolyStrips
            self.stroke3D_left = None
            self.stroke3D_right = None
            self.stroke3D_left_start = None
            self.stroke3D_left_end = None
            self.stroke3D_right_start = None
            self.stroke3D_right_end = None

        def add_stroke_point(self, context, pt2D):
            hit = raycast_valid_sources(context, pt2D)
            if not hit: return False

            pt3D = hit['co_local']

            def find_stroke3D_point_from(i_start, i_dir, *, max_dist_pixels=5):
                pt2D, pt3D = self.stroke_original[i_start], self.stroke3D_original[i_start]
                pt3D_best, dist_best = pt3D, 0
                for (pto2D, pto3D) in zip(self.stroke_original[i_start::i_dir], self.stroke3D_original[i_start::i_dir]):
                    dist = (pt2D - pto2D).length
                    if dist >= dist_best: pt3D_best, dist_best = pto3D, dist
                    if dist_best > max_dist_pixels: break
                return pt3D_best

            if self.stroke_original is None:
                self.stroke_original = []
                self.stroke3D_original = []
                self.stroke_normal = []
                self.stroke_dist = []
                self.stroke3D_left = []
                self.stroke3D_right = []

            if len(self.stroke_original) > 1:
                # if last two points were too close, so replace last point with current
                pt2D_prev0 = self.stroke_original[-2]
                pt2D_prev1 = self.stroke_original[-1]
                if (pt2D_prev0 - pt2D_prev1).length < 2:
                    self.stroke_original.pop()
                    self.stroke3D_original.pop()
                    self.stroke_normal.pop()
                    self.stroke_dist.pop()

            self.stroke_original   += [pt2D]
            self.stroke3D_original += [pt3D]
            self.stroke_normal     += [hit['no_local']]
            self.stroke_dist       += [hit['distance']]
            self.snap_mirror_all = False

            if draw_leftright:
                # TODO: only update the last little bit.  once stroke is sufficiently long, do not need to recheck that part

                self.stroke3D_left, self.stroke3D_right  = [], []

                # set initial position of left and right sides
                # Note: if stroke is not long, there is not enough info to determine good left and right sides
                # TODO: left and right sides could be off high poly mesh!  shrink radius until left and right are both on mesh
                for i in range(len(self.stroke_original)):
                    pt2D, pt3D, no = self.stroke_original[i], self.stroke3D_original[i], self.stroke_normal[i]
                    radius3D = self.stroke_radius * size2D_to_size(context, self.stroke_dist[0]) # self.stroke_dist[i])
                    pt3D_prev, pt3D_next = find_stroke3D_point_from(i, -1), find_stroke3D_point_from(i,  1)
                    d_left = no.cross(pt3D_next - pt3D_prev).normalized()
                    self.stroke3D_left  += [pt3D + d_left * radius3D]
                    self.stroke3D_right += [pt3D - d_left * radius3D]
                self.co_left, self.co_right = self.stroke3D_left[-1], self.stroke3D_right[-1]

                # if stroke is sufficiently long enough, determine front and back
                if len(self.stroke3D_left) > 2:
                    pt3D_next, pt3D_prev = self.stroke3D_original[0], find_stroke3D_point_from(0, 1)
                    radius3D = self.stroke_radius * size2D_to_size(context, self.stroke_dist[0])
                    v_forward = (pt3D_next - pt3D_prev).normalized() * radius3D
                    self.stroke3D_left_start  = self.stroke3D_left[0]  + v_forward
                    self.stroke3D_right_start = self.stroke3D_right[0] + v_forward
                    self.co_back = (self.stroke3D_left_start + self.stroke3D_right_start) / 2

                    pt3D_next, pt3D_prev = self.stroke3D_original[-1], find_stroke3D_point_from(-1, -1)
                    radius3D = self.stroke_radius * size2D_to_size(context, self.stroke_dist[0]) # self.stroke_dist[-1])
                    v_forward = (pt3D_next - pt3D_prev).normalized() * radius3D
                    self.stroke3D_left_end  = self.stroke3D_left[-1]  + v_forward
                    self.stroke3D_right_end = self.stroke3D_right[-1] + v_forward
                    self.co_front = (self.stroke3D_left_end + self.stroke3D_right_end) / 2

                # snap to bmedges if able and have enough information
                if self.nearest_bme and self.co_back and self.co_front:
                    radius3D = math.pi * 2.0 * self.stroke_radius / 4.0 * size2D_to_size(context, self.stroke_dist[0])
                    snap_bmes = set()

                    # check back
                    bme = self.nearest_bme.update(
                        context, self.co_back,
                        filter_fn=(lambda bme: (bme.is_boundary or bme.is_wire)), # and not is_bmedge_hidden(context, bme)),
                        ignore_selected=False,
                        distance=radius3D,
                    )
                    if bme:
                        pt0, pt1 = self.nearest_bme.co2d, self.stroke_original[0]
                        if (pt0 - pt1).length <= self.stroke_radius + self.snap_distance:
                            snap_bmes.add(bme)
                            vp = self.stroke3D_right_start - self.stroke3D_left_start
                            self.stroke3D_left_start, self.stroke3D_right_start = [bmv.co for bmv in bme.verts]
                            vn = self.stroke3D_right_start - self.stroke3D_left_start
                            if vp.dot(vn) < 0: self.stroke3D_left_start, self.stroke3D_right_start = self.stroke3D_right_start, self.stroke3D_left_start

                    # check front
                    bme = self.nearest_bme.update(
                        context, self.co_front,
                        filter_fn=(lambda bme: (bme.is_boundary or bme.is_wire)), # and not is_bmedge_hidden(context, bme)),
                        ignore_selected=False,
                        distance=radius3D,
                    )
                    if bme:
                        pt0, pt1 = self.nearest_bme.co2d, self.stroke_original[-1]
                        if (pt0 - pt1).length <= self.stroke_radius + self.snap_distance:
                            snap_bmes.add(bme)
                            vp = self.stroke3D_right_end - self.stroke3D_left_end
                            self.stroke3D_left_end, self.stroke3D_right_end = [bmv.co for bmv in bme.verts]
                            vn = self.stroke3D_right_end - self.stroke3D_left_end
                            if vp.dot(vn) < 0: self.stroke3D_left_end, self.stroke3D_right_end = self.stroke3D_right_end, self.stroke3D_left_end

                    # check left
                    # print(f'left')
                    nleft, cleft = [], []
                    i1 = -1
                    for (i0, ptcur) in enumerate(self.stroke3D_left):
                        if i0 <= i1: continue
                        bme = self.nearest_bme.update(
                            context, ptcur,
                            filter_fn=(lambda bme: (bme.is_boundary or bme.is_wire)), # and not is_bmedge_hidden(context, bme)),
                            ignore_selected=False,
                            distance=radius3D,
                        )
                        if not bme or bme in snap_bmes:
                            cleft += [ptcur]
                            continue
                        pt0, pt1 = [bmv.co for bmv in bme.verts]
                        v01 = (pt1 - pt0)
                        l = v01.length
                        ptc = closest_point_segment(ptcur, pt0, pt1, clamp_ratio=0.05)
                        dist = (ptc - ptcur).length
                        if dist > l or dist > radius3D:
                            # print(f'  {l=} {radius3D=} {dist=}')
                            cleft += [ptcur]
                            continue
                        # rewind until stroke should not snap to bme
                        cleft_prev = list(cleft)
                        ptp = ptcur # set default
                        while cleft:
                            ptp = cleft[-1]
                            ptc = closest_point_segment(ptp, pt0, pt0, clamp_ratio=0.25)
                            vpc = (ptc - ptp)
                            dist = (ptp - ptc).length
                            if dist > l and dist > radius3D: break
                            cleft.pop()
                            # print(f'{dist=} {l=} {radius3D=}')
                        ptn = ptcur  # set default
                        i1 = i0
                        for i2 in range(i0+1, len(self.stroke3D_left)):
                            ptn = self.stroke3D_left[i1]
                            ptc = closest_point_segment(ptn, pt0, pt0, clamp_ratio=0.25)
                            vpc = (ptc - ptn)
                            dist = (ptn - ptc).length
                            if dist <= l or dist <= radius3D:
                                i1 = i2
                        vpn = (ptn - ptp)
                        if vpn.dot(v01) < 0: pt0, pt1, v01 = pt1, pt0, -v01
                        d = vpn.normalized().dot(v01.normalized())
                        # print(f'{d=}')
                        if abs(d) < 0.50:
                            i1 = i0
                            cleft = cleft_prev + [ptcur]
                            continue
                        # print(f'  found closest {i0=} {i1=} len={len(self.stroke3D_left)} {bme=}')
                        snap_bmes.add(bme)
                        nleft += cleft + [pt0, pt1]
                        cleft = []
                    self.stroke3D_left = nleft + cleft
                    if not cleft:
                        self.stroke3D_left_end = nleft[-1]

                    # check right
                    # print(f'right')
                    nright, cright = [], []
                    i1 = -1
                    for (i0, ptcur) in enumerate(self.stroke3D_right):
                        if i0 <= i1: continue
                        bme = self.nearest_bme.update(
                            context, ptcur,
                            filter_fn=(lambda bme: (bme.is_boundary or bme.is_wire)), # and not is_bmedge_hidden(context, bme)),
                            ignore_selected=False,
                            distance=radius3D,
                        )
                        if not bme or bme in snap_bmes:
                            cright += [ptcur]
                            continue
                        pt0, pt1 = [bmv.co for bmv in bme.verts]
                        v01 = (pt1 - pt0)
                        l = v01.length
                        ptc = closest_point_segment(ptcur, pt0, pt1, clamp_ratio=0.25)
                        vpc = (ptc - ptcur)
                        dist = vpc.length
                        #print(f'  {l=} {dist=}')
                        if dist > l:
                            cright += [ptcur]
                            continue
                        # rewind until stroke should not snap to bme
                        cright_prev = list(cright)
                        ptp = ptcur # set default
                        while cright:
                            ptp = cright[-1]
                            ptc = closest_point_segment(ptp, pt0, pt0, clamp_ratio=0.25)
                            vpc = (ptc - ptp)
                            dist = (ptp - ptc).length
                            if dist > l and dist > radius3D: break
                            cright.pop()
                            # print(f'{dist=} {l=} {radius3D=}')
                        ptn = ptcur  # set default
                        i1 = i0
                        for i2 in range(i0+1, len(self.stroke3D_right)):
                            ptn = self.stroke3D_right[i1]
                            ptc = closest_point_segment(ptn, pt0, pt0, clamp_ratio=0.25)
                            vpc = (ptc - ptn)
                            dist = (ptn - ptc).length
                            if dist <= l or dist <= radius3D:
                                i1 = i2
                        vpn = (ptn - ptp)
                        if vpn.dot(v01) < 0:
                            pt0, pt1 = pt1, pt0
                            v01 = -v01
                        d = vpn.normalized().dot(v01.normalized())
                        # print(f'{d=}')
                        if abs(d) < 0.50:
                            i1 = i0
                            cright = cright_prev + [ptcur]
                            continue
                        # print(f'  found closest {i0=} {i1=} len={len(self.stroke3D_right)} {bme=}')
                        snap_bmes.add(bme)
                        nright += cright + [pt0, pt1]
                        cright = []
                    self.stroke3D_right = nright + cright
                    if not cright:
                        self.stroke3D_right_end = nright[-1]
                    ##### for pt in self.stroke3D_left

                # if self.nearest_bme and self.co_front and self.co_left and self.co_right:
                #     radius = math.pi * 2.0 * self.stroke_radius / 4.0
                #     self.snap_bme_back, self.snap_bme_front = None, None
                #     self.snap_bme_left, self.snap_bme_right = None, None
                #     snap_bmes = {}
                #     # need to find nearest from four different points, because we cannot find the N nearest things
                #     # using blender's BVH Tree (sad face)
                #     # should only find back after stroke has gone far enough and front,left,right while stroking
                #     # once an edge gets close enough, continue snapping until it is too far away (but keep remembering
                #     # it in case it gets close enough again... in other words, don't snap twice!).  do we need to
                #     # keep track of all the edges that left and right snap to, or should this get rediscovered in
                #     # the tool?
                #     # https://www.desmos.com/geometry/iqctjch3rm
                #     for (co,i,w) in [(self.co_back,0,'b'), (self.co_front,-1,'f'), (self.co_left,-1,'l'), (self.co_right,-1,'r')]:
                #         bme = self.nearest_bme.update(
                #             context, co,
                #             filter_fn=(lambda bme: (bme.is_boundary or bme.is_wire)), # and not is_bmedge_hidden(context, bme)),
                #             ignore_selected=False,
                #             distance2d=radius,
                #         )
                #         if not bme: continue
                #         pt0, pt1 = self.nearest_bme.co2d, self.stroke_original[i]
                #         if (pt0 - pt1).length > self.stroke_radius + self.snap_distance: continue  # too far away from stroke
                #         co2d = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ co)
                #         d = (co2d - pt0).length
                #         if bme in snap_bmes and d >= snap_bmes[bme][0]: continue  # seen this bme closer to another already
                #         snap_bmes[bme] = (d, w)

                #     for bme in snap_bmes:
                #         match snap_bmes[bme][1]:
                #             case 'b': self.snap_bme_back  = bme
                #             case 'f': self.snap_bme_front = bme
                #             case 'l': self.snap_bme_left  = bme
                #             case 'r': self.snap_bme_right = bme
                #     # print(f'{self.snap_bme_back=} {self.snap_bme_left=} {self.snap_bme_right=} {self.snap_bme_front=}')
                #     # print(f'{self.snap_bme_left=} {self.snap_bme_right=}')

                #     if self.snap_bme_back:
                #         vp = self.stroke3D_right_start - self.stroke3D_left_start
                #         self.stroke3D_left_start, self.stroke3D_right_start = [bmv.co for bmv in self.snap_bme_back.verts]
                #         vn = self.stroke3D_right_start - self.stroke3D_left_start
                #         if vp.dot(vn) < 0: self.stroke3D_left_start, self.stroke3D_right_start = self.stroke3D_right_start, self.stroke3D_left_start
                #     if self.snap_bme_front:
                #         vp = self.stroke3D_right_end - self.stroke3D_left_end
                #         self.stroke3D_left_end, self.stroke3D_right_end = [bmv.co for bmv in self.snap_bme_front.verts]
                #         vn = self.stroke3D_right_end - self.stroke3D_left_end
                #         if vp.dot(vn) < 0: self.stroke3D_left_end, self.stroke3D_right_end = self.stroke3D_right_end, self.stroke3D_left_end


            if not self.mirror or not self.mirror_clip:
                # no mirror handling needed
                self.stroke = self.stroke_original
                self.stroke3D = self.stroke3D_original
                return True

            # stroke may touch mirror

            snaps = [self.get_snap_mirror(context, co) for co in self.stroke3D_original]
            sides = [self.get_mirror_side(co)          for co in self.stroke3D_original]

            all_sides = set(sides)
            all_snaps = { tuple(snap) for snap in snaps }
            if all_snaps == { tuple() } and len(all_sides) == 1:
                # mirror is there, but the stroke did not touch
                self.stroke = self.stroke_original
                self.stroke3D = self.stroke3D_original
                return True

            DEBUG = False

            if DEBUG: print(f'stroke touches mirror')
            l = len(self.stroke_original)
            self.stroke3D = []
            if DEBUG: print(f'0-', end='')
            i0 = 0
            last_side = sides[0]
            while i0 < l:
                if sides[i0] != last_side:
                    last_side = sides[i0]
                    if not snaps[i0-1] and not snaps[i0]:  # safe to check i0-1
                        # crossed mirror without getting near it
                        if DEBUG: print(f'{i0-1} crossed mirror {i0}-', end='')
                        pt0 = self.stroke3D_original[i0-1]
                        pt1 = self.stroke3D_original[i0]
                        for _ in range(100):
                            pt = pt0 + (pt1 - pt0) * 0.5
                            (pt0, pt1) = (pt0, pt) if sides[i0] == self.get_mirror_side(pt) else (pt, pt1)
                        snap = self.get_snap_mirror(context, pt)  # possible (although unlikely) that snap is empty!
                        self.stroke3D += [pt * Vector((
                            0 if 'x' in snap else 1,
                            0 if 'y' in snap else 1,
                            0 if 'z' in snap else 1,
                        ))]
                        i0 += 1
                        continue

                if not snaps[i0] and sides[i0] == last_side:
                    # not near mirror and did not cross mirror
                    self.stroke3D += [self.stroke3D_original[i0]]
                    i0 += 1
                    continue

                # near mirror
                i1 = next((i1 for i1 in range(i0, l-1) if not snaps[i1+1]), l - 1)

                if i1 == l - 1:
                    # rest of stroke is near mirror
                    if DEBUG: print(f'{i0} rest near mirror {i1}-', end='')
                    self.stroke3D += [self.stroke3D_original[i0] * Vector((
                        0 if 'x' in snaps[i0] else 1,
                        0 if 'y' in snaps[i0] else 1,
                        0 if 'z' in snaps[i0] else 1,
                    ))]
                    if i0 != i1:
                        self.stroke3D += [self.stroke3D_original[i1] * Vector((
                            0 if 'x' in snaps[i1] else 1,
                            0 if 'y' in snaps[i1] else 1,
                            0 if 'z' in snaps[i1] else 1,
                        ))]
                    break

                pt0, pt1 = self.stroke_original[i0], self.stroke_original[i1]
                if (pt0 - pt1).length > 20:
                    if DEBUG: print(f'{i0} stretch near mirror {i1}-', end='')
                    # long stretch of stroke is near mirror, so snap it all
                    self.stroke3D += [self.stroke3D_original[i0] * Vector((
                        0 if 'x' in snaps[i0] else 1,
                        0 if 'y' in snaps[i0] else 1,
                        0 if 'z' in snaps[i0] else 1,
                    ))]
                    self.stroke3D += [self.stroke3D_original[i1] * Vector((
                        0 if 'x' in snaps[i1] else 1,
                        0 if 'y' in snaps[i1] else 1,
                        0 if 'z' in snaps[i1] else 1,
                    ))]
                    i0 = i1 + 1
                    continue

                # stroke either crosses or bounces off mirror
                # find point of stroke closest to mirror
                fn_dist = lambda pt: self.get_mirror_dist(pt, self.get_snap_mirror(context, pt))
                i_min = min(range(i0,i1+1), key=lambda i:fn_dist(self.stroke3D_original[i]))
                if DEBUG: print(f'{i0} cross/bounce at {i_min} {i1}-', end='')
                pt = self.stroke3D_original[i_min]
                self.stroke3D += [pt * Vector((
                    0 if 'x' in snaps[i0] else 1,
                    0 if 'y' in snaps[i0] else 1,
                    0 if 'z' in snaps[i0] else 1,
                ))]
                i0 = i1 + 1
            if DEBUG: print(f'{l-1}')

            self.stroke = [
                location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ co)
                for co in self.stroke3D
            ]

            return True

        def process_stroke(self, context):
            # # tessellate stroke
            # new_stroke = []
            # for (co0, co1) in iter_pairs(self.stroke, False):
            #     new_stroke += [co0]
            #     d = co1 - co0
            #     l = d.length
            #     lt = int(l / 0.5)
            #     for i in range(lt):
            #         co = co0 + d * (i / lt)
            #         new_stroke += [co]
            # new_stroke += [self.stroke[-1]]
            # self.stroke = new_stroke
            # self.stroke3D = [raycast_valid_sources(context, pt2D)['co_local'] for pt2D in self.stroke]

            self.operator.process_stroke(
                context,
                self.stroke_radius,
                self.snap_distance,
                self.stroke,
                self.stroke3D,
                self.stroke_cycle,
                [(self.snap_bmv0, self.snap_bmv1), (None, None), (self.snap_bmf0, self.snap_bmf1)],
                [self.snap_mirror_0, self.snap_mirror_1, self.snap_mirror_all],
            )

        def _update(self, context):
            if context.area not in self.mouse_areas: return
            if not self.matrix_world: return
            self.hit = False
            if not self.mouse: return
            # print(f'RFBrush_Stroke.update {(event.mouse_region_x, event.mouse_region_y)}') #{context.region=} {context.region_data=}')
            hit = raycast_valid_sources(context, self.mouse)
            # print(f'  {hit=}')
            if not hit: return
            if self.is_stroking():
                scale_below = size2D_to_size(context, self.stroke_dist[0])
                scale_above = size2D_to_size(context, self.stroke_dist[0] - self.push_above)
            else:
                scale_below = size2D_to_size(context, hit['distance'])
                scale_above = size2D_to_size(context, hit['distance'] - self.push_above)
            # print(f'  {scale=}')
            if not scale_below or not scale_above: return

            n = hit['no_local']
            rmat = Matrix.Rotation(Direction.Z.angle(n), 4, Direction.Z.cross(n))

            self.hit = True
            self.hit_ray = hit['ray_world']
            self.hit_scale_below = scale_below
            self.hit_scale_above = scale_above
            self.hit_p = hit['co_world']
            self.hit_n = hit['no_world']
            self.hit_pl = hit['co_local']
            self.hit_nl = hit['no_local']
            self.hit_depth = hit['distance']
            self.hit_x = Vec(rmat @ Direction.X)
            self.hit_y = Vec(rmat @ Direction.Y)
            self.hit_z = Vec(rmat @ Direction.Z)
            self.hit_rmat = rmat

        def draw_adjust(self, context):
            center2D = self.center2D
            co = self.outer_color
            instance: RFOperator_StrokeBrush_Adjust = RFOperator_StrokeBrush_Adjust.active_operator()
            Drawing.draw2D_smooth_circle(context, center2D, self.stroke_radius, co, width=2.5)
            if instance:
                Drawing.draw2D_smooth_circle(context, center2D, instance.prev_radius, co, width=.5)

        def draw_stroke(self, context):
            if self.mouse:
                if (not self.is_stroking() and self.snap_bmv0) or (self.is_stroking() and self.snap_bmv1):
                    Drawing.draw2D_smooth_circle(context, Point2D(self.mouse), self.snap_distance, self.snap_color, width=1)
                elif self.snap_mirror:
                    Drawing.draw2D_smooth_circle(context, Point2D(self.mouse), self.snap_distance, self.snap_color, width=1)
                elif self.stroke_cycle:
                    Drawing.draw2D_smooth_circle(context, Point2D(self.mouse), self.snap_distance, self.cycle_color, width=1)
                elif self.hit:
                    Drawing.draw2D_smooth_circle(context, Point2D(self.mouse), self.snap_distance, self.inner_color, width=1)
                else:
                    Drawing.draw2D_smooth_circle(context, Point2D(self.mouse), self.snap_distance, self.miss_color, width=1)

            if self.operator and self.operator.is_active() and self.is_stroking():
                # draw mirrored stroke first
                for axes in all_combinations(self.mirror):
                    s = Vector((
                        -1 if 'x' in axes else 1,
                        -1 if 'y' in axes else 1,
                        -1 if 'z' in axes else 1,
                    ))
                    mcos = [
                        mco for co in self.stroke3D
                        if (mco := location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ (co * s)))
                    ]
                    Drawing.draw2D_linestrip(context, mcos, self.stroke_mirror_color, width=2, stipple=[5,5])

                    if draw_leftright and self.stroke3D_left_start:
                        mcos_left = [
                            mco for co in chain([self.stroke3D_left_start], self.stroke3D_left, [self.stroke3D_left_end])
                            if (mco := location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ (co * s)))
                        ]
                        mcos_right = [
                            mco for co in chain([self.stroke3D_right_start], self.stroke3D_right, [self.stroke3D_right_end])
                            if (mco := location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ (co * s)))
                        ]
                        Drawing.draw2D_linestrip(context, mcos_left, [1,1,0,0.25], width=1, stipple=[3,3])
                        Drawing.draw2D_linestrip(context, mcos_right, [1,1,0,0.25], width=1, stipple=[3,3])
                        Drawing.draw2D_linestrip(context, [mcos_left[0], mcos_right[0]], [1,1,0,0.25], width=1, stipple=[3,3])
                        Drawing.draw2D_linestrip(context, [mcos_left[-1], mcos_right[-1]], [1,1,0,0.25], width=1, stipple=[3,3])

                Drawing.draw2D_linestrip(context, self.stroke, self.stroke_color, width=2, stipple=[5,5])
                if draw_leftright and self.stroke3D_left_start:
                    mcos_left = [
                        mco for co in chain([self.stroke3D_left_start], self.stroke3D_left, [self.stroke3D_left_end])
                        if (mco := location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ co))
                    ]
                    mcos_right = [
                        mco for co in chain([self.stroke3D_right_start], self.stroke3D_right, [self.stroke3D_right_end])
                        if (mco := location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ co))
                    ]
                    Drawing.draw2D_linestrip(context, mcos_left, [1,1,0,0.5], width=1, stipple=[3,3])
                    Drawing.draw2D_linestrip(context, mcos_right, [1,1,0,0.5], width=1, stipple=[3,3])
                    Drawing.draw2D_linestrip(context, [mcos_left[0], mcos_right[0]], [1,1,0,0.5], width=1, stipple=[3,3])
                    Drawing.draw2D_linestrip(context, [mcos_left[-1], mcos_right[-1]], [1,1,0,0.5], width=1, stipple=[3,3])

                if self.stroke_cycle:
                    Drawing.draw2D_linestrip(context, [self.stroke[0], self.stroke[-1]], self.cycle_color, width=2)

            if self.nearest_bmv:
                if self.is_stroking():
                    if self.snap_bmv0 and self.snap_bmv0.is_valid:
                        co = self.matrix_world @ self.snap_bmv0.co
                        p2d = location_3d_to_region_2d(context.region, context.region_data, co)
                        Drawing.draw2D_linestrip(context, [self.stroke[0], p2d], self.snap_color, width=2)
                    if self.snap_bmv1 and self.snap_bmv1.is_valid:
                        co = self.matrix_world @ self.snap_bmv1.co
                        p2d = location_3d_to_region_2d(context.region, context.region_data, co)
                        Drawing.draw2D_linestrip(context, [self.stroke[-1], p2d], self.snap_color, width=2)
                else:
                    if self.mouse and self.snap_bmv0 and self.snap_bmv0.is_valid:
                        co = self.matrix_world @ self.snap_bmv0.co
                        p2d = location_3d_to_region_2d(context.region, context.region_data, co)
                        Drawing.draw2D_linestrip(context, [Point2D(self.mouse), p2d], self.snap_color, width=2)

            if self.mouse and self.snap_mirror:
                s = Vector((
                    0 if 'x' in self.snap_mirror else 1,
                    0 if 'y' in self.snap_mirror else 1,
                    0 if 'z' in self.snap_mirror else 1,
                ))
                co = self.matrix_world @ (self.hit_pl * s)
                p2d = location_3d_to_region_2d(context.region, context.region_data, co)
                Drawing.draw2D_linestrip(context, [Point2D(self.mouse), p2d], self.snap_color, width=2)

            if self.nearest_bmf:
                if self.snap_bmf0 and self.snap_bmf0.is_valid:
                    cos = [location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv.co) for bmv in self.snap_bmf0.verts]
                    Drawing.draw2D_linestrip(context, cos + [cos[0]], self.snap_color, width=2)
                if self.snap_bmf1 and self.snap_bmf1.is_valid:
                    cos = [location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv.co) for bmv in self.snap_bmf1.verts]
                    Drawing.draw2D_linestrip(context, cos + [cos[0]], self.snap_color, width=2)

        def draw_postpixel(self, context):
            if not self.RFCore.is_current_area(context): return
            if self.shift_held: return
            if not self.matrix_world: return
            #if context.area not in self.mouse_areas: return

            gpustate.blend('ALPHA')

            if RFOperator_StrokeBrush_Adjust.is_active():
                self.draw_adjust(context)
            else:
                self.draw_stroke(context)

        def get_mirror_side(self, pt3D_local):
            return (
                1 if 'x' not in self.mirror else sign_threshold(pt3D_local.x, self.mirror_threshold),
                1 if 'y' not in self.mirror else sign_threshold(pt3D_local.y, self.mirror_threshold),
                1 if 'z' not in self.mirror else sign_threshold(pt3D_local.z, self.mirror_threshold),
            )

        def get_mirror_dist(self, co, snap):
            return Vector((
                co.x if 'x' in snap else 0,
                co.y if 'y' in snap else 0,
                co.z if 'z' in snap else 0,
            )).length

        def get_snap_mirror(self, context, pt3D_local, *, max_dist=None):
            s = set()
            if max_dist is None: max_dist = self.snap_distance

            if not pt3D_local: return s
            if not (self.mirror and self.mirror_clip): return s
            if not self.matrix_world: return s

            pt3D_local = bvec_point_to_bvec4(pt3D_local)
            pt2D = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt3D_local)
            if not pt2D: return s

            if 'x' in self.mirror:
                if abs(pt3D_local.x) <= self.mirror_threshold: s.add('x')
                pt3D_local_mirror = pt3D_local * Vector((-1, 1, 1, 1))
                pt2D_mirror = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt3D_local_mirror)
                if pt2D_mirror:
                    dist = (pt2D - pt2D_mirror).length
                    if dist < max_dist: s.add('x')

            if 'y' in self.mirror:
                if abs(pt3D_local.y) <= self.mirror_threshold: s.add('y')
                pt3D_local_mirror = pt3D_local * Vector((1, -1, 1, 1))
                pt2D_mirror = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt3D_local_mirror)
                if pt2D_mirror:
                    dist = (pt2D - pt2D_mirror).length
                    if dist < max_dist: s.add('y')

            if 'z' in self.mirror:
                if abs(pt3D_local.z) <= self.mirror_threshold: s.add('z')
                pt3D_local_mirror = pt3D_local * Vector((1, 1, -1, 1))
                pt2D_mirror = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt3D_local_mirror)
                if pt2D_mirror:
                    dist = (pt2D - pt2D_mirror).length
                    if dist < max_dist: s.add('z')

            return s

        def draw_postview(self, context):
            if not self.RFCore.is_current_area(context): return
            if context.area not in self.mouse_areas: return
            if not self.matrix_world: return
            if self.shift_held: return

            if RFOperator_StrokeBrush_Adjust.is_active(): return

            self._update(context)
            if not self.hit: return

            pb, n = self.hit_p, self.hit_n

            if self.snap_mirror:
                pbl = self.hit_pl
                if 'x' in self.snap_mirror: pbl.x = 0
                if 'y' in self.snap_mirror: pbl.y = 0
                if 'z' in self.snap_mirror: pbl.z = 0
                pb = self.matrix_world @ pbl

            co = self.outer_color
            thickness = 1.0
            pa = pb - self.push_above * self.hit_ray[1].xyz # * context.region_data.view_distance

            gpustate.blend('ALPHA')
            gpustate.depth_mask(False)

            viewport_size = (context.region.width, context.region.height)

            # draw mirror
            mirrored_pts = []
            for axes in all_combinations(self.mirror):
                s = Vector((
                    0 if 'x' in self.snap_mirror else (-1 if 'x' in axes else 1),
                    0 if 'y' in self.snap_mirror else (-1 if 'y' in axes else 1),
                    0 if 'z' in self.snap_mirror else (-1 if 'z' in axes else 1),
                ))
                pt2D = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ (self.hit_pl * s))
                mirrored_pts.append(pt2D)
            gpustate.depth_test('LESS_EQUAL')
            Drawing.draw2D_points(context, mirrored_pts, self.mouse_mirror_color, radius=self.mouse_mirror_radius, border=0, borderColor=None)

            # draw below
            gpustate.depth_test('GREATER')
            Drawing.draw_circle_3d(pb, n, co * self.below_alpha, self.stroke_radius, scale=self.hit_scale_above, thickness=thickness, viewport_size=viewport_size)

            # draw above
            gpustate.depth_test('LESS_EQUAL')
            Drawing.draw_circle_3d(pa, n, co, self.stroke_radius, scale=self.hit_scale_below, thickness=thickness, viewport_size=viewport_size)
            if draw_leftright:
                for axes in all_combinations(self.mirror):
                    s = Vector((
                        0 if 'x' in self.snap_mirror else (-1 if 'x' in axes else 1),
                        0 if 'y' in self.snap_mirror else (-1 if 'y' in axes else 1),
                        0 if 'z' in self.snap_mirror else (-1 if 'z' in axes else 1),
                    ))
                    Drawing.draw_circle_3d(
                        self.matrix_world @ (self.hit_pl * s),
                        self.matrix_world_ti @ (self.hit_nl * s),
                        co,
                        self.stroke_radius,
                        scale=self.hit_scale_below,
                        thickness=thickness,
                        viewport_size=viewport_size,
                    )

            # reset
            gpustate.depth_test('LESS_EQUAL')
            gpustate.depth_mask(True)


    class RFOperator_StrokeBrush_Adjust(RFOperator):
        '''
        Handles resizing of Strokes Brush
        '''
        bl_idname = f'retopoflow.{idname}' # stroke_brush_radius
        bl_label = label
        bl_description = f'Adjust radius of {label}'
        bl_space_type = 'VIEW_3D'
        bl_space_type = 'TOOLS'
        bl_options = set()

        rf_keymaps = [
            # bl_idname
            (f'retopoflow.{idname}', {'type': 'F', 'value': 'PRESS'}, None),  #, 'ctrl': False, 'shift': False
        ]
        rf_status = ['LMB: Commit', 'RMB: Cancel']

        def can_init(self, context, event):
            return not any(
                instance.is_stroking()
                for instance in RFBrush_Stroke.get_instances()
            )

        def init(self, context, event):
            dist = self.radius_to_dist()
            self.prev_radius = RFBrush_Stroke.stroke_radius
            self._change_pre = dist
            mouse = Point2D((event.mouse_region_x, event.mouse_region_y))
            RFBrush_Stroke.center2D = mouse - Vec2D((dist, 0))
            context.area.tag_redraw()

        def dist_to_radius(self, d):
            RFBrush_Stroke.stroke_radius = max(5, int(d))
        def radius_to_dist(self):
            return RFBrush_Stroke.stroke_radius

        def update(self, context, event):
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                return {'FINISHED'}
            if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
                self.dist_to_radius(self._change_pre)
                return {'CANCELLED'}
            if event.type == 'ESC' and event.value == 'PRESS':
                self.dist_to_radius(self._change_pre)
                return {'CANCELLED'}

            if event.type == 'MOUSEMOVE':
                mouse = Point2D((event.mouse_region_x, event.mouse_region_y))
                dist = (RFBrush_Stroke.center2D - mouse).length
                self.dist_to_radius(dist)
                context.area.tag_redraw()
                return {'PASS_THROUGH'}

            return {'RUNNING_MODAL'} # allow other operators, such as UNDO!!!

    return (RFBrush_Stroke, RFOperator_StrokeBrush_Adjust)
