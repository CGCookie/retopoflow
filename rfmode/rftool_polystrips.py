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
        bme0 = find_opposite_edge(bmf_strip[0], bmes[0][0])
        bme1 = find_opposite_edge(bmf_strip[-1], bmes[-1][0])
        if len(bme0.link_faces) == 1: bmes = [(bme0, bmf_strip[0].normal)] + bmes
        if len(bme1.link_faces) == 1: bmes = bmes + [(bme1, bmf_strip[-1].normal)]
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
        #self.cbs = []
        
        # get selected quads
        bmquads = set(bmf for bmf in self.rfcontext.get_selected_faces() if len(bmf.verts) == 4)
        if not bmquads: return
        # print('bmquads len: %d' % len(bmquads))
        
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
        #self.cbs = CubicBezierSpline()
        for bmf0 in knots:
            bme0,bme1,bme2,bme3 = bmf0.edges
            edge0,edge1,edge2,edge3 = [is_edge(bme, bmquads) for bme in bmf0.edges]
            
            def add_strip(bme):
                strip = crawl_strip(bmf0, bme, bmquads, knots)
                # print('quads in strip: %d' % len(strip))
                bmf1 = strip[-1]
                if len(strip) > 1 and hash_face_pair(bmf0, bmf1) not in touched:
                    touched.add(hash_face_pair(bmf0,bmf1))
                    touched.add(hash_face_pair(bmf1,bmf0))
                    self.strips.append(RFTool_PolyStrips_Strip(strip))
                    #pts,r = strip_details(strip)
                    #print('strip: %s' % str(strip))
                    #print('pts: %s' % str(pts))
                    #print('radius: %f' % r)
                    #self.cbs = self.cbs + CubicBezierSpline.create_from_points([pts], r/2000.0)
            
            if not edge0: add_strip(bme0)
            if not edge1: add_strip(bme1)
            if not edge2: add_strip(bme2)
            if not edge3: add_strip(bme3)
        
        #print('touched len: %d' % len(touched))
        #print('bezier count: %d' % len(self.cbs))
        #print(touched)
        #self.cbs_pts = [[cb.eval(i / 10) for i in range(10+1)] for cb in self.cbs]
        self.update_strip_viz()
    
    def update_strip_viz(self):
        self.strip_pts = [[cb.eval(i/10) for i in range(10+1)] for strip in self.strips for cb in strip]
    
    @RFTool.dirty_when_done
    def stroke(self):
        radius = self.rfwidget.get_scaled_size()
        stroke2D = self.rfwidget.stroke2D
        stroke_len = len(stroke2D)
        bmfaces = []
        
        if stroke_len < 10: return
        
        self.rfcontext.undo_push('stroke')
        
        strokes = []
        cur_stroke = []
        for pt2D in stroke2D:
            pt = self.rfcontext.get_point3D(pt2D)
            if not pt:
                if cur_stroke: strokes += [cur_stroke]
                cur_stroke = []
                continue
            cur_stroke += [pt]
        if cur_stroke: strokes += [cur_stroke]
        self.strokes = strokes
        
        def merge(p0, p1, q0, q1):
            nonlocal bmfaces
            dp = p1.co - p0.co
            dq = q1.co - q0.co
            if dp.dot(dq) < 0: p0,p1 = p1,p0
            q0.merge(p0)
            q1.merge(p1)
            mapping = self.rfcontext.clean_duplicate_bmedges(q0)
            bmfaces = [mapping[f] if f in mapping else f for f in bmfaces]
        
        def insert(cb, bme_start, bme_end):
            length = cb.approximate_length_uniform(lambda p,q: (p-q).length)
            steps = round(length / radius)
            steps += steps % 2              # make sure that we have even number of steps
            if steps <= 1: return
            
            intervals = [0] + [((i+1)/steps)*length for i in range(steps)]
            ts = cb.approximate_ts_at_intervals_uniform(intervals, lambda p,q: (p-q).length)
            
            fp0,fp1 = None,None
            lp2,lp3 = None,None
            p0,p1,p2,p3 = None,None,None,None
            for i,t in enumerate(ts):
                if i % 2 == 1: continue
                center,normal,_,_ = self.rfcontext.nearest_sources_Point(cb.eval(t))
                direction = cb.eval_derivative(t).normalized()
                cross = normal.cross(direction).normalized()
                back = center - direction * radius
                if p0 is None:
                    p0 = self.rfcontext.new_vert_point(back - cross * radius)
                    p1 = self.rfcontext.new_vert_point(back + cross * radius)
                    fp0,fp1 = p0,p1
                else:
                    p0.co = (Vector(p0.co) + Vector(back - cross * radius)) * 0.5
                    p1.co = (Vector(p1.co) + Vector(back + cross * radius)) * 0.5
                front = center + direction * radius
                p2 = self.rfcontext.new_vert_point(front + cross * radius)
                p3 = self.rfcontext.new_vert_point(front - cross * radius)
                lp2,lp3 = p2,p3
                bmfaces.append(self.rfcontext.new_face([p0,p1,p2,p3]))
                p0,p1 = p3,p2
            
            if bme_start is not None:
                bmv0,bmv1 = bme_start.verts
                merge(fp0, fp1, bmv0, bmv1)
            if bme_end is not None:
                bmv0,bmv1 = bme_end.verts
                merge(lp2, lp3, bmv0, bmv1)
        
        cbs = CubicBezierSpline.create_from_points(strokes, radius/20.0)
        
        for cb in cbs:
            # pre-pass curve to see if we cross existing geo
            p0,_,_,p3 = cb.points()
            bmes0 = self.rfcontext.nearest_bmedges_Point(p0, radius)
            bmes3 = self.rfcontext.nearest_bmedges_Point(p3, radius)
            print('close to %d and %d' % (len(bmes0), len(bmes3)))
            if bmes0:
                bmes0 = sorted(bmes0, key=lambda d:d[1])
                bme0 = bmes0[0][0]
            else:
                bme0 = None
            if bmes3:
                bmes3 = sorted(bmes3, key=lambda d:d[1])
                bme3 = bmes3[0][0]
            else:
                bme3 = None
            
            # post-pass to create 
            insert(cb, bme0, bme3)
        
        for bmf in bmfaces:
            self.rfcontext.update_face_normal(bmf)
        
        self.stroke_cbs = cbs
        
        self.rfcontext.select(bmfaces)
    
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
            self.rfcontext.undo_push('move grabbed')
            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move bmf'
        
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
            bgl.glLineWidth(1.0)
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
        bgl.glPointSize(self.point_size)
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
        bgl.glLineWidth(2.0)
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
        bgl.glLineWidth(2.0)
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
        bgl.glPointSize(self.point_size)
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
        bgl.glLineWidth(2.0)
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
        bgl.glLineWidth(2.0)
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
    
