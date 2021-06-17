'''
Copyright (C) 2021 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

import time
import random
from itertools import chain
from mathutils import Vector
from mathutils.geometry import intersect_line_line_2d as intersect_segment_segment_2d

import bpy

from ...config.options import visualization, options
from ...addon_common.common.debug import dprint
from ...addon_common.common.blender import matrix_vector_mult
from ...addon_common.common.decorators import timed_call
from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.maths import Point, Vec, Direction, Normal, Ray, XForm, BBox
from ...addon_common.common.maths import Point2D, Vec2D, Direction2D, Accel2D

from ..rfmesh.rfmesh import RFMesh, RFVert, RFEdge, RFFace
from ..rfmesh.rfmesh import RFSource, RFTarget
from ..rfmesh.rfmesh_render import RFMeshRender


class RetopoFlow_Target:
    '''
    functions to work on target mesh (RFTarget)
    '''

    @profiler.function
    def setup_target(self):
        ''' target is the active object.  must be selected and visible '''
        assert self.tar_object, 'Could not find valid target?'
        self.rftarget = RFTarget.new(self.tar_object, self.unit_scaling_factor)
        opts = visualization.get_target_settings()
        self.rftarget_draw = RFMeshRender.new(self.rftarget, opts)
        self.rftarget_version = None
        self.hide_target()

        self.accel_defer_recomputing = False
        self.accel_recompute = True
        self.accel_target_version = None
        self.accel_view_version = None
        self.accel_vis_verts = None
        self.accel_vis_edges = None
        self.accel_vis_faces = None
        self.accel_vis_accel = None
        self._last_visible_bbox_factor = None
        self._last_visible_dist_offset = None
        self._last_draw_count = -1
        self._draw_count = 0

    def hide_target(self):
        self.rftarget.obj_viewport_hide()
        self.rftarget.obj_render_hide()

    def teardown_target(self):
        # IMPORTANT: changes here should also go in rf_blendersave.backup_recover()
        self.rftarget.obj_viewport_unhide()
        self.rftarget.obj_render_unhide()

    def done_target(self):
        del self.rftarget_draw
        del self.rftarget
        self.tar_object.to_mesh_clear()
        del self.tar_object


    #########################################
    # split target visualization

    def clear_split_target_visualization(self):
        # print(f'clear_split_target_visualization')
        self.rftarget_draw.split_visualization()

    def split_target_visualization(self, verts=None, edges=None, faces=None):
        # print(f'split_target_visualization')
        self.rftarget_draw.split_visualization(verts=verts, edges=edges, faces=faces)

    def split_target_visualization_selected(self):
        # print(f'split_target_visualization_selected')
        self.rftarget_draw.split_visualization(
            verts=self.get_selected_verts(),
            edges=self.get_selected_edges(),
            faces=self.get_selected_faces(),
        )

    def split_target_visualization_visible(self):
        # print(f'split_target_visualization_visible')
        self.rftarget_draw.split_visualization(
            verts=self.visible_verts(),
        )


    #########################################
    # acceleration structures

    def set_accel_defer(self, defer): self.accel_defer_recomputing = defer

    @profiler.function
    def get_vis_accel(self, force=False):
        target_version = self.get_target_version(selection=False)
        view_version = self.get_view_version()

        recompute = self.accel_recompute
        recompute |= target_version != self.accel_target_version
        recompute |= view_version != self.accel_view_version
        recompute |= self.accel_vis_verts is None
        recompute |= self.accel_vis_edges is None
        recompute |= self.accel_vis_faces is None
        recompute |= self.accel_vis_accel is None
        recompute |= options['visible bbox factor'] != self._last_visible_bbox_factor
        recompute |= options['visible dist offset'] != self._last_visible_dist_offset
        recompute &= not self.accel_defer_recomputing
        recompute &= not self._nav and (time.time() - self._nav_time) > 0.25
        recompute &= self._draw_count != self._last_draw_count

        self.accel_recompute = False

        if force or recompute:
            # print(f'RECOMPUTE VIS ACCEL {random.random()}')
            # print(f'  accel recompute: {self.accel_recompute}')
            # print(f'  target change: {target_version != self.accel_target_version}')
            # print(f'  view change: {view_version != self.accel_view_version}  ({self.accel_view_version.get_hash() if self.accel_view_version else None}, {view_version.get_hash()})')
            # print(f'  geom change: {self.accel_vis_verts is None} {self.accel_vis_edges is None} {self.accel_vis_faces is None} {self.accel_vis_accel is None}')
            # print(f'  bbox change: {options["visible bbox factor"] != self._last_visible_bbox_factor}')
            # print(f'  dist offset change: {options["visible dist offset"] != self._last_visible_dist_offset}')
            # print(f'  navigating: {not self._nav}  {time.time() - self._nav_time > 0.25}')
            # print(f'  draw change: {self._draw_count != self._last_draw_count}')
            self.accel_target_version = target_version
            self.accel_view_version = view_version
            self.accel_vis_verts = self.visible_verts()
            self.accel_vis_edges = self.visible_edges(verts=self.accel_vis_verts)
            self.accel_vis_faces = self.visible_faces(verts=self.accel_vis_verts)
            self.accel_vis_accel = Accel2D(self.accel_vis_verts, self.accel_vis_edges, self.accel_vis_faces, self.get_point2D)
            self._last_visible_bbox_factor = options['visible bbox factor']
            self._last_visible_dist_offset = options['visible dist offset']
            self._last_draw_count = self._draw_count
        else:
            self.accel_vis_verts = { bmv for bmv in self.accel_vis_verts if bmv.is_valid } if self.accel_vis_verts is not None else None
            self.accel_vis_edges = { bme for bme in self.accel_vis_edges if bme.is_valid } if self.accel_vis_edges is not None else None
            self.accel_vis_faces = { bmf for bmf in self.accel_vis_faces if bmf.is_valid } if self.accel_vis_faces is not None else None

        return self.accel_vis_accel

    def get_custom_vis_accel(self, selection_only=None, include_verts=True, include_edges=True, include_faces=True):
        vis_verts = self.visible_verts()
        verts = vis_verts                           if include_verts else []
        edges = self.visible_edges(verts=vis_verts) if include_edges else []
        faces = self.visible_faces(verts=vis_verts) if include_faces else []
        if selection_only is not None:
            verts = [v for v in verts if v.select == selection_only]
            edges = [e for e in edges if e.select == selection_only]
            faces = [f for f in faces if f.select == selection_only]
        return Accel2D(verts, edges, faces, self.get_point2D)

    @profiler.function
    def accel_nearest2D_vert(self, point=None, max_dist=None, vis_accel=None, selected_only=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if not vis_accel: vis_accel = self.get_vis_accel()
        if not vis_accel: return None,None

        if not max_dist:
            verts = self.accel_vis_verts
        else:
            max_dist = self.drawing.scale(max_dist)
            verts = vis_accel.get_verts(xy, max_dist)

        if selected_only is not None:
            verts = { bmv for bmv in verts if bmv.select == selected_only }

        return self.rftarget.nearest2D_bmvert_Point2D(xy, self.Point_to_Point2D, verts=verts, max_dist=max_dist)

    @profiler.function
    def accel_nearest2D_edge(self, point=None, max_dist=None, vis_accel=None, selected_only=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if not vis_accel: vis_accel = self.get_vis_accel()
        if not vis_accel: return None,None

        if not max_dist:
            edges = self.accel_vis_edges
        else:
            max_dist = self.drawing.scale(max_dist)
            edges = vis_accel.get_edges(xy, max_dist)

        if selected_only is not None:
            edges = { bme for bme in edges if bme.select == selected_only }

        return self.rftarget.nearest2D_bmedge_Point2D(xy, self.Point_to_Point2D, edges=edges, max_dist=max_dist)

    @profiler.function
    def accel_nearest2D_face(self, point=None, max_dist=None, vis_accel=None, selected_only=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if not vis_accel: vis_accel = self.get_vis_accel()
        if not vis_accel: return None

        if not max_dist:
            faces = self.accel_vis_faces
        else:
            max_dist = self.drawing.scale(max_dist)
            faces = vis_accel.get_faces(xy, max_dist)

        if selected_only is not None:
            faces = { bmf for bmf in faces if bmf.select == selected_only }

        return self.rftarget.nearest2D_bmface_Point2D(self.Vec_forward(), xy, self.Point_to_Point2D, faces=faces) #, max_dist=max_dist)


    #########################################
    # find target entities in screen space

    def get_point2D(self, point):
        if point.is_2D(): return point
        return self.Point_to_Point2D(point)

    @profiler.function
    def nearest2D_vert(self, point=None, max_dist=None, verts=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmvert_Point2D(xy, self.Point_to_Point2D, verts=verts, max_dist=max_dist)

    @profiler.function
    def nearest2D_verts(self, point=None, max_dist:float=10, verts=None):
        xy = self.get_point2D(point or self.actions.mouse)
        max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmverts_Point2D(xy, max_dist, self.Point_to_Point2D, verts=verts)

    @profiler.function
    def nearest2D_edge(self, point=None, max_dist=None, edges=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmedge_Point2D(xy, self.Point_to_Point2D, edges=edges, max_dist=max_dist)

    @profiler.function
    def nearest2D_edges(self, point=None, max_dist:float=10, edges=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmedges_Point2D(xy, max_dist, self.Point_to_Point2D, edges=edges)

    # TODO: implement max_dist
    @profiler.function
    def nearest2D_face(self, point=None, max_dist=None, faces=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmface_Point2D(self.Vec_forward(), xy, self.Point_to_Point2D, faces=faces)

    # TODO: fix this function! Izzza broken
    @profiler.function
    def nearest2D_faces(self, point=None, max_dist:float=10, faces=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmfaces_Point2D(xy, self.Point_to_Point2D, faces=faces)

    ####################
    # REWRITE BELOW!!! #
    ####################

    # def nearest2D_face_Point2D(self, point:Point2D, faces=None):
    #     return self.rftarget.nearest2D_bmface_Point2D(point, self.Point_to_Point2D, faces=faces)

    # def nearest2D_face_point(self, point):
    #     xy = self.get_point2D(point)
    #     return self.rftarget.nearest2D_bmface_Point2D(xy, self.Point_to_Point2D)

    # def nearest2D_face_mouse(self):
    #     return self.nearest2D_face_point(self.actions.mouse)

    # def nearest2D_face_point(self, point):
    #     # if max_dist: max_dist = self.drawing.scale(max_dist)
    #     xy = self.get_point2D(point)
    #     return self.rftarget.nearest2D_bmface_Point2D(xy, self.Point_to_Point2D)


    ########################################
    # find target entities in world space

    def get_point3D(self, point):
        if point.is_3D(): return point
        xyz,_,_,_ = self.raycast_sources_Point2D(point)
        return xyz

    def nearest_vert_point(self, point, verts=None):
        xyz = self.get_point3D(point)
        if xyz is None: return None
        return self.rftarget.nearest_bmvert_Point(xyz, verts=verts)

    def nearest_vert_mouse(self, verts=None):
        return self.nearest_vert_point(self.actions.mouse, verts=verts)

    def nearest_verts_point(self, point, max_dist:float, bmverts=None):
        xyz = self.get_point3D(point)
        if xyz is None: return None
        return self.rftarget.nearest_bmverts_Point(xyz, max_dist, bmverts=bmverts)

    def nearest_verts_mouse(self, max_dist:float):
        return self.nearest_verts_point(self.actions.mouse, max_dist)

    def nearest_edges_Point(self, point, max_dist:float):
        max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest_bmedges_Point(point, max_dist)

    def nearest_edge_Point(self, point:Point, edges=None):
        return self.rftarget.nearest_bmedge_Point(point, edges=edges)


    #######################################
    # get visible geometry

    @profiler.function
    def visible_verts(self, verts=None):
        return self.rftarget.visible_verts(self.is_visible, verts=verts)

    @profiler.function
    def visible_edges(self, verts=None, edges=None):
        return self.rftarget.visible_edges(self.is_visible, verts=verts, edges=edges)

    @profiler.function
    def visible_faces(self, verts=None):
        return self.rftarget.visible_faces(self.is_visible, verts=verts)


    @profiler.function
    def nonvisible_verts(self):
        return self.rftarget.visible_verts(self.is_nonvisible)

    @profiler.function
    def nonvisible_edges(self, verts=None):
        return self.rftarget.visible_edges(self.is_nonvisible, verts=verts)

    @profiler.function
    def nonvisible_faces(self, verts=None):
        return self.rftarget.visible_faces(self.is_nonvisible, verts=verts)


    def iter_verts(self):
        yield from self.rftarget.iter_verts()
    def iter_edges(self):
        yield from self.rftarget.iter_edges()
    def iter_faces(self):
        yield from self.rftarget.iter_faces()

    ########################################
    # symmetry utils

    def apply_symmetry(self):
        self.undo_push('applying symmetry')
        self.rftarget.apply_symmetry(self.nearest_sources_Point)

    @profiler.function
    def clip_pointloop(self, pointloop, connected):
        # assuming loop will cross symmetry line exactly zero or two times
        l2w_point,w2l_point = self.rftarget.xform.l2w_point,self.rftarget.xform.w2l_point
        pointloop = [w2l_point(pt) for pt in pointloop]
        if self.rftarget.mirror_mod.x and any(p.x < 0 for p in pointloop):
            if connected:
                rot_idx = next(i for i,p in enumerate(pointloop) if p.x < 0)
                pointloop = pointloop[rot_idx:] + pointloop[:rot_idx]
            npl = []
            for p0,p1 in iter_pairs(pointloop, connected):
                if p0.x < 0 and p1.x < 0: continue
                elif p0.x == 0: npl += [p0]
                elif p0.x > 0 and p1.x > 0: npl += [p0]
                else:
                    connected = False
                    npl += [p0 + (p1 - p0) * (p0.x / (p0.x - p1.x))]
            if npl:
                npl[0].x = 0
                npl[-1].x = 0
            pointloop = npl
        if self.rftarget.mirror_mod.y and any(p.y > 0 for p in pointloop):
            if connected:
                rot_idx = next(i for i,p in enumerate(pointloop) if p.y > 0)
                pointloop = pointloop[rot_idx:] + pointloop[:rot_idx]
            npl = []
            for p0,p1 in iter_pairs(pointloop, connected):
                if p0.y > 0 and p1.y > 0: continue
                elif p0.y == 0: npl += [p0]
                elif p0.y < 0 and p1.y < 0: npl += [p0]
                else:
                    connected = False
                    npl += [p0 + (p1 - p0) * (p0.y / (p0.y - p1.y))]
            if npl:
                npl[0].y = 0
                npl[-1].y = 0
            pointloop = npl
        if self.rftarget.mirror_mod.z and any(p.z < 0 for p in pointloop):
            if connected:
                rot_idx = next(i for i,p in enumerate(pointloop) if p.z < 0)
                pointloop = pointloop[rot_idx:] + pointloop[:rot_idx]
            npl = []
            for p0,p1 in iter_pairs(pointloop, connected):
                if p0.z < 0 and p1.z < 0: continue
                elif p0.z == 0: npl += [p0]
                elif p0.z > 0 and p1.z > 0: npl += [p0]
                else:
                    connected = False
                    npl += [p0 + (p1 - p0) * (p0.z / (p0.z - p1.z))]
            if npl:
                npl[0].z = 0
                npl[-1].z = 0
            pointloop = npl
        pointloop = [l2w_point(pt) for pt in pointloop]
        return (pointloop, connected)

    def clamp_pointloop(self, pointloop, connected):
        return (pointloop, connected)

    def is_point_on_mirrored_side(self, point):
        p = self.rftarget.xform.w2l_point(point)
        if self.rftarget.mirror_mod.x and p.x < 0: return True
        if self.rftarget.mirror_mod.y and p.y > 0: return True
        if self.rftarget.mirror_mod.z and p.z < 0: return True
        return False

    def symmetry_planes_for_point(self, point):
        point = self.rftarget.xform.w2l_point(point)
        mm = self.rftarget.mirror_mod
        th = mm.symmetry_threshold * self.rftarget.unit_scaling_factor / 2.0
        planes = set()
        if mm.x and abs(point.x) <= th: planes.add('x')
        if mm.y and abs(point.y) <= th: planes.add('y')
        if mm.z and abs(point.z) <= th: planes.add('z')
        return planes

    def mirror_point(self, point):
        p = self.rftarget.xform.w2l_point(point)
        if self.rftarget.mirror_mod.x: p.x = abs(p.x)
        if self.rftarget.mirror_mod.y: p.y = abs(p.y)
        if self.rftarget.mirror_mod.z: p.z = abs(p.z)
        return self.rftarget.xform.l2w_point(p)

    def get_point_symmetry(self, point):
        return self.rftarget.get_point_symmetry(point)

    def snap_to_symmetry(self, point, symmetry, to_world=True, from_world=True):
        return self.rftarget.snap_to_symmetry(point, symmetry, to_world=to_world, from_world=from_world)

    def clamp_point_to_symmetry(self, point):
        return self.rftarget.symmetry_real(point)

    def push_then_snap_all_verts(self):
        self.undo_push('push then snap all verts')
        d = options['push and snap distance']
        for bmv in self.rftarget.get_verts(): bmv.co += bmv.normal * d
        self.rftarget.snap_all_verts(self.nearest_sources_Point)

    def push_then_snap_selected_verts(self):
        self.undo_push('push then snap selected verts')
        d = options['push and snap distance']
        for bmv in self.rftarget.get_verts():
            if bmv.select: bmv.co += bmv.normal * d
        self.rftarget.snap_selected_verts(self.nearest_sources_Point)

    def snap_verts_filter(self, fn_filter):
        self.undo_push('snap filtered verts')
        self.rftarget.snap_verts_filter(self.nearest_source_Point, fn_filter)

    def snap_all_verts(self):
        self.undo_push('snap all verts')
        self.rftarget.snap_all_verts(self.nearest_sources_Point)

    def snap_all_nonhidden_verts(self):
        self.undo_push('snap all visible verts')
        self.rftarget.snap_all_nonhidden_verts(self.nearest_sources_Point)

    def snap_selected_verts(self):
        self.undo_push('snap visible and selected verts')
        self.rftarget.snap_selected_verts(self.nearest_sources_Point)

    def snap_unselected_verts(self):
        self.undo_push('snap visible and unselected verts')
        self.rftarget.snap_unselected_verts(self.nearest_sources_Point)

    def snap_visible_verts(self):
        self.undo_push('snap visible verts')
        nonvisible_verts = self.nonvisible_verts()
        self.rftarget.snap_verts_filter(self.nearest_sources_Point, lambda v: not v.hide and v not in nonvisible_verts)

    def snap_nonvisible_verts(self):
        self.undo_push('snap non-visible verts')
        nonvisible_verts = self.nonvisible_verts()
        self.rftarget.snap_verts_filter(self.nearest_sources_Point, lambda v: not v.hide and v in nonvisible_verts)

    def remove_all_doubles(self):
        self.undo_push('remove all doubles')
        self.rftarget.remove_all_doubles(options['remove doubles dist'])

    def remove_selected_doubles(self):
        self.undo_push('remove selected doubles')
        self.rftarget.remove_selected_doubles(options['remove doubles dist'])

    def flip_face_normals(self):
        self.undo_push('flipping face normals')
        self.rftarget.flip_face_normals()

    #######################################
    # target manipulation functions
    #
    # note: these do NOT dirty the target!
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    def snap_vert(self, vert:RFVert):
        xyz,norm,_,_ = self.nearest_sources_Point(vert.co)
        vert.co = xyz
        vert.normal = norm

    def snap2D_vert(self, vert:RFVert):
        xy = self.Point_to_Point2D(vert.co)
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if xyz is None: return
        vert.co = xyz
        vert.normal = norm

    def offset2D_vert(self, vert:RFVert, delta_xy:Vec2D):
        xy = self.Point_to_Point2D(vert.co) + delta_xy
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if xyz is None: return
        vert.co = xyz
        vert.normal = norm

    def set2D_vert(self, vert:RFVert, xy:Point2D, snap_to_symmetry=None):
        if not vert: return
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if xyz is None: return
        if snap_to_symmetry:
            xyz = self.snap_to_symmetry(xyz, snap_to_symmetry)
        vert.co = xyz
        vert.normal = norm
        return xyz

    def set2D_crawl_vert(self, vert:RFVert, xy:Point2D):
        hits = self.raycast_sources_Point2D_all(xy)
        if not hits: return
        # find closest
        co = vert.co
        p,n,_,_ = min(hits, key=lambda hit:(hit[0]-co).length)
        vert.co = p
        vert.normal = n


    def new_vert_point(self, xyz:Point):
        xyz,norm,_,_ = self.nearest_sources_Point(xyz)
        if not xyz or not norm: return None
        rfvert = self.rftarget.new_vert(xyz, norm)
        d = self.Point_to_Direction(xyz)
        _,n,_,_ = self.raycast_sources_Point(xyz)
        if d and n and n.dot(d) > 0.5: self._detected_bad_normals = True
        # if (d is None or norm.dot(d) > 0.5) and self.is_visible(rfvert.co, bbox_factor_override=0, dist_offset_override=0):
        #     self._detected_bad_normals = True
        return rfvert

    def new2D_vert_point(self, xy:Point2D):
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if not xyz or not norm: return None
        rfvert = self.rftarget.new_vert(xyz, norm)
        if rfvert.normal.dot(self.Point2D_to_Direction(xy)) > 0 and self.is_visible(rfvert.co):
            self._detected_bad_normals = True
        return rfvert

    def new2D_vert_mouse(self):
        return self.new2D_vert_point(self.actions.mouse)

    def new_edge(self, verts):
        return self.rftarget.new_edge(verts)

    def new_face(self, verts):
        return self.rftarget.new_face(verts)

    def bridge_vertloop(self, vloop0, vloop1, connected):
        assert len(vloop0) == len(vloop1), "loops must have same vertex counts"
        faces = []
        for pair0,pair1 in zip(iter_pairs(vloop0, connected), iter_pairs(vloop1, connected)):
            v00,v01 = pair0
            v10,v11 = pair1
            faces += [self.new_face((v00,v01,v11,v10))]
        return faces

    def holes_fill(self, edges, sides):
        self.rftarget.holes_fill(edges, sides)

    def update_verts_faces(self, verts):
        self.rftarget.update_verts_faces(verts)

    def update_face_normal(self, face):
        return self.rftarget.update_face_normal(face)

    def clean_duplicate_bmedges(self, vert):
        return self.rftarget.clean_duplicate_bmedges(vert)

    def remove_duplicate_bmfaces(self, vert):
        return self.rftarget.remove_duplicate_bmfaces(vert)

    ###################################################

    def ensure_lookup_tables(self):
        self.rftarget.ensure_lookup_tables()

    def dirty(self):
        self.rftarget.dirty()

    def dirty_render(self):
        self.rftarget_draw.dirty()

    def get_target_version(self, selection=True):
        return self.rftarget.get_version(selection=selection)

    def get_target_geometry_counts(self):
        return self.rftarget.get_geometry_counts()

    ###################################################

    # determines if any of the edges cross
    # uses face normal to compute 2D projection
    # returns None if any of the points cannot project
    def is_face_twisted(self, bmverts, Point_to_Point2D=None):
        if not Point_to_Point2D:
            # estimate a normal
            v0, v1, v2 = bmverts[:3]
            n = (v1.co-v0.co).cross(v2.co-v0.co)
            t = Direction.uniform()
            y = Direction(t.cross(n))
            x = Direction(y.cross(n))
            Point_to_Point2D = lambda point: Vec2D((x.dot(point), y.dot(point)))
        pts = [Point_to_Point2D(bmv.co) for bmv in bmverts]
        if not all(pts): return None
        l = len(pts)
        for i0 in range(l):
            i1 = (i0 + 1) % l
            p0, p1 = pts[i0], pts[i1]
            for j0 in range(i1 + 1, l):
                j1 = (j0 + 1) % l
                p2, p3 = pts[j0], pts[j1]
                if intersect_segment_segment_2d(p0, p1, p2, p3): return True
        return False


    ###################################################


    def get_quadwalk_edgesequence(self, edge):
        return self.rftarget.get_quadwalk_edgesequence(edge)

    def get_edge_loop(self, edge):
        return self.rftarget.get_edge_loop(edge)

    def get_inner_edge_loop(self, edge):
        return self.rftarget.get_inner_edge_loop(edge)

    def get_face_loop(self, edge):
        return self.rftarget.get_face_loop(edge)

    def is_quadstrip_looped(self, edge):
        return self.rftarget.is_quadstrip_looped(edge)

    def iter_quadstrip(self, edge):
        yield from self.rftarget.iter_quadstrip(edge)

    ###################################################

    def get_selected_verts(self): return self.rftarget.get_selected_verts()
    def get_selected_edges(self): return self.rftarget.get_selected_edges()
    def get_selected_faces(self): return self.rftarget.get_selected_faces()

    def get_unselected_verts(self): return self.rftarget.get_unselected_verts()
    def get_unselected_edges(self): return self.rftarget.get_unselected_edges()
    def get_unselected_faces(self): return self.rftarget.get_unselected_faces()

    def get_hidden_verts(self): return self.rftarget.get_hidden_verts()
    def get_hidden_edges(self): return self.rftarget.get_hidden_edges()
    def get_hidden_faces(self): return self.rftarget.get_hidden_faces()

    def get_revealed_verts(self): return self.rftarget.get_revealed_verts()
    def get_revealed_edges(self): return self.rftarget.get_revealed_edges()
    def get_revealed_faces(self): return self.rftarget.get_revealed_faces()

    def any_verts_selected(self):
        return self.rftarget.any_verts_selected()

    def any_edges_selected(self):
        return self.rftarget.any_edges_selected()

    def any_faces_selected(self):
        return self.rftarget.any_faces_selected()

    def any_selected(self):
        return self.rftarget.any_selected()

    def none_selected(self):
        return not self.any_selected()

    def deselect_all(self):
        self.rftarget.deselect_all()

    def deselect(self, elems, supparts=True, subparts=True):
        self.rftarget.deselect(elems, supparts=supparts, subparts=subparts)

    def select(self, elems, supparts=True, subparts=True, only=True):
        self.rftarget.select(elems, supparts=supparts, subparts=subparts, only=only)

    def select_toggle(self):
        self.rftarget.select_toggle()

    def select_invert(self):
        self.rftarget.select_invert()

    def select_edge_loop(self, edge, only=True, **kwargs):
        eloop,connected = self.get_edge_loop(edge)
        self.rftarget.select(eloop, only=only, **kwargs)

    def select_inner_edge_loop(self, edge, **kwargs):
        eloop,connected = self.get_inner_edge_loop(edge)
        self.rftarget.select(eloop, **kwargs)

    def hide_selected(self):
        self.undo_push('hide selected')
        selected = set()
        for bmv in self.get_selected_verts():
            selected |= {bmv} | set(bmv.link_edges) | set(bmv.link_faces)
        for bme in self.get_selected_edges():
            selected |= {bme} | set(bme.link_faces) | set(bme.verts)
        for bmf in self.get_selected_faces():
            selected |= {bmf} | set(bmf.edges) | set(bmf.verts)
        for e in selected: e.hide = True
        self.dirty()

    def hide_visible(self):
        self.undo_push('hide visible')
        selected = set()
        visible_verts = self.visible_verts()
        visible_edges = self.visible_edges(verts=visible_verts)
        visible_faces = self.visible_faces(verts=visible_verts)
        for bmv in visible_verts:
            selected |= {bmv} | set(bmv.link_edges) | set(bmv.link_faces)
        for bme in visible_edges:
            selected |= {bme} | set(bme.link_faces) | set(bme.verts)
        for bmf in visible_faces:
            selected |= {bmf} | set(bmf.edges) | set(bmf.verts)
        for e in selected: e.hide = True
        self.dirty()

    def hide_nonvisible(self):
        self.undo_push('hide visible')
        selected = set()
        nonvisible_verts = self.nonvisible_verts()
        nonvisible_edges = self.nonvisible_edges(verts=nonvisible_verts)
        nonvisible_faces = self.nonvisible_faces(verts=nonvisible_verts)
        for bmv in nonvisible_verts:
            selected |= {bmv} | set(bmv.link_edges) | set(bmv.link_faces)
        for bme in nonvisible_edges:
            selected |= {bme} | set(bme.link_faces) | set(bme.verts)
        for bmf in nonvisible_faces:
            selected |= {bmf} | set(bmf.edges) | set(bmf.verts)
        for e in selected: e.hide = True
        self.dirty()

    def hide_unselected(self):
        self.undo_push('hide unselected')
        selected = self.get_unselected_verts() | self.get_unselected_edges() | self.get_unselected_faces()
        for e in selected: e.hide = True
        self.dirty()

    def reveal_hidden(self):
        self.undo_push('reveal hidden')
        hidden = self.get_hidden_verts() | self.get_hidden_edges() | self.get_hidden_faces()
        for e in hidden: e.hide = False
        self.dirty()
        return


    #######################################################

    def get_verts_link_edges(self, verts):
        return RFVert.get_link_edges(verts)

    def get_verts_link_faces(self, verts):
        return RFVert.get_link_faces(verts)

    def get_edges_verts(self, edges):
        return RFEdge.get_verts(edges)

    def get_faces_verts(self, faces):
        return RFFace.get_verts(faces)

    #######################################################
    def smooth_edge_flow(self, iterations=10):
        self.undo_push(f'smooth edge flow')

        # get connected loops/strips
        all_edges = set(self.get_selected_edges())
        edge_sets = []
        while all_edges:
            current_set = set()
            working = { next(iter(all_edges)) }
            while working:
                e = working.pop()
                if e not in all_edges: continue
                all_edges.discard(e)
                current_set.add(e)
                v0,v1 = e.verts
                working.update(o for o in v0.link_edges if o.select)
                working.update(o for o in v1.link_edges if o.select)
            edge_sets.append(current_set)

        niters = 1 if len(edge_sets)==1 else iterations

        for i in range(niters):
            for current_set in edge_sets:
                for e in current_set:
                    v0,v1 = e.verts
                    faces0 = e.shared_faces(v0)
                    edges0 = [edge for f in faces0 for edge in f.edges if not edge.select and edge != e and edge.share_vert(e)]
                    verts0 = [edge.other_vert(v0) for edge in edges0]
                    verts0 = [v for v in verts0 if v and v != v1]
                    faces1 = e.shared_faces(v1)
                    edges1 = [edge for f in faces1 for edge in f.edges if not edge.select and edge != e and edge.share_vert(e)]
                    verts1 = [edge.other_vert(v1) for edge in edges0]
                    verts1 = [v for v in verts1 if v and v != v0]
                    if len(verts0) > 1:
                        v0.co = Point.average([v.co for v in verts0])
                        self.snap_vert(v0)
                    if len(verts1) > 1:
                        v1.co = Point.average([v.co for v in verts1])
                        self.snap_vert(v1)

        self.dirty()



    #######################################################

    def update_rot_object(self):
        bbox = self.rftarget.get_selection_bbox()
        if bbox.min == None:
            #bbox = BBox.merge(src.get_bbox() for src in self.rfsources)
            bboxes = []
            for s in self.rfsources:
                verts = [matrix_vector_mult(s.obj.matrix_world, Vector((v[0], v[1], v[2], 1))) for v in s.obj.bound_box]
                verts = [(v[0]/v[3], v[1]/v[3], v[2]/v[3]) for v in verts]
                bboxes.append(BBox(from_coords=verts))
            bbox = BBox.merge(bboxes)
        # print('update_rot_object', bbox)
        diff = bbox.max - bbox.min
        rot_object = bpy.data.objects[options['rotate object']]
        rot_object.location = bbox.min + diff / 2
        rot_object.scale = diff / 2

    #######################################################
    # delete / dissolve

    def delete_dissolve_collapse_option(self, opt):
        if opt is None: return
        if opt[0] == 'Dissolve':
            self.dissolve_option(opt[1])
        elif opt[0] == 'Delete':
            self.delete_option(opt[1])
        elif opt[0] == 'Collapse':
            self.collapse_option(opt[1])
        else:
            return

    def dissolve_option(self, opt):
        sel_verts = self.rftarget.get_selected_verts()
        sel_edges = self.rftarget.get_selected_edges()
        sel_faces = self.rftarget.get_selected_faces()
        try:
            self.undo_push('dissolve %s' % opt)
            if opt == 'Vertices' and sel_verts:
                self.dissolve_verts(sel_verts)
            elif opt == 'Edges' and sel_edges:
                self.dissolve_edges(sel_edges)
            elif opt == 'Faces' and sel_faces:
                self.dissolve_faces(sel_faces)
            elif opt == 'Loops' and sel_edges:
                self.dissolve_edges(sel_edges)
                self.dissolve_verts(self.rftarget.get_selected_verts())
                #self.dissolve_loops()
            self.dirty()
        except RuntimeError as e:
            self.undo_cancel()
            self.alert_user('Error while dissolving:\n' + '\n'.join(e.args))

    def delete_option(self, opt):
        del_empty_edges=True
        del_empty_verts=True
        del_verts=True
        del_edges=True
        del_faces=True

        if opt == 'Vertices':
            pass
        elif opt == 'Edges':
            del_verts = False
        elif opt == 'Faces':
            del_verts = False
            del_edges = False
        elif opt == 'Only Edges & Faces':
            del_verts = False
            del_empty_verts = False
        elif opt == 'Only Faces':
            del_verts = False
            del_edges = False
            del_empty_verts = False
            del_empty_edges = False

        try:
            self.undo_push('delete %s' % opt)
            self.delete_selection(del_empty_edges=del_empty_edges, del_empty_verts=del_empty_verts, del_verts=del_verts, del_edges=del_edges, del_faces=del_faces)
            self.dirty()
        except RuntimeError as e:
            self.undo_cancel()
            self.alert_user('Error while deleting:\n' + '\n'.join(e.args))

    def collapse_option(self, opt):
        del_empty_edges=True
        del_empty_verts=True
        del_verts=True
        del_edges=True
        del_faces=True

        if opt == 'Edges & Faces':
            pass
        else:
            return

        try:
            self.undo_push('collapse %s' % opt)
            self.collapse_edges_faces()
            self.dirty()
        except RuntimeError as e:
            self.undo_cancel()
            self.alert_user('Error while collapsing:\n' + '\n'.join(e.args))

    def collapse_edges_faces(self):
        self.rftarget.collapse_edges_faces(self.nearest_sources_Point)

    def delete_selection(self, del_empty_edges=True, del_empty_verts=True, del_verts=True, del_edges=True, del_faces=True):
        self.rftarget.delete_selection(del_empty_edges=del_empty_edges, del_empty_verts=del_empty_verts, del_verts=del_verts, del_edges=del_edges, del_faces=del_faces)

    def delete_verts(self, verts):
        self.rftarget.delete_verts(verts)

    def delete_edges(self, edges):
        self.rftarget.delete_edges(edges)

    def delete_faces(self, faces, del_empty_edges=True, del_empty_verts=True):
        self.rftarget.delete_faces(faces, del_empty_edges=del_empty_edges, del_empty_verts=del_empty_verts)

    def dissolve_verts(self, verts, use_face_split=False, use_boundary_tear=False):
        self.rftarget.dissolve_verts(verts, use_face_split, use_boundary_tear)

    def dissolve_edges(self, edges, use_verts=True, use_face_split=False):
        self.rftarget.dissolve_edges(edges, use_verts, use_face_split)

    def dissolve_faces(self, faces, use_verts=True):
        self.rftarget.dissolve_faces(faces, use_verts)

    # def find_loops(self, edges):
    #     if not edges: return []
    #     touched,loops = set(),[]

    #     def crawl(v0, edge01, vert_list):
    #         nonlocal edges, touched
    #         # ... -- v0 -- edge01 -- v1 -- edge12 -- ...
    #         #  > came-^-from-^        ^-going-^-to >
    #         vert_list.append(v0)
    #         touched.add(edge01)
    #         v1 = edge01.other_vert(v0)
    #         if v1 == vert_list[0]: return vert_list
    #         next_edges = [e for e in v1.link_edges if e in edges and e != edge01]
    #         if not next_edges: return []
    #         if len(next_edges) == 1: edge12 = next_edges[0]
    #         else: edge12 = next_edge_in_string(edge01, v1)
    #         if not edge12 or edge12 in touched or edge12 not in edges: return []
    #         return crawl(v1, edge12, vert_list)

    #     for edge in edges:
    #         if edge in touched: continue
    #         vert_list = crawl(edge.verts[0], edge, [])
    #         if vert_list:
    #             loops.append(vert_list)

    #     return loops

    # def dissolve_loops(self):
    #     sel_edges = self.get_selected_edges()
    #     sel_loops = self.find_loops(sel_edges)
    #     if not sel_loops:
    #         dprint('Could not find any loops')
    #         return

    #     while sel_loops:
    #         ploop = None
    #         for loop in sel_loops:
    #             sloop = set(loop)
    #             # find a parallel loop next to loop
    #             adj_verts = {e.other_vert(v) for v in loop for e in v.link_edges} - sloop
    #             adj_verts = {v for v in adj_verts if v.is_valid}
    #             parallel_edges = [e for v in adj_verts for e in v.link_edges if e.other_vert(v) in adj_verts]
    #             parallel_loops = self.find_loops(parallel_edges)
    #             if len(parallel_loops) != 2: continue
    #             ploop = parallel_loops[0]
    #             break
    #         if not ploop: break
    #         # merge loop into ploop
    #         eloop = [v0.shared_edge(v1) for v0,v1 in iter_pairs(loop, wrap=True)]
    #         self.deselect(loop)
    #         self.deselect(eloop)
    #         self.deselect([f for e in eloop for f in e.link_faces])
    #         v01 = {v0:next(v1 for v1 in ploop if v0.share_edge(v1)) for v0 in loop}
    #         edges = [v0.shared_edge(v1) for v0,v1 in v01.items()]
    #         self.delete_edges(edges)
    #         touched = set()
    #         for v0,v1 in v01.items():
    #             v1.merge(v0)
    #             touched.add(v1)
    #         for v in touched:
    #             self.clean_duplicate_bmedges(v)
    #         # remove dissolved loop
    #         sel_loops = [l for l in sel_loops if l != loop]
