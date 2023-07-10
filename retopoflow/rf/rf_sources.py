'''
Copyright (C) 2023 CG Cookie
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

import bpy
import time
from math import isinf, isnan

from ...config.options import visualization, options
from ...addon_common.common.maths import BBox
from ...addon_common.common.profiler import profiler, time_it
from ...addon_common.common.debug import dprint
from ...addon_common.common.maths import Point, Vec, Direction, Normal, Ray, XForm, Plane
from ...addon_common.common.maths import Point2D, Accel2D
from ...addon_common.common.timerhandler import CallGovernor

from ..rfmesh.rfmesh import RFSource
from ..rfmesh.rfmesh_render import RFMeshRender


class RetopoFlow_Sources:
    '''
    functions to work on all source meshes (RFSource)
    '''

    @profiler.function
    def setup_sources(self):
        ''' find all valid source objects, which are mesh objects that are visible and not active '''
        print('  rfsources...')
        self.rfsources = [RFSource.new(src) for src in self.get_sources()]
        print('  bboxes...')
        self.sources_bbox = BBox.merge(rfs.get_bbox() for rfs in self.rfsources)
        dprint('%d sources found' % len(self.rfsources))
        opts = visualization.get_source_settings()
        print('  drawing...')
        self.rfsources_draw = [RFMeshRender.new(rfs, opts) for rfs in self.rfsources]
        dprint('%d sources found' % len(self.rfsources))
        print('  done!')
        self._detected_bad_normals = False
        self._warned_bad_normals = False

    def done_sources(self):
        for rfs in self.rfsources:
            rfs.obj.to_mesh_clear()
        del self.sources_bbox
        del self.rfsources_draw
        del self.rfsources

    @profiler.function
    def setup_sources_symmetry(self):
        xyplane,xzplane,yzplane = self.rftarget.get_xy_plane(),self.rftarget.get_xz_plane(),self.rftarget.get_yz_plane()
        w2l_point = self.rftarget.w2l_point
        rfsources_xyplanes = [e for rfs in self.rfsources for e in rfs.plane_intersection(xyplane)]
        rfsources_xzplanes = [e for rfs in self.rfsources for e in rfs.plane_intersection(xzplane)]
        rfsources_yzplanes = [e for rfs in self.rfsources for e in rfs.plane_intersection(yzplane)]

        def gen_accel(edges, Point_to_Point2D):
            nonlocal w2l_point
            edges = [(w2l_point(v0), w2l_point(v1)) for (v0, v1) in edges]
            return Accel2D.simple_edges('RFSource edges', edges, Point_to_Point2D)

        self.rftarget.set_symmetry_accel(
            gen_accel(rfsources_xyplanes, lambda p:[Point2D((p.x,p.y))]),
            gen_accel(rfsources_xzplanes, lambda p:[Point2D((p.x,p.z))]),
            gen_accel(rfsources_yzplanes, lambda p:[Point2D((p.y,p.z))]),
        )

    ###################################################
    # snap settings

    snap_sources = {}

    @staticmethod
    def get_source_snap(name):
        return RFContext_Sources.snap_sources.get(name, True)

    @staticmethod
    def set_source_snap(name, val):
        RFContext_Sources.snap_sources[name] = val

    def get_rfsource_snap(self, rfsource):
        n = rfsource.get_obj_name()
        return self.snap_sources.get(n, True)

    ###################################################
    # ray casting functions

    def raycast_sources_Ray(self, ray:Ray, *, correct_mirror=True, ignore_backface=None):
        ignore_backface = self.ray_ignore_backface_sources() if ignore_backface is None else ignore_backface
        bp,bn,bi,bd,bo = None,None,None,None,None
        for rfsource in self.rfsources:
            if not self.get_rfsource_snap(rfsource): continue
            hp,hn,hi,hd = rfsource.raycast(ray, ignore_backface=ignore_backface)
            if hp is None:     continue     # did we miss?
            if isinf(hd):      continue     # is distance infinitely far away?
            if isnan(hd):      continue     # is distance NaN?  (issue #1062)
            if bp and bd < hd: continue     # have we seen a closer hit already?
            bp,bn,bi,bd,bo = hp,hn,hi,hd,rfsource
        if correct_mirror and bp and bn: bp, bn = self.mirror_point_normal(bp, bn)
        return (bp,bn,bi,bd)

    def raycast_sources_Ray_all(self, ray:Ray):
        return [
            hit
            for rfsource in self.rfsources
            for hit in rfsource.raycast_all(ray)
            if self.get_rfsource_snap(rfsource)
        ]

    def raycast_sources_Point2D(self, xy:Point2D, *, correct_mirror=True, ignore_backface=None):
        if xy is None: return None,None,None,None
        return self.raycast_sources_Ray(self.Point2D_to_Ray(xy, min_dist=self.drawing.space.clip_start), correct_mirror=correct_mirror, ignore_backface=ignore_backface)

    def raycast_sources_Point2D_all(self, xy:Point2D):
        if xy is None: return None,None,None,None
        return self.raycast_sources_Ray_all(self.Point2D_to_Ray(xy, min_dist=self.drawing.space.clip_start))

    def raycast_sources_mouse(self, *, correct_mirror=True, ignore_backface=None):
        return self.raycast_sources_Point2D(self.actions.mouse, correct_mirror=correct_mirror, ignore_backface=ignore_backface)

    def raycast_sources_Point(self, xyz:Point, *, correct_mirror=True, ignore_backface=None):
        if xyz is None: return None,None,None,None
        xy = self.Point_to_Point2D(xyz)
        return self.raycast_sources_Point2D(xy, correct_mirror=correct_mirror, ignore_backface=ignore_backface)


    ###################################################
    # nearest surface point (snapping) functions

    def nearest_sources_Point(self, point:Point, max_dist=float('inf')): #sys.float_info.max):
        bp,bn,bi,bd = None,None,None,None
        for rfsource in self.rfsources:
            if not self.get_rfsource_snap(rfsource): continue
            hp,hn,hi,hd = rfsource.nearest(point, max_dist=max_dist)
            if bp is None or (hp is not None and hd < bd):
                bp,bn,bi,bd = hp,hn,hi,hd
        return (bp,bn,bi,bd)


    ###################################################
    # plane intersection

    def plane_intersection_crawl(self, ray:Ray, plane:Plane, walk_to_plane=False):
        bp,bn,bi,bd,bo = None,None,None,None,None
        for rfsource in self.rfsources:
            if not self.get_rfsource_snap(rfsource): continue
            hp,hn,hi,hd = rfsource.raycast(ray)
            if bp is None or (hp is not None and hd < bd):
                bp,bn,bi,bd,bo = hp,hn,hi,hd,rfsource
        if not bo: return []
        return bo.plane_intersection_crawl(ray, plane, walk_to_plane=walk_to_plane)

    def plane_intersections_crawl(self, plane:Plane):
        return [crawl for rfsource in self.rfsources for crawl in rfsource.plane_intersections_crawl(plane) if self.get_rfsource_snap(rfsource)]


    ###################################################
    # visibility testing

    def ray_ignore_backface_sources(self):
        return self.shading_backface_get()

    def _raycast_hit_any(self, ray, ignore_backface):
        return any(
            rfsource.raycast_hit(ray, ignore_backface=ignore_backface)
            for rfsource in self.rfsources if self.get_rfsource_snap(rfsource)
        )

    def gen_is_visible(self, *, bbox_factor_override=None, dist_offset_override=None, occlusion_test_override=None, backface_test_override=None):
        backface_test  = options['selection backface test']  if backface_test_override  is None else backface_test_override
        occlusion_test = options['selection occlusion test'] if occlusion_test_override is None else occlusion_test_override
        bbox_factor    = options['visible bbox factor']      if bbox_factor_override    is None else bbox_factor_override
        dist_offset    = options['visible dist offset']      if dist_offset_override    is None else dist_offset_override
        max_dist_offset = self.sources_bbox.get_min_dimension() * bbox_factor + dist_offset
        Point_to_Point2D = self.Point_to_Point2D
        Point_to_Ray = self.Point_to_Ray
        raycast_hit_any = self._raycast_hit_any
        ray_ignore_backface_sources = self.ray_ignore_backface_sources()
        area_x, area_y = self.actions.size.x, self.actions.size.y
        clip_start = self.drawing.space.clip_start
        vec_fwd = self.Vec_forward()

        def is_inside_area(point):
            return (p2D := Point_to_Point2D(point)) and (0 <= p2D.x <= area_x) and (0 <= p2D.y <= area_y)
        def is_facing_correctly(normal):
            return not backface_test or (not normal) or vec_fwd.dot(normal) <= 0
        def is_not_occluded(point):
            return not occlusion_test or ((ray := Point_to_Ray(point, min_dist=clip_start, max_dist_offset=-max_dist_offset)) and not raycast_hit_any(ray, ray_ignore_backface_sources))

        def is_visible(point:Point, normal:Normal=None):
            return is_inside_area(point) and is_facing_correctly(normal) and is_not_occluded(point)

        return is_visible

    def gen_is_nonvisible(self, *args, **kwargs):
        is_visible = self.gen_is_visible(*args, **kwargs)
        def is_nonvisible(*args, **kwargs):
            return not is_visible(*args, **kwargs)
        return is_nonvisible

    def is_visible(self, point:Point, normal:Normal=None, bbox_factor_override=None, dist_offset_override=None, occlusion_test_override=None, backface_test_override=None):
        backface_test  = options['selection backface test']  if backface_test_override  is None else backface_test_override
        occlusion_test = options['selection occlusion test'] if occlusion_test_override is None else occlusion_test_override
        bbox_factor    = options['visible bbox factor']      if bbox_factor_override    is None else bbox_factor_override
        dist_offset    = options['visible dist offset']      if dist_offset_override    is None else dist_offset_override
        max_dist_offset = self.sources_bbox.get_min_dimension() * bbox_factor + dist_offset

        # find where point projects to screen
        p2D = self.Point_to_Point2D(point)
        if not p2D: return False
        if not (0 <= p2D.x <= self.actions.size.x) or not (0 <= p2D.y <= self.actions.size.y): return False

        # compute ray through projection point
        ray = self.Point_to_Ray(point, min_dist=self.drawing.space.clip_start, max_dist_offset=-max_dist_offset)
        if not ray: return False

        # run backfacing test if applicable
        if backface_test and normal and normal.dot(ray.d) >= 0: return False

        # run occlusion test if applicable
        if occlusion_test and self._raycast_hit_any(ray, self.ray_ignore_backface_sources()): return False

        # point is visible!
        return True

    def is_nonvisible(self, *args, **kwargs):
        return not self.is_visible(*args, **kwargs)

    def visibility_preset_normal(self):
        options['visible bbox factor'] = 0.001
        options['visible dist offset'] = 0.1
        self.get_accel_visible()

    def visibility_preset_tiny(self):
        options['visible bbox factor'] = 0.0
        options['visible dist offset'] = 0.0004
        self.get_accel_visible()


    ###################################################
    # normal check

    @CallGovernor.limit(time_limit=0.25)
    def normal_check(self):
        if not options['warning normal check']: return  # user wishes not to do this check :(
        if self._warned_bad_normals: return             # already warned this session
        if not self._detected_bad_normals: return       # no bad normals detected

        # _,hn,_,_ = self.raycast_sources_mouse()
        # vd = self.Point2D_to_Direction(self.actions.mouse)
        # if not hn: return                               # did not hit source mesh
        # if vd.dot(hn) < 0: return                       # facing correct direction (opposite of viewing direction)

        self._warned_bad_normals = True                 # only warn once

        message = ['\n'.join([
            'One of the sources has inward facing normals.',
            'Inward facing normals will cause new geometry to be created incorrectly or to prevent it from being selected.',
            '',
            'Possible fix: exit RetopoFlow, switch to Edit Mode on the source mesh, recalculate normals, then try RetopoFlow again.',
        ])]

        self.alert_user(
            title='Source(s) with inverted normals',
            message='\n\n'.join(message),
            level='warning',
        )

