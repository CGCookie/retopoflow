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
from ..common.bmesh import get_bmesh_emesh, nearest_bmv_world, nearest_bme_world, NearestBMVert, NearestBMFace
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
from ..common.maths import view_forward_direction, lerp
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
from ...addon_common.common.maths import clamp, Direction, Vec, Point, Point2D, Vec2D, sign_threshold, all_combinations
from ...addon_common.common.timerhandler import TimerHandler
from ...addon_common.common.utils import iter_pairs

from time import time


#########################################################
# TODO: This RFBrush is a mess!  rewrite using states?
#########################################################

def filter_bmvs(bmvs):
    return [ bmv for bmv in bmvs if bmv.is_boundary or bmv.is_wire ]

def create_stroke_brush(idname, label, *, smoothing=0.5, snap=(True,False,False), radius=50):
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

            self.hit = False
            self.hit_p = None
            self.hit_n = None
            self.hit_pl = None
            self.hit_scale = None
            self.hit_depth = None
            self.hit_x = None
            self.hit_y = None
            self.hit_z = None
            self.hit_rmat = None

            self.mirror = set()
            self.mirror_clip = False
            self.mirror_threshold = 0
            self.snap_mirror_ratio = 0.90  # [0,1] ratio of stroke near mirror to snap whole stroke

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
            # TODO: Implement snapping to nearest bme if needed
            self.nearest_bmf = None
            self.snap_bmf0 = None
            self.snap_bmf1 = None

        def reset_nearest(self, context):
            if self.operator:
                self.matrix_world = context.edit_object.matrix_world
                self.matrix_world_inv = self.matrix_world.inverted()
                self.bm, self.em = get_bmesh_emesh(context)
                if snap_verts:
                    self.nearest_bmv = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv)
                if snap_faces:
                    self.nearest_bmf = NearestBMFace(self.bm, self.matrix_world, self.matrix_world_inv)
            elif context.edit_object:
                self.matrix_world = context.edit_object.matrix_world
                self.matrix_world_inv = self.matrix_world.inverted()
                self.bm, self.em = get_bmesh_emesh(context)
                if snap_verts:
                    self.nearest_bmv = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv)
                if snap_faces:
                    self.nearest_bmf = NearestBMFace(self.bm, self.matrix_world, self.matrix_world_inv)
                self.reset()
            else:
                self.matrix_world = None
                self.matrix_world_inv = None
                self.bm, self.em = None, None
                self.reset()

            self.snap_bmv0 = None
            self.snap_bmv1 = None
            self.snap_bmf0 = None
            self.snap_bmf1 = None

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

            self.stroke = None
            self.stroke3D = None

            self.stroke_far = False    # True when stroke has gone "far enough" away to consider cycle
            self.stroke_cycle = False  # True when stroke has formed a cycle with self
            self.snap_mirror_0 = False
            self.snap_mirror_1 = False

        def add_stroke_point(self, context, pt2D):
            hit = raycast_valid_sources(context, pt2D)
            if not hit: return False

            pt3D = hit['co_local']

            if self.stroke_original is None:
                self.stroke_original = []
                self.stroke3D_original = []

            self.stroke_original += [pt2D]
            self.stroke3D_original += [pt3D]
            self.snap_mirror_all = False

            if not self.snap_mirror_0 and not self.snap_mirror_1:
                self.stroke = self.stroke_original
                self.stroke3D = self.stroke3D_original
                return True

            # stroke start or end touch mirror, so snap!

            def get_mirror_dist(co, snap):
                return Vector((
                    co.x if 'x' in snap else 0,
                    co.y if 'y' in snap else 0,
                    co.z if 'z' in snap else 0,
                )).length

            snaps = [self.get_snap_mirror(context, co) for co in self.stroke3D_original]
            sides = [self.get_mirror_side(co)          for co in self.stroke3D_original]
            pre, i0, i1, post = [], 0, len(self.stroke3D_original), []
            if self.snap_mirror_0:
                closest = Vector(self.stroke3D_original[0])
                for i in range(len(snaps)):
                    if snaps[i]:
                        # still snapping
                        co = self.stroke3D_original[i]
                        if get_mirror_dist(co, self.snap_mirror_0) < get_mirror_dist(closest, self.snap_mirror_0):
                            closest = co
                        continue
                    # found where we don't snap anymore!
                    pre = [Vector((
                        0 if 'x' in self.snap_mirror_0 else closest.x,
                        0 if 'y' in self.snap_mirror_0 else closest.y,
                        0 if 'z' in self.snap_mirror_0 else closest.z,
                    ))]
                    i0 = i
                    break
            if self.snap_mirror_1:
                closest = Vector(self.stroke3D_original[-1])
                for i in range(1, len(snaps)):
                    if snaps[-i]:
                        # still snapping
                        co = self.stroke3D_original[-i]
                        if get_mirror_dist(co, self.snap_mirror_1) < get_mirror_dist(closest, self.snap_mirror_1):
                            closest = co
                        continue
                    # found where we don't snap anymore!
                    post = [Vector((
                        0 if 'x' in self.snap_mirror_1 else closest.x,
                        0 if 'y' in self.snap_mirror_1 else closest.y,
                        0 if 'z' in self.snap_mirror_1 else closest.z,
                    ))]
                    i1 = len(self.stroke3D_original) - i
                    break
            self.stroke3D = pre + self.stroke3D_original[i0:i1] + post
            self.stroke = [
                location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ co)
                for co in self.stroke3D
            ]


            return True

            #####################################################
            # THE FOLLOWING IS COMMENTED OUT FOR NOW
            # MIGHT TRY TO REVISIT THIS LATER
            # SEE ISSUE #1416 FOR CONTEXT

            # if not self.mirror or not self.mirror_clip:
            #     self.stroke = self.stroke_original
            #     self.stroke3D = self.stroke3D_original
            #     return True

            # t = self.mirror_threshold
            # along_mirror = sum(
            #     1 if self.get_snap_mirror(context, co) else 0
            #     for co in self.stroke3D_original
            # )

            # # handle: no stroke is near mirror
            # if along_mirror == 0:
            #     self.stroke = self.stroke_original
            #     self.stroke3D = self.stroke3D_original
            #     return True

            # # handle: almost all of stroke is near mirror
            # if along_mirror / len(self.stroke3D_original) > self.snap_mirror_ratio:
            #     # find which mirror we're closest to, then snap stroke entirely to that mirror
            #     counts = {}
            #     for co in self.stroke3D_original:
            #         snap = ''.join(sorted(self.get_snap_mirror(context, co)))
            #         counts[snap] = counts.get(snap, 0) + 1
            #     snap = max(counts.items(), key=lambda kv:kv[1])[0]
            #     self.stroke3D = [
            #         Vector((
            #             0 if 'x' in snap else co.x,
            #             0 if 'y' in snap else co.y,
            #             0 if 'z' in snap else co.z,
            #         ))
            #         for co in self.stroke3D_original
            #     ]
            #     self.stroke = [
            #         location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ co)
            #         for co in self.stroke3D
            #     ]
            #     self.snap_mirror_all = True
            #     return True

            # # handle: stroke comes near mirror at least once
            # def get_mirror_dist(co, snap):
            #     return Vector((
            #         co.x if 'x' in snap else 0,
            #         co.y if 'y' in snap else 0,
            #         co.z if 'z' in snap else 0,
            #     )).length

            # # note: cannot all be snaps, because case above (all near mirror) would have handled it
            # snaps = [self.get_snap_mirror(context, co) for co in self.stroke3D_original]
            # sides = [self.get_mirror_side(co)          for co in self.stroke3D_original]
            # pre, i0, i1, post = [], 0, len(self.stroke3D_original), []
            # if self.snap_mirror_0:
            #     closest = Vector(self.stroke3D_original[0])
            #     for i in range(len(snaps)):
            #         if snaps[i]:
            #             # still snapping
            #             co = self.stroke3D_original[i]
            #             if get_mirror_dist(co, snaps[0]) < get_mirror_dist(closest, snaps[0]):
            #                 closest = co
            #             continue
            #         # found where we don't snap anymore!
            #         pre = [Vector((
            #             0 if 'x' in snaps[0] else closest.x,
            #             0 if 'y' in snaps[0] else closest.y,
            #             0 if 'z' in snaps[0] else closest.z,
            #         ))]
            #         i0 = i
            #         break
            # if self.snap_mirror_1:
            #     closest = Vector(self.stroke3D_original[-1])
            #     for i in range(1, len(snaps)):
            #         if snaps[-i]:
            #             # still snapping
            #             co = self.stroke3D_original[-i]
            #             if get_mirror_dist(co, snaps[-1]) < get_mirror_dist(closest, snaps[-1]):
            #                 closest = co
            #             continue
            #         # found where we don't snap anymore!
            #         post = [Vector((
            #             0 if 'x' in snaps[-1] else closest.x,
            #             0 if 'y' in snaps[-1] else closest.y,
            #             0 if 'z' in snaps[-1] else closest.z,
            #         ))]
            #         i1 = -i + 1
            #         break
            # self.stroke3D = pre + self.stroke3D_original[i0:i1] + post
            # self.stroke = [
            #     location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ co)
            #     for co in self.stroke3D
            # ]
            # return True

        def process_stroke(self, context):
            # # tessellate stroke
            new_stroke = []
            for (co0, co1) in iter_pairs(self.stroke, False):
                new_stroke += [co0]
                d = co1 - co0
                l = d.length
                lt = int(l / 0.5)
                for i in range(lt):
                    co = co0 + d * (i / lt)
                    new_stroke += [co]
            new_stroke += [self.stroke[-1]]
            self.stroke = new_stroke
            self.stroke3D = [raycast_valid_sources(context, pt2D)['co_local'] for pt2D in self.stroke]

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
            self.hit = False
            if not self.mouse: return
            # print(f'RFBrush_Stroke.update {(event.mouse_region_x, event.mouse_region_y)}') #{context.region=} {context.region_data=}')
            hit = raycast_valid_sources(context, self.mouse)
            # print(f'  {hit=}')
            if not hit: return
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

                Drawing.draw2D_linestrip(context, self.stroke, self.stroke_color, width=2, stipple=[5,5])

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

        def get_snap_mirror(self, context, pt3D_local, *, max_dist=None):
            s = set()
            if not pt3D_local or not self.mirror or not self.mirror_clip: return s

            if max_dist is None: max_dist = self.snap_distance
            pt2D = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt3D_local)
            if not pt2D: return s

            if 'x' in self.mirror:
                pt3D_local_mirror = pt3D_local * Vector((-1, 1, 1))
                pt2D_mirror = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt3D_local_mirror)
                if pt2D_mirror:
                    dist = (pt2D - pt2D_mirror).length
                    if dist < max_dist: s.add('x')

            if 'y' in self.mirror:
                pt3D_local_mirror = pt3D_local * Vector((1, -1, 1))
                pt2D_mirror = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt3D_local_mirror)
                if pt2D_mirror:
                    dist = (pt2D - pt2D_mirror).length
                    if dist < max_dist: s.add('y')

            if 'z' in self.mirror:
                pt3D_local_mirror = pt3D_local * Vector((1, 1, -1))
                pt2D_mirror = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt3D_local_mirror)
                if pt2D_mirror:
                    dist = (pt2D - pt2D_mirror).length
                    if dist < max_dist: s.add('z')

            return s

        def draw_postview(self, context):
            if not self.RFCore.is_current_area(context): return
            if context.area not in self.mouse_areas: return
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
