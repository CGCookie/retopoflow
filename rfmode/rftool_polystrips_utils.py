'''
Copyright (C) 2017 CG Cookie
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

import bgl
import bpy
import math
from mathutils import Vector, Matrix
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec, Normal, clamp
from ..common.bezier import CubicBezierSpline, CubicBezier
from ..common.utils import iter_pairs

def is_boundaryedge(bme, only_bmfs):
    return len(set(bme.link_faces) & only_bmfs) == 1
def is_boundaryvert(bmv, only_bmfs):
    return len(set(bmv.link_faces) - only_bmfs) > 0 or bmv.is_boundary

def crawl_strip(bmf0, bme0_2, only_bmfs, stop_bmfs):
    #
    #         *------*------*
    #    ===> | bmf0 | bmf1 | ===>
    #         *------*------*
    #                ^      ^
    # bme0_2=bme1_0 /        \ bme1_2
    #
    bmfs = [bmf for bmf in bme0_2.link_faces if bmf in only_bmfs and bmf != bmf0]
    if len(bmfs) != 1: return [bmf0]
    bmf1 = bmfs[0]
    # rotate bmedges so bme1_0 is where we came from, bme1_2 is where we are going
    bmf1_edges = bmf1.edges
    if   bme0_2 == bmf1_edges[0]: bme1_0,bme1_1,bme1_2,bme1_3 = bmf1_edges
    elif bme0_2 == bmf1_edges[1]: bme1_3,bme1_0,bme1_1,bme1_2 = bmf1_edges
    elif bme0_2 == bmf1_edges[2]: bme1_2,bme1_3,bme1_0,bme1_1 = bmf1_edges
    elif bme0_2 == bmf1_edges[3]: bme1_1,bme1_2,bme1_3,bme1_0 = bmf1_edges
    else: assert False, 'Something very unexpected happened!'
    
    if bmf1 not in only_bmfs: return [bmf0]
    if bmf1 in stop_bmfs: return [bmf0, bmf1]
    return [bmf0] + crawl_strip(bmf1, bme1_2, only_bmfs, stop_bmfs)

def strip_details(strip):
    pts = []
    radius = 0
    for bmf in strip:
        bmvs = bmf.verts
        v = sum((Vector(bmv.co) for bmv in bmvs), Vector()) / 4
        r = ((bmvs[0].co - bmvs[1].co).length + (bmvs[1].co - bmvs[2].co).length + (bmvs[2].co - bmvs[3].co).length + (bmvs[3].co - bmvs[0].co).length) / 8
        if not pts: radius = r
        else: radius = max(radius, r)
        pts += [v]
    if False:
        tesspts = []
        tess_count = 2 if len(strip)>2 else 4
        for pt0,pt1 in zip(pts[:-1],pts[1:]):
            for i in range(tess_count):
                p = i / tess_count
                tesspts += [pt0 + (pt1-pt0)*p]
        pts = tesspts + [pts[-1]]
    return (pts, radius)

def hash_face_pair(bmf0, bmf1):
    return str(bmf0.__hash__()) + str(bmf1.__hash__())



class RFTool_PolyStrips_Strip:
    
    # XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
    # TODO: only one, single bezier curve!!
    # XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
    
    def __init__(self, bmf_strip):
        self.bmf_strip = bmf_strip
        self.recompute_curve()
        self.capture_edges()
    
    def __len__(self): return len(self.cbs)
    
    def __iter__(self): return iter(self.cbs)
    
    def __getitem__(self, key): return self.cbs[key]
    
    def end_faces(self): return (self.bmf_strip[0], self.bmf_strip[-1])
    
    def recompute_curve(self):
        pts,r = strip_details(self.bmf_strip)
        self.cbs = CubicBezierSpline.create_from_points([pts], r/2000.0)
        self.cbs.tessellate_uniform(lambda p,q:(p-q).length, split=10)
    
    def capture_edges(self):
        self.bmes = []
        bmes = [(bmf0.shared_edge(bmf1), Normal(bmf0.normal+bmf1.normal)) for bmf0,bmf1 in iter_pairs(self.bmf_strip, False)]
        self.bme0 = self.bmf_strip[0].opposite_edge(bmes[0][0])
        self.bme1 = self.bmf_strip[-1].opposite_edge(bmes[-1][0])
        if len(self.bme0.link_faces) == 1: bmes = [(self.bme0, self.bmf_strip[0].normal)] + bmes
        if len(self.bme1.link_faces) == 1: bmes = bmes + [(self.bme1, self.bmf_strip[-1].normal)]
        if any(not bme.is_valid for (bme,_) in bmes):
            # filter out invalid edges (see commit 88e4fde4)
            bmes = [(bme,norm) for (bme,norm) in bmes if bme.is_valid]
        for bme,norm in bmes:
            bmvs = bme.verts
            halfdiff = (bmvs[1].co - bmvs[0].co) / 2.0
            diffdir = halfdiff.normalized()
            center = bmvs[0].co + halfdiff
            
            t = self.cbs.approximate_t_at_point_tessellation(center, lambda p,q:(p-q).length)
            pos,der = self.cbs.eval(t),self.cbs.eval_derivative(t).normalized()
            
            rad = halfdiff.length
            cross = der.cross(norm).normalized()
            off = center - pos
            off_cross,off_der,off_norm = cross.dot(off),der.dot(off),norm.dot(off)
            rot = math.acos(clamp(diffdir.dot(cross), -0.9999999, 0.9999999))
            if diffdir.dot(der) < 0: rot = -rot
            self.bmes += [(bme, t, rad, rot, off_cross, off_der, off_norm)]
    
    def update(self, nearest_sources_Point, raycast_sources_Point, update_face_normal):
        self.cbs.tessellate_uniform(lambda p,q:(p-q).length, split=10)
        length = self.cbs.approximate_totlength_tessellation()
        for bme,t,rad,rot,off_cross,off_der,off_norm in self.bmes:
            pos,norm,_,_ = raycast_sources_Point(self.cbs.eval(t))
            if not norm: continue
            der = self.cbs.eval_derivative(t).normalized()
            cross = der.cross(norm).normalized()
            center = pos + der * off_der + cross * off_cross + norm * off_norm
            rotcross = (Matrix.Rotation(rot, 3, norm) * cross).normalized()
            p0 = center - rotcross * rad
            p1 = center + rotcross * rad
            bmv0,bmv1 = bme.verts
            v0,_,_,_ = raycast_sources_Point(p0)
            v1,_,_,_ = raycast_sources_Point(p1)
            if not v0: v0,_,_,_ = nearest_sources_Point(p0)
            if not v1: v1,_,_,_ = nearest_sources_Point(p1)
            bmv0.co = v0
            bmv1.co = v1
        for bmf in self.bmf_strip:
            update_face_normal(bmf)
