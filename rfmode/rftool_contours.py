import bpy
import bgl
import blf
import math
from itertools import chain
from .rftool import RFTool
from ..lib.common_utilities import showErrorMessage
from ..common.maths import Point,Point2D,Vec2D,Vec
from .rftool_contours_utils import *

@RFTool.action_call('contours tool')
class RFTool_Contours(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['move']  = self.modal_move

    def name(self): return "Contours"
    def icon(self): return "rf_contours_icon"
    def description(self): return 'Contours!!'

    def start(self):
        self.rfwidget.set_widget('line', color=(1.0, 1.0, 1.0))
        self.rfwidget.set_line_callback(self.line)
        self.update()

        self.show_cut = False
        self.pts = []
        self.connected = False

    def update(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        sel_strings = find_strings(sel_edges)
        self.loops_data = [{
            'loop': loop,
            'plane': loop_plane(loop),
            'count': len(loop),
            'radius': loop_radius(loop),
            } for loop in sel_loops]
        self.strings_data = [{
            'string': string,
            'plane': loop_plane(string),
            'count': len(string),
            } for string in sel_strings]

    @RFTool.dirty_when_done
    def line(self):
        xy0,xy1 = self.rfwidget.line2D
        if (xy1-xy0).length < 0.001: return

        plane = self.rfcontext.Point2D_to_Plane(xy0, xy1)
        ray = self.rfcontext.Point2D_to_Ray(xy0 + (xy1-xy0)/2)

        crawl = self.rfcontext.plane_intersection_crawl(ray, plane)
        if not crawl: return
        # get crawl data (over source)
        pts = [c for (f0,e,f1,c) in crawl]
        connected = crawl[0][0] is not None
        length = sum((c0-c1).length for c0,c1 in iter_pairs(pts, connected))

        self.rfcontext.undo_push('cut')

        sel_edges = self.rfcontext.get_selected_edges()
        if connected:
            # find two closest selected loops, one on each side
            sel_loops = find_loops(sel_edges)
            sel_loop_planes = [loop_plane(loop) for loop in sel_loops]
            sel_loops_pos = sorted([
                (loop, plane.distance_to(p.o), len(loop), loop_length(loop))
                for loop,p in zip(sel_loops, sel_loop_planes) if plane.side(p.o) > 0
                ], key=lambda data:data[1])
            sel_loops_neg = sorted([
                (loop, plane.distance_to(p.o), len(loop), loop_length(loop))
                for loop,p in zip(sel_loops, sel_loop_planes) if plane.side(p.o) < 0
                ], key=lambda data:data[1])
            sel_loop_pos = next(iter(sel_loops_pos), None)
            sel_loop_neg = next(iter(sel_loops_neg), None)
            if sel_loop_pos and sel_loop_neg:
                if sel_loop_pos[2] != sel_loop_neg[2]:
                    # selected loops do not have same count of vertices
                    # choosing the closer loop
                    if sel_loop_pos[1] < sel_loop_neg[1]:
                        sel_loop_neg = None
                    else:
                        sel_loop_pos = None
                else:
                    edges_between = edges_between_loops(sel_loop_pos[0], sel_loop_neg[0])
                    self.rfcontext.delete_edges(edges_between)
        else:
            # find two closest selected strings, one on each side
            sel_strings = find_strings(sel_edges)
            sel_string_planes = [loop_plane(string) for string in sel_strings]
            sel_strings_pos = sorted([
                (string, plane.distance_to(p.o), len(string), string_length(string))
                for string,p in zip(sel_strings, sel_string_planes) if plane.side(p.o) > 0
                ], key=lambda data:data[1])
            sel_strings_neg = sorted([
                (string, plane.distance_to(p.o), len(string), string_length(string))
                for string,p in zip(sel_strings, sel_string_planes) if plane.side(p.o) < 0
                ], key=lambda data:data[1])
            sel_string_pos = next(iter(sel_strings_pos), None)
            sel_string_neg = next(iter(sel_strings_neg), None)
            if sel_string_pos and sel_string_neg:
                if sel_string_pos[2] != sel_string_neg[2]:
                    # selected strings do not have same count of vertices
                    # choosing the closer string
                    if sel_string_pos[1] < sel_string_neg[1]:
                        sel_string_neg = None
                    else:
                        sel_string_pos = None
            sel_loop_pos = None
            sel_loop_neg = None

        count = 16  # default starting count
        if sel_loop_pos is not None: count = sel_loop_pos[2]
        if sel_loop_neg is not None: count = sel_loop_neg[2]

        # where new verts, edges, and faces are stored
        verts,edges,faces = [],[],[]

        def insert_verts_edges(dists, offset=0):
            nonlocal verts,edges,pts,connected
            i,dist = 0,dists[0]
            for c0,c1 in iter_pairs(pts, connected): #chain(pts[:offset],pts[offset:]), connected):
                d = (c1-c0).length
                while dist - d <= 0:
                    # create new vert between c0 and c1
                    p = c0 + (c1 - c0) * (dist / d)
                    verts += [self.rfcontext.new_vert_point(p)]
                    i += 1
                    if i == len(dists): break
                    dist += dists[i]
                dist -= d
                if i == len(dists): break
            assert len(dists)==len(verts)
            for v0,v1 in iter_pairs(verts, connected):
                edges += [self.rfcontext.new_edge((v0, v1))]

        def bridge(loop):
            nonlocal faces, verts
            # find closest pair of verts between new loop and given loop
            vert_pair,dist = None,None
            for i0,v0 in enumerate(verts):
                for i1,v1 in enumerate(loop):
                    d = (v0.co - v1.co).length
                    if vert_pair is None or d < dist:
                        vert_pair,dist = (i0,i1),d
            l = len(loop)
            def get_vnew(i): return verts[((i%l)+l)%l]
            def get_vold(i): return loop[((i%l)+l)%l]
            i0,i3 = vert_pair
            dirs = [
                (1,1,(get_vnew(i0+1).co - get_vold(i3+1).co).length),
                (1,-1,(get_vnew(i0+1).co - get_vold(i3-1).co).length),
                (-1,1,(get_vnew(i0-1).co - get_vold(i3+1).co).length),
                (-1,-1,(get_vnew(i0-1).co - get_vold(i3-1).co).length),
                ]
            dirs.sort(key=lambda x:x[2])
            o0,o3,_ = dirs[0]
            for ind in range(l):
                i1 = i0 + o0
                i2 = i3 + o3
                faces += [self.rfcontext.new_face((get_vnew(i0), get_vnew(i1), get_vold(i2), get_vold(i3)))]
                i0,i3 = i1,i2

        # step_size is shrunk just a bit to account for floating point errors
        if sel_loop_pos and sel_loop_neg:
            step_size = length / (count - (0 if connected else 1)) * 0.999
            dists = [step_size for i in range(count)]
        elif sel_loop_pos:
            step_size = length / (count - (0 if connected else 1)) * 0.999
            dists = [step_size for i in range(count)]
        elif sel_loop_neg:
            step_size = length / (count - (0 if connected else 1)) * 0.999
            dists = [step_size for i in range(count)]
        else:
            step_size = length / (count - (0 if connected else 1)) * 0.999
            dists = [step_size for i in range(count)]

        insert_verts_edges(dists)

        if sel_loop_pos: bridge(sel_loop_pos[0])
        if sel_loop_neg: bridge(sel_loop_neg[0])

        #if sel_loop_pos:
        #    edges += edges_of_loop(sel_loops[sel_loop_pos[0]])
        #if sel_loop_neg:
        #    edges += edges_of_loop(sel_loops[sel_loop_neg[0]])

        self.rfcontext.select(verts + edges, supparts=False) # + faces)
        self.update()

        self.pts = pts
        self.connected = connected

    def modal_main(self):
        if self.rfcontext.actions.pressed('select'):
            edges = self.rfcontext.visible_edges()
            edge,_ = self.rfcontext.nearest2D_edge_mouse(edges=edges, max_dist=10)
            if not edge:
                self.rfcontext.deselect_all()
                return
            self.rfcontext.select_edge_loop(edge, only=True)
            self.update()
            return

        if self.rfcontext.actions.pressed('select add'):
            edges = self.rfcontext.visible_edges()
            edge,_ = self.rfcontext.nearest2D_edge_mouse(edges=edges, max_dist=10)
            if not edge: return
            self.rfcontext.select_edge_loop(edge, only=False)
            self.update()
            return

        if self.rfcontext.actions.pressed('grab'):
            self.rfcontext.undo_push('move grabbed')
            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move'


        if self.rfcontext.actions.pressed('increase count'):
            print('increasing count')
            return
        if self.rfcontext.actions.pressed('decrease count'):
            print('decreasing count')
            return

    def prep_move(self, bmverts=None):
        if not bmverts: bmverts = self.rfcontext.get_selected_verts()
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.mousedown = self.rfcontext.actions.mouse

    @RFTool.dirty_when_done
    def modal_move(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_crawl_vert = self.rfcontext.set2D_crawl_vert
        for bmv,xy in self.bmverts:
            set2D_crawl_vert(bmv, xy + delta)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)

    def draw_postview(self):
        if self.show_cut:
            bgl.glLineWidth(1.0)
            bgl.glColor4f(1,1,0,1)
            bgl.glBegin(bgl.GL_LINE_STRIP)
            for pt in self.pts:
                bgl.glVertex3f(*pt)
            if self.connected: bgl.glVertex3f(*self.pts[0])
            bgl.glEnd()

    def draw_postpixel(self):
        point_to_point2d = self.rfcontext.Point_to_Point2D
        up = self.rfcontext.Vec_up()
        size_to_size2D = self.rfcontext.size_to_size2D
        text_draw2D = self.rfcontext.drawing.text_draw2D
        self.rfcontext.drawing.text_size(12)

        for loop_data in self.loops_data:
            loop = loop_data['loop']
            radius = loop_data['radius']
            count = loop_data['count']
            plane = loop_data['plane']
            cos = [point_to_point2d(vert.co) for vert in loop]
            cos = [co for co in cos if co]
            if cos:
                xy = max(cos, key=lambda co:co.y)
                xy.y += 10
                text_draw2D(count, xy, (1,1,0,1), dropshadow=(0,0,0,0.5))

            p0 = point_to_point2d(plane.o)
            p1 = point_to_point2d(plane.o+plane.n*0.1)
            if p0 and p1:
                d = (p0 - p1) * 0.25
                c = Vec2D((d.y,-d.x))
                p2 = p1 + d + c
                p3 = p1 + d - c

                bgl.glLineWidth(2.0)
                bgl.glColor4f(1,1,0,0.5)
                bgl.glBegin(bgl.GL_LINE_STRIP)
                bgl.glVertex2f(*p0)
                bgl.glVertex2f(*p1)
                bgl.glVertex2f(*p2)
                bgl.glVertex2f(*p1)
                bgl.glVertex2f(*p3)
                bgl.glEnd()

        for string_data in self.strings_data:
            string = string_data['string']
            count = string_data['count']
            plane = string_data['plane']
            cos = [point_to_point2d(vert.co) for vert in string]
            cos = [co for co in cos if co]
            if cos:
                xy = max(cos, key=lambda co:co.y)
                xy.y += 10
                text_draw2D(count, xy, (1,1,0,1), dropshadow=(0,0,0,0.5))

            p0 = point_to_point2d(plane.o)
            p1 = point_to_point2d(plane.o+plane.n*0.1)
            if p0 and p1:
                d = (p0 - p1) * 0.25
                c = Vec2D((d.y,-d.x))
                p2 = p1 + d + c
                p3 = p1 + d - c

                bgl.glLineWidth(2.0)
                bgl.glColor4f(1,1,0,0.5)
                bgl.glBegin(bgl.GL_LINE_STRIP)
                bgl.glVertex2f(*p0)
                bgl.glVertex2f(*p1)
                bgl.glVertex2f(*p2)
                bgl.glVertex2f(*p1)
                bgl.glVertex2f(*p3)
                bgl.glEnd()
