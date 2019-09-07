'''
Copyright (C) 2019 CG Cookie
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

from ...config.options import visualization
from ...addon_common.common.maths import BBox
from ...addon_common.common.profiler import profiler
from ...addon_common.common.debug import dprint
from ...addon_common.common.maths import Point, Vec, Direction, Normal, Ray, XForm, Plane
from ...addon_common.common.maths import Point2D, Accel2D

from ..rfmesh.rfmesh import RFSource
from ..rfmesh.rfmesh_render import RFMeshRender


class RetopoFlow_Sources:
    '''
    functions to work on all RFSource objects
    '''

    @profiler.profile
    def setup_sources(self):
        ''' find all valid source objects, which are mesh objects that are visible and not active '''
        self.rfsources = [RFSource.new(src) for src in self.get_sources()]
        self.sources_bbox = BBox.merge([rfs.get_bbox() for rfs in self.rfsources])
        dprint('%d sources found' % len(self.rfsources))
        opts = visualization.get_source_settings()
        self.rfsources_draw = [RFMeshRender.new(rfs, opts) for rfs in self.rfsources]

    @profiler.profile
    def setup_sources_symmetry(self):
        xyplane,xzplane,yzplane = self.rftarget.get_xy_plane(),self.rftarget.get_xz_plane(),self.rftarget.get_yz_plane()
        w2l_point = self.rftarget.w2l_point
        rfsources_xyplanes = [e for rfs in self.rfsources for e in rfs.plane_intersection(xyplane)]
        rfsources_xzplanes = [e for rfs in self.rfsources for e in rfs.plane_intersection(xzplane)]
        rfsources_yzplanes = [e for rfs in self.rfsources for e in rfs.plane_intersection(yzplane)]

        def gen_accel(edges, Point_to_Point2D):
            nonlocal w2l_point
            edges = [(w2l_point(v0), w2l_point(v1)) for (v0, v1) in edges]
            return Accel2D.simple_edges(edges, Point_to_Point2D)

        self.rftarget.set_symmetry_accel(
            gen_accel(rfsources_xyplanes, lambda p:Point2D((p.x,p.y))),
            gen_accel(rfsources_xzplanes, lambda p:Point2D((p.x,p.z))),
            gen_accel(rfsources_yzplanes, lambda p:Point2D((p.y,p.z))),
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

    def raycast_sources_Ray(self, ray:Ray):
        bp,bn,bi,bd = None,None,None,None
        for rfsource in self.rfsources:
            if not self.get_rfsource_snap(rfsource): continue
            hp,hn,hi,hd = rfsource.raycast(ray)
            if bp is None or (hp is not None and hd < bd):
                bp,bn,bi,bd = hp,hn,hi,hd
        return (bp,bn,bi,bd)

    def raycast_sources_Ray_all(self, ray:Ray):
        return [hit for rfsource in self.rfsources for hit in rfsource.raycast_all(ray) if self.get_rfsource_snap(rfsource)]

    def raycast_sources_Point2D(self, xy:Point2D):
        if xy is None: return None,None,None,None
        return self.raycast_sources_Ray(self.Point2D_to_Ray(xy))

    def raycast_sources_Point2D_all(self, xy:Point2D):
        if xy is None: return None,None,None,None
        return self.raycast_sources_Ray_all(self.Point2D_to_Ray(xy))

    def raycast_sources_mouse(self):
        return self.raycast_sources_Point2D(self.actions.mouse)

    def raycast_sources_Point(self, xyz:Point):
        if xyz is None: return None,None,None,None
        xy = self.Point_to_Point2D(xyz)
        return self.raycast_sources_Point2D(xy)


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

    def plane_intersection_crawl(self, ray:Ray, plane:Plane, walk=False):
        bp,bn,bi,bd,bo = None,None,None,None,None
        for rfsource in self.rfsources:
            if not self.get_rfsource_snap(rfsource): continue
            hp,hn,hi,hd = rfsource.raycast(ray)
            if bp is None or (hp is not None and hd < bd):
                bp,bn,bi,bd,bo = hp,hn,hi,hd,rfsource
        if not bp: return []

        if walk:
            return bo.plane_intersection_walk_crawl(ray, plane)
        else:
            return bo.plane_intersection_crawl(ray, plane)

    def plane_intersections_crawl(self, plane:Plane):
        return [crawl for rfsource in self.rfsources for crawl in rfsource.plane_intersections_crawl(plane) if self.get_rfsource_snap(rfsource)]


    ###################################################
    # visibility testing

    @profiler.profile
    def is_visible(self, point:Point, normal:Normal):
        p2D = self.Point_to_Point2D(point)
        if not p2D: return False
        if p2D.x < 0 or p2D.x > self.actions.size[0]: return False
        if p2D.y < 0 or p2D.y > self.actions.size[1]: return False
        max_dist_offset = self.sources_bbox.get_min_dimension()*0.01 + 0.0008
        ray = self.Point_to_Ray(point, max_dist_offset=-max_dist_offset)
        if not ray: return False
        if normal and normal.dot(ray.d) >= 0: return False
        return not any(rfsource.raycast_hit(ray) for rfsource in self.rfsources if self.get_rfsource_snap(rfsource))


