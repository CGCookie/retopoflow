import bgl
import bpy
import math
from mathutils import Vector, Matrix
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.bezier import CubicBezierSpline, CubicBezier
from mathutils.geometry import intersect_point_tri_2d

from ..lib.common_utilities import showErrorMessage
from ..lib.classes.logging.logger import Logger

from .rftool_polystrips_utils import *

@RFTool.action_call('polystrips tool')
class RFTool_PolyStrips(RFTool):
    def init(self):
        self.FSM['move bmf'] = self.modal_move_bmf
        self.FSM['manip bezier'] = self.modal_manip_bezier
        self.FSM['rotate outer'] = self.modal_rotate_outer
        
        self.point_size = 10
    
    def name(self): return "PolyStrips"
    def icon(self): return "rf_polystrips_icon"
    def description(self): return 'Strips of quads made easy'
    
    def start(self):
        self.mode = 'main'
        self.rfwidget.set_widget('brush stroke', color=(1.0, 0.5, 0.5))
        self.rfwidget.set_stroke_callback(self.stroke)
        self.hovering = []
        self.hovering_strips = set()
        self.sel_cbpts = []
        self.strokes = []
        self.stroke_cbs = CubicBezierSpline()
        self.update()
    
    def update(self):
        self.strips = []
        
        # get selected quads
        bmquads = set(bmf for bmf in self.rfcontext.get_selected_faces() if len(bmf.verts) == 4)
        if not bmquads: return
        
        # find knots
        knots = set()
        for bmf in bmquads:
            edge0,edge1,edge2,edge3 = [is_edge(bme, bmquads) for bme in bmf.edges]
            if edge0 and edge2 and not (edge1 or edge3): continue
            if edge1 and edge3 and not (edge0 or edge2): continue
            knots.add(bmf)
        
        # find strips between knots
        touched = set()
        self.strips = []
        for bmf0 in knots:
            bme0,bme1,bme2,bme3 = bmf0.edges
            edge0,edge1,edge2,edge3 = [is_edge(bme, bmquads) for bme in bmf0.edges]
            
            def add_strip(bme):
                strip = crawl_strip(bmf0, bme, bmquads, knots)
                bmf1 = strip[-1]
                if len(strip) > 1 and hash_face_pair(bmf0, bmf1) not in touched:
                    touched.add(hash_face_pair(bmf0,bmf1))
                    touched.add(hash_face_pair(bmf1,bmf0))
                    self.strips.append(RFTool_PolyStrips_Strip(strip))
            
            if not edge0: add_strip(bme0)
            if not edge1: add_strip(bme1)
            if not edge2: add_strip(bme2)
            if not edge3: add_strip(bme3)
        
        self.update_strip_viz()
    
    def update_strip_viz(self):
        self.strip_pts = [[cb.eval(i/10) for i in range(10+1)] for strip in self.strips for cb in strip]
    
    @RFTool.dirty_when_done
    def stroke(self):
        radius = self.rfwidget.get_scaled_size()
        stroke2D = list(self.rfwidget.stroke2D)
        bmfaces = []
        all_bmfaces = []
        
        if len(stroke2D) < 10: return
        
        self.rfcontext.undo_push('stroke')
        
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        vis_faces = self.rfcontext.visible_faces()
        vis_faces2D = [(bmf, [Point_to_Point2D(bmv.co) for bmv in bmf.verts]) for bmf in vis_faces]
        
        def get_state(point:Point2D):
            nonlocal vis_faces2D
            point3D = self.rfcontext.get_point3D(point)
            if not point3D: return ('off', None)
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
        
        def stroke_to_quads(stroke):
            nonlocal bmfaces, all_bmfaces, vis_faces2D
            cbs = CubicBezierSpline.create_from_points([stroke], radius/20.0)
            nearest_edges_Point = self.rfcontext.nearest_edges_Point
            
            for cb in cbs:
                # pre-pass curve to see if we cross existing geo
                p0,_,_,p3 = cb.points()
                bmes0 = nearest_edges_Point(p0, radius)
                bmes3 = nearest_edges_Point(p3, radius)
                #print('close to %d and %d' % (len(bmes0), len(bmes3)))
                bme0 = None if not bmes0 else sorted(bmes0, key=lambda d:d[1])[0][0]
                bme3 = None if not bmes3 else sorted(bmes3, key=lambda d:d[1])[0][0]
                
                # post-pass to create
                bmfaces = []
                insert(cb, bme0, bme3)
                all_bmfaces += bmfaces
                vis_faces2D += [(bmf, [Point_to_Point2D(bmv.co) for bmv in bmf.verts]) for bmf in bmfaces]
            
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
                        stroke.append(self.rfcontext.get_point3D(pt))
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
        
        try:
            process_stroke()
        except Exception as e:
            Logger.add('Unhandled exception raised while processing stroke\n' + str(e))
            showErrorMessage('Unhandled exception raised while processing stroke.\nPlease try again.')
    
    def modal_main(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        mouse = self.rfcontext.actions.mouse
        self.hovering.clear()
        self.hovering_strips.clear()
        for strip in self.strips:
            for cb in strip:
                for cbpt in cb:
                    v = Point_to_Point2D(cbpt)
                    if v is None: continue
                    if (mouse - v).length < self.point_size:
                        self.hovering.append(cbpt)
                        self.hovering_strips.add(strip)
        if self.hovering:
            self.rfwidget.set_widget('move')
        else:
            self.rfwidget.set_widget('brush stroke')
        
        if self.hovering and self.rfcontext.actions.pressed('action'):
            return self.prep_manip()
        
        if self.hovering and self.rfcontext.actions.pressed('alt action'):
            return self.prep_rotate()
        
        if self.rfcontext.actions.using('select'):
            if self.rfcontext.actions.pressed('select'):
                self.rfcontext.undo_push('select')
                self.rfcontext.deselect_all()
            bmf = self.rfcontext.nearest2D_face_mouse()
            if bmf and not bmf.select:
                self.rfcontext.select(bmf, supparts=False, only=False)
            return
        
        if self.rfcontext.actions.using('select add'):
            if self.rfcontext.actions.pressed('select add'):
                self.rfcontext.undo_push('select add')
            bmf = self.rfcontext.nearest2D_face_mouse()
            if bmf and not bmf.select:
                self.rfcontext.select(bmf, supparts=False, only=False)
            return
        
        if self.rfcontext.actions.pressed('grab'):
            return self.prep_move()
        
        if self.rfcontext.actions.pressed('delete'):
            self.rfcontext.undo_push('delete')
            faces = self.rfcontext.get_selected_faces()
            self.rfcontext.delete_faces(faces)
            self.rfcontext.deselect_all()
            self.rfcontext.dirty()
            self.update()
            return
    
    def prep_rotate(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        inner,outer = None,None
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.points()
                if p1 in self.hovering: inner,outer = p1,p0
                if p2 in self.hovering: inner,outer = p2,p3
        if not inner or not outer: return ''
        self.sel_cbpts = []
        self.mod_strips = set()
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.points()
                if (outer - p0).length < 0.01:
                    self.sel_cbpts += [(p1, Point(p1), Point_to_Point2D(p1))]
                    self.mod_strips.add(strip)
                if (outer - p3).length < 0.01:
                    self.sel_cbpts += [(p2, Point(p2), Point_to_Point2D(p2))]
                    self.mod_strips.add(strip)
        self.rotate_about = Point_to_Point2D(outer)
        if not self.rotate_about: return ''
        
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('move')
        self.move_done_pressed = 'confirm'
        self.move_done_released = 'alt action'
        self.move_cancelled = 'cancel'
        self.rfcontext.undo_push('rotate outer')
        return 'rotate outer'
    
    @RFTool.dirty_when_done
    def modal_rotate_outer(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfwidget.set_widget('brush stroke')
            self.rfcontext.undo_cancel()
            return 'main'
        
        prev_diff = self.mousedown - self.rotate_about
        prev_rot = math.atan2(prev_diff.x, prev_diff.y)
        cur_diff = self.rfcontext.actions.mouse - self.rotate_about
        cur_rot = math.atan2(cur_diff.x, cur_diff.y)
        angle = prev_rot - cur_rot
        
        rot = Matrix.Rotation(angle, 2)
        
        for cbpt,oco,oco2D in self.sel_cbpts:
            xy = rot * (oco2D - self.rotate_about) + self.rotate_about
            xyz,_,_,_ = self.rfcontext.raycast_sources_Point2D(xy)
            if xyz: cbpt.xyz = xyz
        
        for strip in self.mod_strips:
            strip.update(self.rfcontext.nearest_sources_Point, self.rfcontext.raycast_sources_Point, self.rfcontext.update_face_normal)
        
        self.update_strip_viz()
    
    def prep_manip(self):
        cbpts = list(self.hovering)
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.points()
                if p0 in cbpts and p1 not in cbpts: cbpts.append(p1)
                if p3 in cbpts and p2 not in cbpts: cbpts.append(p2)
        self.sel_cbpts = [(cbpt, Point(cbpt), self.rfcontext.Point_to_Point2D(cbpt)) for cbpt in cbpts]
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('move')
        self.move_done_pressed = 'confirm'
        self.move_done_released = 'action'
        self.move_cancelled = 'cancel'
        self.rfcontext.undo_push('manipulate bezier')
        return 'manip bezier'
    
    @RFTool.dirty_when_done
    def modal_manip_bezier(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfwidget.set_widget('brush stroke')
            self.rfcontext.undo_cancel()
            return 'main'
        
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        up,rt = self.rfcontext.Vec_up(),self.rfcontext.Vec_right()
        for cbpt,oco,oco2D in self.sel_cbpts:
            xyz,_,_,_ = self.rfcontext.raycast_sources_Point2D(oco2D + delta)
            #xyz = oco + delta.x * rt - delta.y * up
            if xyz: cbpt.xyz = xyz
        
        for strip in self.hovering_strips:
            strip.update(self.rfcontext.nearest_sources_Point, self.rfcontext.raycast_sources_Point, self.rfcontext.update_face_normal)
        
        self.update_strip_viz()
    
    def prep_move(self, bmfaces=None):
        if not bmfaces: bmfaces = self.rfcontext.get_selected_faces()
        bmverts = set(bmv for bmf in bmfaces for bmv in bmf.verts)
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('default')
        self.rfcontext.undo_push('move grabbed')
        self.move_done_pressed = 'confirm'
        self.move_done_released = None
        self.move_cancelled = 'cancel'
        return 'move bmf'
    
    @RFTool.dirty_when_done
    def modal_move_bmf(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfwidget.set_widget('brush stroke')
            self.rfcontext.undo_cancel()
            return 'main'

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            set2D_vert(bmv, xy + delta)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)
        self.update()
        
    
    def draw_postview(self):
        self.draw_spline()
        
        if False:
            stroke_pts = [[cb.eval(i / 5) for i in range(5+1)] for cb in self.stroke_cbs]
            stroke_der = [[cb.eval_derivative(i / 5) for i in range(5+1)] for cb in self.stroke_cbs]
            self.drawing.line_width(1.0)
            bgl.glColor4f(1,1,1,0.5)
            for pts in stroke_pts:
                bgl.glBegin(bgl.GL_LINE_STRIP)
                for pt in pts:
                    bgl.glVertex3f(*pt)
                bgl.glEnd()
            bgl.glColor4f(0,0,1,0.5)
            bgl.glBegin(bgl.GL_LINES)
            for pts,ders in zip(stroke_pts,stroke_der):
                for pt,der in zip(pts,ders):
                    bgl.glVertex3f(*pt)
                    ptder = pt + der.normalized() * 0.3
                    bgl.glVertex3f(*ptder)
            bgl.glEnd()
        
    
    def draw_spline(self):
        if not self.strips: return
        
        bgl.glDepthRange(0, 0.9999)     # squeeze depth just a bit 
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
        bgl.glEnable(bgl.GL_DEPTH_TEST)

        ######################################
        # draw in front of geometry
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        
        # draw control points
        self.drawing.point_size(self.point_size)
        bgl.glColor4f(1,1,1,0.5)
        bgl.glBegin(bgl.GL_POINTS)
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
                bgl.glVertex3f(*p0)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p3)
        bgl.glEnd()
        
        # draw outer-inner lines
        self.drawing.line_width(2.0)
        bgl.glColor4f(1,0.5,0.5,0.4)
        bgl.glBegin(bgl.GL_LINES)
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
                bgl.glVertex3f(*p0)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p3)
        bgl.glEnd()
        
        # draw curve
        self.drawing.line_width(2.0)
        bgl.glColor4f(1,1,1,0.5)
        bgl.glBegin(bgl.GL_LINES)
        for pts in self.strip_pts:
            v0 = None
            for v1 in pts:
                if v0:
                    bgl.glVertex3f(*v0)
                    bgl.glVertex3f(*v1)
                v0 = v1
        bgl.glEnd()
        
        ######################################
        # draw behind geometry
        bgl.glDepthFunc(bgl.GL_GREATER)
        
        # draw control points
        self.drawing.point_size(self.point_size)
        bgl.glColor4f(1,1,1,0.25)
        bgl.glBegin(bgl.GL_POINTS)
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
                bgl.glVertex3f(*p0)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p3)
        bgl.glEnd()
        
        # draw outer-inner lines
        self.drawing.line_width(2.0)
        bgl.glColor4f(1,0.5,0.5,0.2)
        bgl.glBegin(bgl.GL_LINES)
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
                bgl.glVertex3f(*p0)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p3)
        bgl.glEnd()
        
        # draw curve
        self.drawing.line_width(2.0)
        bgl.glColor4f(1,1,1,0.25)
        bgl.glBegin(bgl.GL_LINES)
        for pts in self.strip_pts:
            v0 = None
            for v1 in pts:
                if v0:
                    bgl.glVertex3f(*v0)
                    bgl.glVertex3f(*v1)
                v0 = v1
        bgl.glEnd()
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glDepthMask(bgl.GL_TRUE)
    
    def draw_postpixel(self):
        pass
    
