import bgl
import bpy
import math
from mathutils import Vector
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.bezier import CubicBezierSpline, CubicBezier

class RFTool_State():
    def __init__(self, **kwargs):
        self.update(kwargs)
    def update(self, kv):
        for k,v in kv.items():
            self.__setattr__(k, v)

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

@RFTool.action_call('polystrips tool')
class RFTool_PolyStrips(RFTool):
    def init(self):
        self.FSM['move bmf'] = self.modal_move_bmf
        self.FSM['manip bezier'] = self.modal_manip_bezier
    
    def name(self): return "PolyStrips"
    def icon(self): return "rf_polystrips_icon"
    def description(self): return 'Strips of quads made easy'
    
    def start(self):
        self.mode = 'main'
        self.rfwidget.set_widget('brush stroke', color=(1.0, 0.5, 0.5))
        self.rfwidget.set_stroke_callback(self.stroke)
        self.sel_cbpts = []
        self.strokes = []
        self.stroke_cbs = CubicBezierSpline()
        self.update()
    
    def update(self):
        self.cbs = []
        
        # get selected quads
        bmquads = set(bmf for bmf in self.rfcontext.get_selected_faces() if len(bmf.verts) == 4)
        if not bmquads: return
        print('bmquads len: %d' % len(bmquads))
        
        # find knots
        knots = set()
        for bmf in bmquads:
            edge0,edge1,edge2,edge3 = [is_edge(bme, bmquads) for bme in bmf.edges]
            if edge0 and edge2 and not (edge1 or edge3): continue
            if edge1 and edge3 and not (edge0 or edge2): continue
            knots.add(bmf)
        
        # find strips between knots
        touched = set()
        self.cbs = CubicBezierSpline()
        for bmf0 in knots:
            bme0,bme1,bme2,bme3 = bmf0.edges
            edge0,edge1,edge2,edge3 = [is_edge(bme, bmquads) for bme in bmf0.edges]
            
            def add_strip(bme):
                strip = crawl_strip(bmf0, bme, bmquads, knots)
                print('quads in strip: %d' % len(strip))
                bmf1 = strip[-1]
                if len(strip) > 1 and hash_face_pair(bmf0, bmf1) not in touched:
                    touched.add(hash_face_pair(bmf0,bmf1))
                    touched.add(hash_face_pair(bmf1,bmf0))
                    pts,r = strip_details(strip)
                    print('strip: %s' % str(strip))
                    print('pts: %s' % str(pts))
                    print('radius: %f' % r)
                    self.cbs = self.cbs + CubicBezierSpline.create_from_points([pts], r/2000.0)
            
            if not edge0: add_strip(bme0)
            if not edge1: add_strip(bme1)
            if not edge2: add_strip(bme2)
            if not edge3: add_strip(bme3)
        
        print('touched len: %d' % len(touched))
        print('bezier count: %d' % len(self.cbs))
        print(touched)
        self.cbs_pts = [[cb.eval(i / 10) for i in range(10+1)] for cb in self.cbs]
    
    
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
        
        cbs = CubicBezierSpline.create_from_points(strokes, radius/2000.0)
        length = cbs.length(lambda p0,p1: (p0-p1).length)
        steps = round(length / radius)
        if steps <= 1: return
        p0,p1,p2,p3 = None,None,None,None
        for i in range(steps):
            t = (i / (steps-1)) * len(cbs)
            center,normal,_,_ = self.rfcontext.nearest_sources_Point(cbs.eval(t))
            direction = cbs.eval_derivative(t).normalized()
            cross = normal.cross(direction).normalized()
            back = center - direction * radius
            if p0 is None:
                p0 = self.rfcontext.new_vert_point(back - cross * radius)
                p1 = self.rfcontext.new_vert_point(back + cross * radius)
            # else:
            #     p0.co = (Vector(p0.co) + Vector(back - cross * radius)) * 0.5
            #     p1.co = (Vector(p1.co) + Vector(back + cross * radius)) * 0.5
            front = center + direction * radius
            p2 = self.rfcontext.new_vert_point(front + cross * radius)
            p3 = self.rfcontext.new_vert_point(front - cross * radius)
            bmfaces.append(self.rfcontext.new_face([p0,p1,p2,p3]))
            p0,p1 = p3,p2
        
        self.stroke_cbs = cbs
        
        # mini_stroke = [stroke2D[i] for i in range(0, stroke_len, int(stroke_len/10))]
        # left,right = [],[]
        
        # for c0,c1 in zip(mini_stroke[:-1],mini_stroke[1:]):
        #     d = c1 - c0
        #     ortho = Vec2D((-d.y, d.x)).normalized() * radius
        #     lpt = self.rfcontext.get_point3D(c0+ortho)
        #     rpt = self.rfcontext.get_point3D(c0-ortho)
        #     if lpt and rpt:
        #         left.append(self.rfcontext.new_vert_point(lpt))
        #         right.append(self.rfcontext.new_vert_point(rpt))
        
        # for i in range(len(left)-1):
        #     l0,r0 = left[i],right[i]
        #     l1,r1 = left[i+1],right[i+1]
        #     bmfaces.append(self.rfcontext.new_face([l1,l0,r0,r1]))
        
        self.rfcontext.select(bmfaces)
    
    def modal_main(self):
        if self.rfcontext.actions.pressed('select'):
            self.move_done_pressed = 'confirm'
            self.move_done_released = 'select'
            self.move_cancelled = 'cancel no select'
            
            # check if control point is under cursor
            self.sel_cbpts = []
            for cb in self.cbs:
                for cb_pt in cb:
                    cb_pt2D = self.rfcontext.Point_to_Point2D(cb_pt)
                    if (cb_pt2D - self.rfcontext.actions.mouse).length < 10:
                        self.sel_cbpts.append(cb_pt)
            if self.sel_cbpts:
                self.prep_manip()
                self.rfcontext.undo_push('manipulate bezier')
                return 'manip bezier'
            
            self.rfcontext.undo_push('select')
            bmf = self.rfcontext.nearest2D_face_mouse()
            if not bmf: return
            self.rfcontext.select(bmf, supparts=False)
            self.prep_move()
            self.rfcontext.undo_push('move single')
            return 'move bmf'
        
        if self.rfcontext.actions.pressed('grab'):
            self.rfcontext.undo_push('move grabbed')
            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move bmf'
        
        if self.rfcontext.actions.using('select add'):
            if self.rfcontext.actions.pressed('select add'):
                self.rfcontext.undo_push('select add')
            bmf = self.rfcontext.nearest2D_face_mouse()
            if bmf and not bmf.select:
                self.rfcontext.select(bmf, supparts=False, only=False)
            return
    
    def prep_manip(self):
        self.sel_cbpts = [(cbpt, self.rfcontext.Point_to_Point2D(cbpt)) for cbpt in self.sel_cbpts]
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('default')
    
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
        for cbpt,oco in self.sel_cbpts:
            xyz,_,_,_ = self.rfcontext.raycast_sources_Point2D(oco + delta)
            if xyz: cbpt.xyz = xyz
        #self.update()
        self.cbs_pts = [[cb.eval(i / 10) for i in range(10+1)] for cb in self.cbs]
    
    
    def prep_move(self, bmfaces=None):
        if not bmfaces: bmfaces = self.rfcontext.get_selected_faces()
        bmverts = set(bmv for bmf in bmfaces for bmv in bmf.verts)
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('default')
    
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
        if not self.cbs: return
        
        bgl.glDepthRange(0, 0.9999)     # squeeze depth just a bit 
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glLineWidth(2.0)
        bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
        bgl.glEnable(bgl.GL_DEPTH_TEST)

        ######################################
        # draw in front of geometry

        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glPointSize(10.0)
        bgl.glColor4f(1,1,1,0.5)
        bgl.glBegin(bgl.GL_POINTS)
        for cb in self.cbs:
            p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
            bgl.glVertex3f(*p0)
            bgl.glVertex3f(*p1)
            bgl.glVertex3f(*p2)
            bgl.glVertex3f(*p3)
        bgl.glEnd()
        if False:
            bgl.glColor4f(0.5,1.0,0.5,1.0)
            bgl.glPointSize(20.0)
            bgl.glBegin(bgl.GL_POINTS)
            for cbpt,_ in self.sel_cbpts:
                bgl.glVertex3f(*cbpt)
            bgl.glEnd()
        bgl.glColor4f(1,1,1,0.5)
        bgl.glBegin(bgl.GL_LINES)
        if False:
            # draw line segments between control points of bezier
            for cb in self.cbs:
                p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
                bgl.glVertex3f(*p0)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p3)
        # draw bezier curve
        for pts in self.cbs_pts:
            v0 = None
            for v1 in pts:
                if v0:
                    bgl.glVertex3f(*v0)
                    bgl.glVertex3f(*v1)
                v0 = v1
        bgl.glEnd()
        
        bgl.glDepthFunc(bgl.GL_GREATER)
        bgl.glPointSize(10.0)
        bgl.glColor4f(1,1,1,0.05)
        bgl.glBegin(bgl.GL_POINTS)
        for cb in self.cbs:
            p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
            bgl.glVertex3f(*p0)
            bgl.glVertex3f(*p1)
            bgl.glVertex3f(*p2)
            bgl.glVertex3f(*p3)
        bgl.glEnd()
        if False:
            bgl.glColor4f(0.5,1.0,0.5,0.1)
            bgl.glPointSize(20.0)
            bgl.glBegin(bgl.GL_POINTS)
            for cbpt,_ in self.sel_cbpts:
                bgl.glVertex3f(*cbpt)
            bgl.glEnd()
        bgl.glColor4f(1,1,1,0.05)
        bgl.glBegin(bgl.GL_LINES)
        if False:
            # draw line segments between control points of bezier
            for cb in self.cbs:
                p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
                bgl.glVertex3f(*p0)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p3)
        # draw bezier curve
        for pts in self.cbs_pts:
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
    
