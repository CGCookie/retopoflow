'''
Copyright (C) 2020 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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
from mathutils.geometry import intersect_line_line_2d
from ...addon_common.common.blender import matrix_vector_mult
from ...addon_common.common.debug import dprint
from ...addon_common.common.maths import Point,Point2D,Vec2D,Vec, Normal, clamp
from ...addon_common.common.bezier import CubicBezierSpline, CubicBezier
from ...addon_common.common.utils import iter_pairs

def is_boundaryedge(bme, only_bmfs):
    return len(set(bme.link_faces) & only_bmfs) == 1
def is_boundaryvert(bmv, only_bmfs):
    return len(set(bmv.link_faces) - only_bmfs) > 0 or bmv.is_boundary

def crawl_strip(bmf0, bme0_2, only_bmfs, stop_bmfs, touched=None):
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
    if touched and bmf1 in touched: return None
    if not touched: touched = set()
    touched.add(bmf0)
    next_part = crawl_strip(bmf1, bme1_2, only_bmfs, stop_bmfs, touched)
    if next_part is None: return None
    return [bmf0] + next_part

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


def process_stroke_filter(stroke, min_distance=1.0, max_distance=2.0):
    ''' filter stroke to pts that are at least min_distance apart '''
    nstroke = stroke[:1]
    for p in stroke[1:]:
        v = p - nstroke[-1]
        l = v.length
        if l < min_distance: continue
        d = v / l
        while l > 0:
            q = nstroke[-1] + d * min(l, max_distance)
            nstroke.append(q)
            l -= max_distance
    return nstroke

def process_stroke_source(stroke, raycast, is_point_on_mirrored_side):
    ''' filter out pts that don't hit source on non-mirrored side '''
    pts = [(pt, raycast(pt)[0]) for pt in stroke]
    return [pt for pt,p3d in pts if p3d and not is_point_on_mirrored_side(p3d)]

def process_stroke_split_at_crossings(stroke):
    strokes = []
    stroke = list(stroke)
    l = len(stroke)
    cstroke = [stroke.pop()]
    while stroke:
        if not stroke[-1]:
            strokes.append(cstroke)
            stroke.pop()
            cstroke = [stroke.pop()]
            continue
        p0,p1 = cstroke[-1],stroke[-1]
        # see if p0-p1 segment crosses any other segment
        for i in range(len(stroke)-3):
            q0,q1 = stroke[i+0],stroke[i+1]
            if q0 is None or q1 is None: continue
            p = intersect_line_line_2d(p0,p1, q0,q1)
            if not p: continue
            if (p-p0).length < 0.000001 or (p-p1).length < 0.000001: continue
            # intersection!
            strokes.append(cstroke + [p])
            cstroke = [p]
            # note: inserting None to indicate broken stroke
            stroke = stroke[:i+1] + [p,None,p] + stroke[i+1:]
            break
        else:
            # no intersections!
            cstroke.append(stroke.pop())
    if cstroke: strokes.append(cstroke)
    return strokes

def process_stroke_get_next(stroke, from_edge, edges2D):
    # returns the next chunk of stroke to be processed
    # stops at...
    # - discontinuity
    # - intersection with self
    # - intersection with edges (ignoring from_edge)
    # - "strong" corners

    cstroke = []
    to_edge = None
    curve_distance, curve_threshold = 25.0, math.cos(60.0 * math.pi/180.0)
    discontinuity_distance = 10.0

    def compute_cosangle_at_index(idx):
        nonlocal stroke
        if idx >= len(stroke): return 1.0
        p0 = stroke[idx]
        for iprev in range(idx-1, -1, -1):
            pprev = stroke[iprev]
            if (p0-pprev).length < curve_distance: continue
            break
        else:
            return 1.0
        for inext in range(idx+1, len(stroke)):
            pnext = stroke[inext]
            if (p0-pnext).length < curve_distance: continue
            break
        else:
            return 1.0
        dprev = (p0 - pprev).normalized()
        dnext = (pnext - p0).normalized()
        cosangle = dprev.dot(dnext)
        return cosangle

    for i0 in range(1, len(stroke)-1):
        i1 = i0 + 1
        p0,p1 = stroke[i0],stroke[i1]

        # check for discontinuity
        if (p0-p1).length > discontinuity_distance:
            dprint('frag: %d %d %d' % (i0, len(stroke), len(stroke)-i1))
            return (from_edge, stroke[:i1], None, False, stroke[i1:])

        # check for self-intersection
        for j0 in range(i0+3, len(stroke)-1):
            q0,q1 = stroke[j0],stroke[j0+1]
            p = intersect_line_line_2d(p0,p1, q0,q1)
            if not p: continue
            dprint('self: %d %d %d' % (i0, len(stroke), len(stroke)-i1))
            return (from_edge, stroke[:i1], None, False, stroke[i1:])

        # check for intersections with edges
        for bme,(q0,q1) in edges2D:
            if bme is from_edge: continue
            p = intersect_line_line_2d(p0,p1, q0,q1)
            if not p: continue
            dprint('edge: %d %d %d' % (i0, len(stroke), len(stroke)-i1))
            return (from_edge, stroke[:i1], bme, True, stroke[i1:])

        # check for strong angles
        cosangle = compute_cosangle_at_index(i0)
        if cosangle > curve_threshold: continue
        # found a strong angle, but there may be a stronger angle coming up...
        minangle = cosangle
        for i0_plus in range(i0+1, len(stroke)):
            p0_plus = stroke[i0_plus]
            if (p0-p0_plus).length > curve_distance: break
            minangle = min(compute_cosangle_at_index(i0_plus), minangle)
            if minangle < cosangle: break
        if minangle < cosangle: continue
        dprint('bend: %d %d %d' % (i0, len(stroke), len(stroke)-i1))
        return (from_edge, stroke[:i1], None, False, stroke[i1:])

    dprint('full: %d %d' % (len(stroke), len(stroke)))
    return (from_edge, stroke, None, False, [])

