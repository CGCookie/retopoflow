import bpy
import bgl
import blf
import math
from .rftool import RFTool
from ..lib.common_utilities import showErrorMessage
from ..common.maths import Point,Point2D,Vec2D,Vec
from .rftool_contours_utils import *

@RFTool.action_call('contours tool')
class RFTool_Contours(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self): pass

    def name(self): return "Contours"
    def icon(self): return "rf_contours_icon"
    def description(self): return 'Contours!!'

    def start(self):
        self.rfwidget.set_widget('line', color=(1.0, 1.0, 1.0))
        self.rfwidget.set_line_callback(self.line)
        self.update()

    def update(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        self.loops_data = [{
            'loop': loop,
            'plane': loop_plane(loop),
            'count': len(loop),
            'radius': loop_radius(loop),
            } for loop in sel_loops]

    @RFTool.dirty_when_done
    def line(self):
        xy0,xy1 = self.rfwidget.line2D
        if (xy1-xy0).length < 0.001: return

        plane = self.rfcontext.Point2D_to_Plane(xy0, xy1)
        ray = self.rfcontext.Point2D_to_Ray(xy0 + (xy1-xy0)/2)

        crawl = self.rfcontext.plane_intersection_crawl(ray, plane)
        if not crawl: return

        self.rfcontext.undo_push('cut')

        # find two closest selected loops, one on each side
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        sel_loop_planes = [loop_plane(loop) for loop in sel_loops]
        sel_loops_pos = [(i,plane.distance_to(p.o),len(sel_loops[i])) for i,p in enumerate(sel_loop_planes) if plane.side(p.o) > 0]
        sel_loops_neg = [(i,plane.distance_to(p.o),len(sel_loops[i])) for i,p in enumerate(sel_loop_planes) if plane.side(p.o) < 0]
        sel_loops_pos.sort(key=lambda x:x[1])
        sel_loops_neg.sort(key=lambda x:x[1])
        sel_loop_pos = None if not sel_loops_pos else sel_loops_pos[0]
        sel_loop_neg = None if not sel_loops_neg else sel_loops_neg[0]

        if sel_loop_pos is not None and sel_loop_neg is not None:
            if sel_loop_pos[2] != sel_loop_neg[2]:
                # selected loops do not have same count of vertices
                # choosing the closer loop
                if sel_loop_pos[1] < sel_loop_neg[1]:
                    sel_loop_neg = None
                else:
                    sel_loop_pos = None
                #showErrorMessage('Selected loops do not have same count of vertices')
        if sel_loop_pos is not None:
            count = sel_loop_pos[2]
        elif sel_loop_neg is not None:
            count = sel_loop_neg[2]
        else:
            count = 16

        pts = [c for (f0,e,f1,c) in crawl]
        connected = crawl[0][0] is not None
        length = sum((c0-c1).length for c0,c1 in iter_pairs(pts, connected))

        step_size = length / count
        verts,edges,faces = [],[],[]
        dist = 0
        for c0,c1 in iter_pairs(pts, connected):
            d = (c1-c0).length
            while dist - d <= 0:
                # create new vert between c0 and c1
                p = c0 + (c1 - c0) * (dist / d)
                verts += [self.rfcontext.new_vert_point(p)]
                dist += step_size
                count -= 1 # make sure we don't add too many!
                if count == 0: break
            dist -= d
            if count == 0: break

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

        if sel_loop_pos:
            bridge(sel_loops[sel_loop_pos[0]])
        if sel_loop_neg:
            bridge(sel_loops[sel_loop_neg[0]])

        if sel_loop_pos:
            edges += edges_of_loop(sel_loops[sel_loop_pos[0]])
        if sel_loop_neg:
            edges += edges_of_loop(sel_loops[sel_loop_neg[0]])

        self.rfcontext.select(verts + edges, supparts=False) # + faces)
        self.update()

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


    def draw_postview(self): pass
    def draw_postpixel(self):
        point_to_point2d = self.rfcontext.Point_to_Point2D
        up = self.rfcontext.Vec_up()
        size_to_size2D = self.rfcontext.size_to_size2D
        font_id = 0
        bgl.glColor4f(1, 1, 1, 1)
        blf.size(font_id, 12, 72)
        for loop_data in self.loops_data:
            loop = loop_data['loop']
            radius = loop_data['radius']
            count = loop_data['count']
            plane = loop_data['plane']
            cos = [point_to_point2d(vert.co) for vert in loop]
            cos = [co for co in cos if co]
            if not cos: continue
            xy = max(cos, key=lambda co:co.y)
            #xy = point_to_point2d(plane.o + up * radius)
            blf.position(font_id, xy.x, xy.y + 10, 0)
            blf.draw(font_id, '%d' % (count))
