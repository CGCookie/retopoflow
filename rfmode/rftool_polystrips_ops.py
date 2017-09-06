import bgl
import bpy
import math
from mathutils import Vector, Matrix
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.bezier import CubicBezierSpline, CubicBezier
from mathutils.geometry import intersect_point_tri_2d
from ..common.ui import UI_Image
from ..common.utils import iter_pairs

from ..lib.common_utilities import showErrorMessage, dprint
from ..lib.classes.logging.logger import Logger

from .rftool_polystrips_utils import *

class RFTool_PolyStrips_Ops:
        
    @RFTool.dirty_when_done
    def stroke(self):
        # called when artist finishes a stroke
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
        
        for bmf in all_bmfaces:
            if not bmf.is_valid: continue
            for bmv in bmf.verts:
                self.rfcontext.snap_vert(bmv)
    
    def change_count(self, delta):
        # find first strip that is simple enough to modify
        for strip in self.strips:
            if len(strip) != 1:
                # skip, because strip uses more than one curve
                continue
            bmf_strip = strip.bmf_strip
            bme0,bme1 = strip.bme0,strip.bme1
            dontcount = set(bmf_strip) | set(bme0.link_faces) | set(bme1.link_faces)
            if sum(1 for f in bmf_strip for e in f.edges for f_ in e.link_faces if f_ not in dontcount) != 0:
                # skip, because there are faces attached :(
                continue
            
            c0,c1 = len(bme0.link_faces)==2,len(bme1.link_faces)==2
            
            cb = strip.cbs[0]
            radius = sum(rad for bme,_,rad,_,_,_ in strip.bmes) / len(strip.bmes)
            count = len(bmf_strip)
            count_new = max(count + delta, 0 if c0 and c1 else 2)
            if count == count_new: return
            dprint('changing strip count: %d > %d' % (count,count_new))
            self.rfcontext.delete_faces(bmf_strip)
            faces = self.insert_strip(cb, count_new, radius, bme_start=bme0 if c0 else None, bme_end=bme1 if c1 else None)
            self.rfcontext.select(faces)
            for bmf in faces:
                if not bmf.is_valid: continue
                for bmv in bmf.verts:
                    self.rfcontext.snap_vert(bmv)
            break

        # pass
        # sel_edges = self.rfcontext.get_selected_edges()
        # loops = find_loops(sel_edges)
        # if len(loops) != 1: return
        # loop = loops[0]
        # count = len(loop)
        # count_new = max(3, count+delta)
        # if count == count_new: return
        # if any(len(v.link_edges) != 2 for v in loop): return
        # cl = Contours_Loop(loop, True)
        # avg = Point.average(v.co for v in loop)
        # plane = cl.plane
        # ray = self.rfcontext.Point2D_to_Ray(self.rfcontext.Point_to_Point2D(avg))
        # self.rfcontext.delete_edges(e for v in loop for e in v.link_edges)
        # self.new_cut(ray, plane, walk=True, count=count_new)
    
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
        
        if steps == 0:
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