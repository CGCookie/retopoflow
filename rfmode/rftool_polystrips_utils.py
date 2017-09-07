import bgl
import bpy
import math
from mathutils import Vector, Matrix
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.bezier import CubicBezierSpline, CubicBezier

def find_opposite_edge(bmf, bme):
    bmes = bmf.edges
    if bmes[0] == bme: return bmes[2]
    if bmes[1] == bme: return bmes[3]
    if bmes[2] == bme: return bmes[0]
    if bmes[3] == bme: return bmes[1]
    assert False

def find_shared_edge(bmf0, bmf1):
    for e0 in bmf0.edges:
        for e1 in bmf1.edges:
            if e0 == e1: return e0
    return None

def is_edge(bme, only_bmfs):
    return len([f for f in bme.link_faces if f in only_bmfs]) == 1

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
    def __init__(self, bmf_strip):
        pts,r = strip_details(bmf_strip)
        self.bmf_strip = bmf_strip
        self.cbs = CubicBezierSpline.create_from_points([pts], r/2000.0)
        self.cbs.tessellate_uniform(lambda p,q:(p-q).length, split=10)
        
        self.bmes = []
        bmes = [(find_shared_edge(bmf0,bmf1), (bmf0.normal+bmf1.normal).normalized()) for bmf0,bmf1 in zip(bmf_strip[:-1], bmf_strip[1:])]
        self.bme0 = find_opposite_edge(bmf_strip[0], bmes[0][0])
        self.bme1 = find_opposite_edge(bmf_strip[-1], bmes[-1][0])
        if len(self.bme0.link_faces) == 1: bmes = [(self.bme0, bmf_strip[0].normal)] + bmes
        if len(self.bme1.link_faces) == 1: bmes = bmes + [(self.bme1, bmf_strip[-1].normal)]
        for bme,norm in bmes:
            if not bme.is_valid: continue
            bmvs = bme.verts
            halfdiff = (bmvs[1].co - bmvs[0].co) / 2.0
            diffdir = halfdiff.normalized()
            center = bmvs[0].co + halfdiff
            
            t = self.cbs.approximate_t_at_point_tessellation(center, lambda p,q:(p-q).length)
            pos,der = self.cbs.eval(t),self.cbs.eval_derivative(t).normalized()
            
            rad = halfdiff.length
            cross = der.cross(norm).normalized()
            off = center - pos
            off_cross = cross.dot(off)
            off_der = der.dot(off)
            rot = math.acos(max(-0.99999,min(0.99999,diffdir.dot(cross))))
            if diffdir.dot(der) < 0: rot = -rot
            self.bmes += [(bme, t, rad, rot, off_cross, off_der)]
    
    def __len__(self): return len(self.cbs)
    
    def __iter__(self): return iter(self.cbs)
    
    def __getitem__(self, key): return self.cbs[key]
    
    def update(self, nearest_sources_Point, raycast_sources_Point, update_face_normal):
        self.cbs.tessellate_uniform(lambda p,q:(p-q).length, split=10)
        length = self.cbs.approximate_totlength_tessellation()
        for bme,t,rad,rot,off_cross,off_der in self.bmes:
            pos,norm,_,_ = raycast_sources_Point(self.cbs.eval(t))
            der = self.cbs.eval_derivative(t).normalized()
            cross = der.cross(norm).normalized()
            center = pos + der * off_der + cross * off_cross
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