def process_stroke_get_marks(stroke, at_dists):
    marks = []
    tot_dist = 0
    i_at_dists = 0
    i_stroke = 1
    cp = stroke[0]
    np = stroke[1]
    dist_to_np = (np-cp).length
    dir_to_np = (np-cp).normalized()

    while len(marks) < len(at_dists):
        # can we go to np without passing next mark?
        dratio = (at_dists[i_at_dists] - tot_dist) / dist_to_np
        if dratio > 1:
            tot_dist += dist_to_np
            i_stroke += 1
            if i_stroke == len(stroke): break
            cp,np = np,stroke[i_stroke]
            dist_to_np = (np-cp).length
            dir_to_np = (np-cp).normalized()
            continue
        dist_traveled = dist_to_np * dratio
        cp = cp + dir_to_np * dist_traveled
        marks.append(cp)
        dist_to_np -= dist_traveled
        tot_dist += dist_traveled
        i_at_dists += 1

    while len(marks) < len(at_dists):
        marks.append(stroke[-1])

    return marks

def mark_info(marks, imark):
    imark0 = max(imark-1, 0)
    imark1 = min(imark+1, len(marks)-1)
    #assert imark0!=imark1, '%d %d %d %d' % (marks, imark, imark0, imark1)
    tangent = (marks[imark1] - marks[imark0]).normalized()
    perpendicular = Vec2D((-tangent.y, tangent.x))
    return (marks[imark], tangent, perpendicular)


class RFTool_PolyStrips_Strip:
    def __init__(self, bmf_strip):
        self.bmf_strip = bmf_strip
        self.recompute_curve()
        self.capture_edges()

    def __len__(self): return len(self.bmf_strip)

    def __iter__(self): return iter(self.bmf_strip)

    def __getitem__(self, key): return self.bmf_strip[key]

    def end_faces(self): return (self.bmf_strip[0], self.bmf_strip[-1])

    def recompute_curve(self):
        pts,r = strip_details(self.bmf_strip)
        self.curve = CubicBezier.create_from_points(pts)
        self.curve.tessellate_uniform(lambda p,q:(p-q).length, split=10)

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

            t = self.curve.approximate_t_at_point_tessellation(center, lambda p,q:(p-q).length)
            pos,der = self.curve.eval(t),self.curve.eval_derivative(t).normalized()

            rad = halfdiff.length
            cross = der.cross(norm).normalized()
            off = center - pos
            off_cross,off_der,off_norm = cross.dot(off),der.dot(off),norm.dot(off)
            rot = math.acos(clamp(diffdir.dot(cross), -0.9999999, 0.9999999))
            if diffdir.dot(der) < 0: rot = -rot
            self.bmes += [(bme, t, rad, rot, off_cross, off_der, off_norm)]

    def update(self, nearest_sources_Point, raycast_sources_Point, update_face_normal):
        self.curve.tessellate_uniform(lambda p,q:(p-q).length, split=10)
        length = self.curve.approximate_totlength_tessellation()
        for bme,t,rad,rot,off_cross,off_der,off_norm in self.bmes:
            pos,norm,_,_ = raycast_sources_Point(self.curve.eval(t))
            if not norm: continue
            der = self.curve.eval_derivative(t).normalized()
            cross = der.cross(norm).normalized()
            center = pos + der * off_der + cross * off_cross + norm * off_norm
            rotcross = matrix_vector_mult(Matrix.Rotation(rot, 3, norm), cross).normalized()
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
