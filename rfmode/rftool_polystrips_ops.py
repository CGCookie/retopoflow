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
from mathutils.geometry import intersect_point_tri_2d, intersect_point_tri_2d
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec,Accel2D
from ..common.bezier import CubicBezierSpline, CubicBezier
from ..common.ui import UI_Image
from ..common.utils import iter_pairs
from ..lib.common_utilities import showErrorMessage, dprint
from ..lib.classes.logging.logger import Logger

from .rftool_polystrips_utils import (
    RFTool_PolyStrips_Strip,
    hash_face_pair,
    strip_details,
    crawl_strip,
    is_boundaryvert, is_boundaryedge,
    process_stroke_filter, process_stroke_onlyhit,
    process_stroke_get_next, process_stroke_get_marks,
    mark_info,
    )

class RFTool_PolyStrips_Ops:
    
    @RFTool.dirty_when_done
    def stroke(self):
        # called when artist finishes a stroke
        self.stroke_new()
        #self.stroke_old()
    
    def stroke_new(self):
        # XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
        # todo: stroke may fall off the source!! :(
        # XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
        
        radius = self.rfwidget.size
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        Point2D_to_Ray = self.rfcontext.Point2D_to_Ray
        nearest_sources_Point = self.rfcontext.nearest_sources_Point
        raycast = self.rfcontext.raycast_sources_Point2D
        vis_verts = self.rfcontext.visible_verts()
        vis_edges = self.rfcontext.visible_edges(verts=vis_verts)
        vis_faces = self.rfcontext.visible_faces(verts=vis_verts)
        vis_edges2D,vis_faces2D = [],[]
        new_geom = []
        
        def add_edge(bme): vis_edges2D.append((bme, [Point_to_Point2D(bmv.co) for bmv in bme.verts]))
        def add_face(bmf): vis_faces2D.append((bmf, [Point_to_Point2D(bmv.co) for bmv in bmf.verts]))
        
        for bme in vis_edges: add_edge(bme)
        for bmf in vis_faces: add_face(bmf)
        
        def intersect_face(pt):
            # todo: rewrite! inefficient!
            nonlocal vis_faces2D
            for f,vs in vis_faces2D:
                v0 = vs[0]
                for v1,v2 in iter_pairs(vs[1:], False):
                    if intersect_point_tri_2d(pt, v0, v1, v2): return f
            return None
        
        def create_vert(p2D_init, dist):
            p = raycast(p2D_init)[0]
            if p is not None: return p
            r = Point2D_to_Ray(p2D_init)
            p = nearest_sources_Point(r.eval(dist))[0]
            return p
        
        def create_edge(center, tangent, mult, perpendicular):
            nonlocal new_geom
            bmv0,bmv1 = None,None
            d,mmult = None,mult
            while not d:
                p = center + tangent * mmult
                d = raycast(p)[3]
                mmult -= 0.1
            p0 = create_vert(center + tangent * mult + perpendicular * radius, d)
            p1 = create_vert(center + tangent * mult - perpendicular * radius, d)
            bmv0 = self.rfcontext.new_vert_point(p0)
            bmv1 = self.rfcontext.new_vert_point(p1)
            bme = self.rfcontext.new_edge([bmv0,bmv1])
            add_edge(bme)
            new_geom += [bme]
            return bme
        
        def create_face(bme01, bme23):
            #  0  3      0--3
            #  |  |  ->  |  |
            #  1  2      1--2
            nonlocal new_geom
            bmv0,bmv1 = bme01.verts
            bmv2,bmv3 = bme23.verts
            if bme01.vector().dot(bme23.vector()) > 0: bmv2,bmv3 = bmv3,bmv2
            bmf = self.rfcontext.new_face([bmv0,bmv1,bmv2,bmv3])
            bme12 = bmv1.shared_edge(bmv2)
            bme30 = bmv3.shared_edge(bmv0)
            add_edge(bme12)
            add_edge(bme30)
            add_face(bmf)
            new_geom += [bme12, bme30, bmf]
            return bmf
        
        self.rfcontext.undo_push('stroke')
        
        stroke = list(self.rfwidget.stroke2D)
        # filter stroke down where each pt is at least 1px away to eliminate local wiggling
        stroke = process_stroke_filter(stroke)
        stroke = process_stroke_onlyhit(stroke, self.rfcontext.raycast_sources_Point2D)
        
        from_edge = None
        while len(stroke) > 2:
            # get stroke segment to work on
            from_edge,cstroke,to_edge,cont,stroke = process_stroke_get_next(stroke, from_edge, vis_edges2D)
            
            # discard stroke segment if it lies in a face
            if intersect_face(cstroke[1]):
                dprint('stroke is on face (1)')
                from_edge = to_edge
                continue
            if intersect_face(cstroke[-2]):
                dprint('stroke is on face (-2)')
                from_edge = to_edge
                continue
            
            # estimate length of stroke (used with radius to determine num of quads)
            stroke_len = sum((p0-p1).length for (p0,p1) in iter_pairs(cstroke,False))
            
            # marks start and end at center of quad, and alternate with
            # edge and face, each approx radius distance apart
            # +---+---+---+---+---+
            # |   |   |   |   |   |
            # +---+---+---+---+---+
            #   ^ ^ ^ ^ ^ ^ ^ ^ ^  <-----marks (nmarks: 9, nquads: 5)
            #     ^ ^ ^ ^ ^ ^ ^ ^  <- if from_edge not None
            #   ^ ^ ^ ^ ^ ^ ^ ^    <- if to_edge not None
            #     ^ ^ ^ ^ ^ ^ ^    <- if from_edge and to_edge are not None
            # mark counts:
            #     min marks = 3   [ | ]    (2 quads)
            #     marks = 5      [ | | ]   (3 quads)
            #     marks = 7     [ | | | ]  (4 quads)
            #     marks must be odd
            # if from_edge is not None, then stroke starts at edge
            # if to_edge is not None, then stroke ends at edge
            markoff0 = 0 if from_edge is None else 1
            markoff1 = 0 if to_edge   is None else 1
            nmarks = int(math.ceil(stroke_len / radius))        # approx num of marks
            nmarks = nmarks + (1 - ((nmarks+markoff0+markoff1) % 2))  # make sure odd count
            nmarks = max(nmarks, 3-markoff0-markoff1)           # min marks = 3
            # marks are found at dists along stroke
            at_dists = [stroke_len*i/(nmarks-1) for i in range(nmarks)]
            # compute marks
            marks = process_stroke_get_marks(cstroke, at_dists)
            
            # compute number of quads
            nquads = int(((nmarks-markoff0-markoff1) + 1) / 2)
            dprint('nmarks = %d, markoff0 = %d, markoff1 = %d, nquads = %d' % (nmarks, markoff0, markoff1, nquads))
            
            if from_edge and to_edge and nquads == 1:
                bmv0,bmv1 = from_edge.verts
                if bmv0 in to_edge.verts or bmv1 in to_edge.verts:
                    self.rfcontext.alert_user(title='PolyStrips', message='Cannot create short strip between edges that share a vertex')
                    self.rfcontext.undo_cancel()
                    return
            
            # add edges
            if from_edge is None:
                # create from_edge
                dprint('creating from_edge')
                pt,tn,pe = mark_info(marks, 0)
                from_edge = create_edge(pt, -tn, radius, pe)
            else:
                new_geom += list(from_edge.link_faces)
            
            if to_edge is None:
                dprint('creating to_edge')
                pt,tn,pe = mark_info(marks, nmarks-1)
                to_edge = create_edge(pt, tn, radius, pe)
            else:
                new_geom += list(to_edge.link_faces)
            
            for iquad in range(1, nquads):
                #print('creating edge')
                pt,tn,pe = mark_info(marks, iquad*2+markoff0-1)
                bme = create_edge(pt, tn, 0.0, pe)
                bmf = create_face(from_edge, bme)
                from_edge = bme
            bmf = create_face(from_edge, to_edge)
            
            from_edge = to_edge if cont else None
        
        self.rfcontext.select(new_geom, supparts=False)
    
    def stroke_old(self):
        radius = self.rfwidget.get_scaled_size()
        stroke2D = list(self.rfwidget.stroke2D)
        bmfaces = []
        all_bmfaces = []
        
        if len(stroke2D) < 10: return
        
        self.rfcontext.undo_push('stroke')
        
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        vis_verts = self.rfcontext.visible_verts()
        vis_edges = self.rfcontext.visible_edges(verts=vis_verts)
        vis_faces = self.rfcontext.visible_faces(verts=vis_verts)
        vis_faces2D = [(bmf, [Point_to_Point2D(bmv.co) for bmv in bmf.verts]) for bmf in vis_faces]
        
        def get_state(point:Point2D):
            nonlocal vis_faces2D
            point3D = self.rfcontext.get_point3D(point)
            if not point3D: return ('off', None)
            if self.rfcontext.is_point_on_mirrored_side(point3D): return ('off',None)
            for bmf,cos in vis_faces2D:
                co0 = cos[0]
                for co1,co2 in zip(cos[1:-1],cos[2:]):
                    if intersect_point_tri_2d(point, co0, co1, co2):
                        return ('tar', bmf)
            return ('src', None)
        def next_state():
            nonlocal stroke2D
            pt = stroke2D.pop()
            state,face = get_state(pt)
            return (pt,state,face)
        
        def merge(p0, p1, q0, q1):
            nonlocal bmfaces
            dp = p1.co - p0.co
            dq = q1.co - q0.co
            if dp.dot(dq) < 0: p0,p1 = p1,p0
            q0.merge(p0)
            q1.merge(p1)
            mapping = self.rfcontext.clean_duplicate_bmedges(q0)
            bmfaces = [mapping.get(f, f) for f in bmfaces]
            mapping = self.rfcontext.clean_duplicate_bmedges(q1)
            bmfaces = [mapping.get(f, f) for f in bmfaces]
        
        def insert(cb, bme_start, bme_end):
            nonlocal bmfaces
            if bme_start and bme_start == bme_end: return
            if bme_start and bme_end:
                bmv0,bmv1 = bme_start.verts
                bmv2,bmv3 = bme_end.verts
                if bmv0 == bmv2 or bmv0 == bmv3 or bmv1 == bmv2 or bmv1 == bmv3: return
            
            length = cb.approximate_length_uniform(lambda p,q: (p-q).length)
            steps = math.floor((length / radius) / 2)
            
            if steps == 0:
                if bme_start == None or bme_end == None: return
                bmv0,bmv1 = bme_start.verts
                bmv2,bmv3 = bme_end.verts
                dir01,dir23 = bmv1.co - bmv0.co, bmv3.co - bmv2.co
                if dir01.dot(dir23) > 0:
                    bmfaces.append(self.rfcontext.new_face([bmv0,bmv1,bmv3,bmv2]))
                else:
                    bmfaces.append(self.rfcontext.new_face([bmv0,bmv1,bmv2,bmv3]))
                return
            
            intervals = [(i/steps)*length for i in range(steps+1)]
            ts = cb.approximate_ts_at_intervals_uniform(intervals, lambda p,q: (p-q).length)
            
            fp0,fp1 = None,None
            lp2,lp3 = None,None
            p0,p1,p2,p3 = None,None,None,None
            for t in ts:
                center,normal,_,_ = self.rfcontext.nearest_sources_Point(cb.eval(t))
                direction = cb.eval_derivative(t).normalized()
                cross = normal.cross(direction).normalized()
                back,front = center - direction * radius, center + direction * radius
                loc0,loc1 = back  - cross * radius, back  + cross * radius
                loc2,loc3 = front + cross * radius, front - cross * radius
                if p0 is None:
                    p0 = self.rfcontext.new_vert_point(loc0)
                    p1 = self.rfcontext.new_vert_point(loc1)
                else:
                    p0.co = (Vector(p0.co) + Vector(loc0)) * 0.5
                    p1.co = (Vector(p1.co) + Vector(loc1)) * 0.5
                p2 = self.rfcontext.new_vert_point(loc2)
                p3 = self.rfcontext.new_vert_point(loc3)
                bmfaces.append(self.rfcontext.new_face([p0,p1,p2,p3]))
                if not fp0: fp0,fp1 = p0,p1
                p0,p1 = p3,p2
            lp2,lp3 = p2,p3
            
            if bme_start:
                bmv0,bmv1 = bme_start.verts
                merge(fp0, fp1, bmv0, bmv1)
            if bme_end:
                bmv0,bmv1 = bme_end.verts
                merge(lp2, lp3, bmv0, bmv1)
        
        def absorb(cb, bme):
            if not bme: return cb
            Point_to_Point2D = self.rfcontext.Point_to_Point2D
            # tessellate curve to points, absorb points into bme0 and bme3, then refit
            pts = cb.tessellate_uniform_points()
            v0,v1 = bme.verts
            p0,p1 = Point_to_Point2D(v0.co),Point_to_Point2D(v1.co)
            d01 = p1 - p0
            len2D = d01.length
            d01.normalize()
            def dist2D(pt):
                pt2D = Point_to_Point2D(pt)
                d = max(0, min(len2D, d01.dot(pt2D-p0)))
                pt = p0 + d01 * d
                return (pt - pt2D).length
            npts = [pt for pt in pts if dist2D(pt) > len2D * 0.65]
            if len(npts) > 2:
                cb = CubicBezier.create_from_points(npts)
            dprint('absorb: %d -> %d' % (len(pts), len(npts)))
            return cb
        
        def stroke_to_quads(stroke):
            nonlocal bmfaces, all_bmfaces, vis_faces2D, vis_edges, radius
            cbs = CubicBezierSpline.create_from_points([stroke], radius/60.0)
            nearest2D_edge = self.rfcontext.nearest2D_edge
            radius2D = self.rfcontext.size_to_size2D(radius, stroke[0])
           
            for cb in cbs:
                # pre-pass curve to see if we cross existing geo
                p0,_,_,p3 = cb.points()
                bme0,d0 = nearest2D_edge(p0, radius2D, edges=vis_edges)
                bme3,d3 = nearest2D_edge(p3, radius2D, edges=vis_edges)
                
                # print((len(vis_edges), radius2D,bme0,d0,bme3,d3))
                # bme0,bme3 = None,None
                
                cb = absorb(cb, bme0)
                cb = absorb(cb, bme3)
                
                # post-pass to create
                bmfaces = []
                insert(cb, bme0, bme3)
                all_bmfaces += bmfaces
                # vis_edges |= set(bme for bmf in bmfaces for bme in bmf.edges)
                # vis_faces2D += [(bmf, [Point_to_Point2D(bmv.co) for bmv in bmf.verts]) for bmf in bmfaces]
            
            self.stroke_cbs = self.stroke_cbs + cbs
        
        def process_stroke():
            # scan through all the points of stroke
            # if stroke goes off source or crosses a visible face, stop and insert,
            # then skip ahead until stroke goes back on source
            
            self.stroke_cbs = CubicBezierSpline()
            
            strokes = []
            pt,state,face0 = next_state()
            while stroke2D:
                if state == 'src':
                    stroke = []
                    while stroke2D and state == 'src':
                        pt3d = self.rfcontext.get_point3D(pt)
                        stroke.append(pt3d)
                        pt,state,face1 = next_state()
                    if len(stroke) > 10:
                        stroke_to_quads(stroke)
                        strokes.append(stroke)
                    face0 = face1
                elif state in {'tar', 'off'}:
                    pt,state,face0 = next_state()
                else:
                    assert False, 'Unexpected state'
            self.strokes = strokes
            
            map(self.rfcontext.update_face_normal, all_bmfaces)
            self.rfcontext.select(all_bmfaces)
        
        def merge_faces():
            nonlocal all_bmfaces
            # go through all the faces and merge newly created faces that overlap
            Point_to_Point2D = self.rfcontext.Point_to_Point2D
            done = False
            while not done:
                done = True
                max_i0,max_i1,max_overlap = -1,-1,0.5
                for i0,bmf0 in enumerate(all_bmfaces):
                    if not bmf0.is_valid: continue
                    for i1,bmf1 in enumerate(all_bmfaces):
                        if i1 <= i0: continue
                        if not bmf1.is_valid: continue
                        if any(bmf0 in bme.link_faces for bme in bmf1.edges): continue
                        overlap = bmf0.overlap2D(bmf1, Point_to_Point2D)
                        if overlap > max_overlap:
                            max_i0 = i0
                            max_i1 = i1
                            max_overlap = overlap
                if max_i0 != -1:
                    dprint('%s overlaps %s by %f' % (str(bmf0), str(bmf1), overlap))
                    bmf0 = all_bmfaces[max_i0]
                    bmf1 = all_bmfaces[max_i1]
                    bmf0.merge(bmf1)
                    for vert in bmf0.verts:
                        self.rfcontext.clean_duplicate_bmedges(vert)
                    done = False
        
        try:
            process_stroke()
        except Exception as e:
            Logger.add('Unhandled exception raised while processing stroke\n' + str(e))
            dprint('Unhandled exception raised while processing stroke\n' + str(e))
            showErrorMessage('Unhandled exception raised while processing stroke.\nPlease try again.')
            raise e
        try:
            merge_faces()
        except Exception as e:
            Logger.add('Unhandled exception raised while merging faces\n' + str(e))
            dprint('Unhandled exception raised while merging faces\n' + str(e))
            showErrorMessage('Unhandled exception raised while merging faces.\nPlease try again.')
            raise e
        
        self.rfcontext.reselect()
        
        for bmf in all_bmfaces:
            if not bmf.is_valid: continue
            for bmv in bmf.verts:
                self.rfcontext.snap2D_vert(bmv)
    
    @RFTool.dirty_when_done
    def change_count(self, delta):
        '''
        find parallel strips of boundary edges, fit curve to verts of strips, then
        recompute faces based on curves.
        
        note: this op will only change counts along boundaries.  otherwise, use loop cut
        '''
        
        nfaces = []
        
        def process(bmfs, bmes):
            nonlocal nfaces
            
            # find edge strips
            strip0,strip1 = [bmes[0].verts[0]], [bmes[0].verts[1]]
            edges0,edges1 = [],[]
            for bmf,bme0 in zip(bmfs,bmes):
                bme1,bme2 = bmf.neighbor_edges(bme0)
                if strip0[-1] in bme2.verts: bme1,bme2 = bme2,bme1
                strip0.append(bme1.other_vert(strip0[-1]))
                strip1.append(bme2.other_vert(strip1[-1]))
                edges0.append(bme1)
                edges1.append(bme2)
            pts0,pts1 = [v.co for v in strip0],[v.co for v in strip1]
            lengths0 = [(p0-p1).length for p0,p1 in iter_pairs(pts0, False)]
            lengths1 = [(p0-p1).length for p0,p1 in iter_pairs(pts1, False)]
            length0,length1 = sum(lengths0),sum(lengths1)
            
            max_error = min(min(lengths0),min(lengths1)) / 100.0   # arbitrary!
            spline0 = CubicBezierSpline.create_from_points([[Vector(p) for p in pts0]], max_error)
            spline1 = CubicBezierSpline.create_from_points([[Vector(p) for p in pts1]], max_error)
            len0,len1 = len(spline0), len(spline1)
            
            count = len(bmfs)
            ncount = max(1, count + delta)
            
            # approximate ts along each strip
            def approx_ts(spline_len, lengths):
                nonlocal ncount,count
                accum_ts_old = [0]
                for l in lengths: accum_ts_old.append(accum_ts_old[-1] + l)
                total_ts_old = sum(lengths)
                ts_old = [Vector((i, t / total_ts_old, 0)) for i,t in enumerate(accum_ts_old)]
                spline_ts_old = CubicBezierSpline.create_from_points([ts_old], 0.01)
                spline_ts_old_len = len(spline_ts_old)
                ts = [spline_len * spline_ts_old.eval(spline_ts_old_len * i / ncount).y for i in range(ncount+1)]
                return ts
            ts0 = approx_ts(len0, lengths0)
            ts1 = approx_ts(len1, lengths1)
            
            self.rfcontext.delete_edges(edges0 + edges1 + bmes[1:-1])
            
            new_vert = self.rfcontext.new_vert_point
            verts0 = strip0[:1] + [new_vert(spline0.eval(t)) for t in ts0[1:-1]] + strip0[-1:]
            verts1 = strip1[:1] + [new_vert(spline1.eval(t)) for t in ts1[1:-1]] + strip1[-1:]
            
            for (v00,v01),(v10,v11) in zip(iter_pairs(verts0,False), iter_pairs(verts1,False)):
                nfaces.append(self.rfcontext.new_face([v00,v01,v11,v10]))
            
            
        
        # find selected faces that are not part of strips
        #  [ | | | | | | | ]
        #      |O|     |O|    <- with either of these selected, split into two
        #  [ | | | ]
        
        bmquads = [bmf for bmf in self.rfcontext.get_selected_faces() if len(bmf.verts) == 4]
        bmquads = [bmq for bmq in bmquads if not any(bmq in strip for strip in self.strips)]
        for bmf in bmquads:
            bmes = list(bmf.edges)
            boundaries = [len(bme.link_faces) == 2 for bme in bmf.edges]
            if (boundaries[0] or boundaries[2]) and not boundaries[1] and not boundaries[3]:
                process([bmf], [bmes[0],bmes[2]])
                continue
            if (boundaries[1] or boundaries[3]) and not boundaries[0] and not boundaries[2]:
                process([bmf], [bmes[1],bmes[3]])
                continue
        
        # find boundary portions of each strip
        # TODO: what if there are multiple boundary portions??
        #  [ | |O| | ]
        #      |O|      <-
        #      |O|      <- only working on this part of strip
        #      |O|      <-
        #      |O| | ]
        #  [ | |O| | ]
        
        for strip in self.strips:
            bmfs,bmes = [],[]
            bme0 = strip.bme0
            for bmf in strip:
                bme2 = bmf.opposite_edge(bme0)
                bme1,bme3 = bmf.neighbor_edges(bme0)
                if len(bme1.link_faces) == 1 and len(bme3.link_faces) == 1:
                    bmes.append(bme0)
                    bmfs.append(bmf)
                else:
                    # if we've already seen a portion of the strip that can be modified, break!
                    if bmfs:
                        bmes.append(bme0)
                        break
                bme0 = bme2
            else:
                bmes.append(bme0)
            if not bmfs: continue
            process(bmfs, bmes)
        
        if nfaces:
            self.rfcontext.select(nfaces, supparts=False, only=False)
        else:
            self.rfcontext.alert_user('PolyStrips', 'Could not find a strip to adjust')
    
    @RFTool.dirty_when_done
    def insert_strip(self, cb, steps, radius, bme_start=None, bme_end=None):
        steps = max(steps, 0 if bme_start and bme_end else 2)
        bmfaces = []
        
        def merge_edges(p0, p1, q0, q1):
            nonlocal bmfaces
            dp,dq = p1.co - p0.co, q1.co - q0.co
            if dp.dot(dq) < 0: p0,p1 = p1,p0
            q0.merge(p0)
            q1.merge(p1)
            mapping = self.rfcontext.clean_duplicate_bmedges(q0)
            bmfaces = [mapping.get(f, f) for f in bmfaces]
            mapping = self.rfcontext.clean_duplicate_bmedges(q1)
            bmfaces = [mapping.get(f, f) for f in bmfaces]
        
        if bme_start and bme_start == bme_end: return
        if bme_start and bme_end:
            bmv0,bmv1 = bme_start.verts
            bmv2,bmv3 = bme_end.verts
            if bmv0 == bmv2 or bmv0 == bmv3 or bmv1 == bmv2 or bmv1 == bmv3: return
        
        if steps == 1:
            if bme_start == None or bme_end == None: return
            bmv0,bmv1 = bme_start.verts
            bmv2,bmv3 = bme_end.verts
            dir01,dir23 = bmv1.co - bmv0.co, bmv3.co - bmv2.co
            if dir01.dot(dir23) > 0:
                bmfaces.append(self.rfcontext.new_face([bmv0,bmv1,bmv3,bmv2]))
            else:
                bmfaces.append(self.rfcontext.new_face([bmv0,bmv1,bmv2,bmv3]))
            return bmfaces
        
        length = cb.approximate_length_uniform(lambda p,q: (p-q).length)
        #radius = length / steps/2
        intervals = [(i/(steps-1))*length for i in range(steps)]
        ts = cb.approximate_ts_at_intervals_uniform(intervals, lambda p,q: (p-q).length)
        
        fp0,fp1 = None,None
        lp2,lp3 = None,None
        p0,p1,p2,p3 = None,None,None,None
        for t in ts:
            center,normal,_,_ = self.rfcontext.nearest_sources_Point(cb.eval(t))
            direction = cb.eval_derivative(t).normalized()
            cross = normal.cross(direction).normalized()
            back,front = center - direction * radius, center + direction * radius
            loc0,loc1 = back  - cross * radius, back  + cross * radius
            loc2,loc3 = front + cross * radius, front - cross * radius
            if p0 is None:
                p0 = self.rfcontext.new_vert_point(loc0)
                p1 = self.rfcontext.new_vert_point(loc1)
            else:
                p0.co = (Vector(p0.co) + Vector(loc0)) * 0.5
                p1.co = (Vector(p1.co) + Vector(loc1)) * 0.5
            p2 = self.rfcontext.new_vert_point(loc2)
            p3 = self.rfcontext.new_vert_point(loc3)
            bmfaces.append(self.rfcontext.new_face([p0,p1,p2,p3]))
            if not fp0: fp0,fp1 = p0,p1
            p0,p1 = p3,p2
        lp2,lp3 = p2,p3
        
        # TODO: redo this to not use merge!
        if bme_start:
            bmv0,bmv1 = bme_start.verts
            merge_edges(fp0, fp1, bmv0, bmv1)
        if bme_end:
            bmv0,bmv1 = bme_end.verts
            merge_edges(lp2, lp3, bmv0, bmv1)
        
        return bmfaces