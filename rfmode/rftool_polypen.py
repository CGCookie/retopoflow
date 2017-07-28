import bpy
import bmesh
import math
import bgl
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec

@RFTool.action_call('polypen tool')
class RFTool_PolyPen(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['insert'] = self.modal_insert
        self.FSM['move']  = self.modal_move

    def name(self): return "PolyPen"
    def icon(self): return "rf_polypen_icon"
    def description(self): return 'Insert vertices one at a time'

    def start(self):
        self.rfwidget.set_widget('default', color=(1.0, 1.0, 1.0))
        self.next_state = None

    def set_next_state(self):
        sel_verts = self.rfcontext.rftarget.get_selected_verts()
        sel_edges = self.rfcontext.rftarget.get_selected_edges()
        sel_faces = self.rfcontext.rftarget.get_selected_faces()
        num_verts = len(sel_verts)
        num_edges = len(sel_edges)
        num_faces = len(sel_faces)
        if num_verts == 1 and num_edges == 0 and num_faces == 0:
            self.next_state = 'vert-edge'
        elif num_edges == 1 and num_faces == 0:
            self.next_state = 'edge-face'
        elif num_edges == 2 and num_faces == 0:
            self.next_state = 'edges-face'
        elif num_verts == 3 and num_edges == 3 and num_faces == 1:
            self.next_state = 'tri-quad'
        else:
            self.next_state = 'new vertex'

    def modal_main(self):
        self.set_next_state()

        if self.rfcontext.actions.pressed('insert'):
            return 'insert'

        # if self.rfcontext.actions.pressed('action'):
        #     self.rfcontext.undo_push('polypen place vert')
        #     radius = self.rfwidget.get_scaled_radius()
        #     nearest = self.rfcontext.nearest_verts_mouse(radius)
        #     if not nearest:
        #         self.rfcontext.undo_cancel()
        #         return
        #     self.bmverts = [(bmv, Point(bmv.co), d3d) for bmv,d3d in nearest]
        #     self.rfcontext.select([bmv for bmv,_,_ in self.bmverts])
        #     self.mousedown = self.rfcontext.actions.mousedown
        #     return 'move'

        if self.rfcontext.actions.pressed('select add'):
            self.rfcontext.undo_push('select add')
            bmv,d = self.rfcontext.nearest2D_vert_mouse()
            if d < 15:
                self.rfcontext.select(bmv, only=False)
            else:
                bme,_ = self.rfcontext.nearest2D_edge_mouse()
                self.rfcontext.select(bme, only=False)
            return

        if self.rfcontext.actions.pressed('select'):
            self.rfcontext.undo_push('select')
            bmv,d = self.rfcontext.nearest2D_vert_mouse()
            if d < 15:
                self.rfcontext.select(bmv)
            else:
                bme,_ = self.rfcontext.nearest2D_edge_mouse()
                self.rfcontext.select(bme)
            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = 'select'
            self.move_cancelled = 'cancel no select'
            self.rfcontext.undo_push('move single')
            return 'move'

        if self.rfcontext.actions.pressed('grab'):
            self.rfcontext.undo_push('move grabbed')
            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move'

        if self.rfcontext.actions.pressed('SPACE'):
            bmes = self.rfcontext.get_selected_edges()
            bmvs = []
            for bme in bmes:
                _,bmv = bme.split()
                bmvs.append(bmv)
            self.rfcontext.select(bmvs)
            self.rfcontext.dirty()

    def prep_move(self, bmverts=None):
        if not bmverts: bmverts = self.rfcontext.get_selected_verts()
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.mousedown = self.rfcontext.actions.mouse

    @RFTool.dirty_when_done
    def modal_insert(self):
        self.rfcontext.undo_push('insert')

        self.move_done_pressed = None
        self.move_done_released = 'insert'
        self.move_cancelled = 'cancel'

        sel_verts = self.rfcontext.rftarget.get_selected_verts()
        sel_edges = self.rfcontext.rftarget.get_selected_edges()
        sel_faces = self.rfcontext.rftarget.get_selected_faces()

        if self.next_state == 'vert-edge':
            bmv0 = next(iter(sel_verts))
            bmv1 = self.rfcontext.new2D_vert_mouse()
            if not bmv1:
                self.rfcontext.undo_cancel()
                return 'main'
            bme = self.rfcontext.new_edge((bmv0, bmv1))
            self.rfcontext.select(bme)
            self.mousedown = self.rfcontext.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv1.co)
            if not xy:
                print('Could not insert: ' + str(bmv1.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv1, xy)]
            return 'move'

        if self.next_state == 'edge-face' or self.next_state == 'edges-face':
            if self.next_state == 'edges-face':
                bme0,_ = self.rfcontext.nearest2D_edge_mouse(edges=sel_edges)
                bmv0,bmv1 = bme0.verts

            if self.next_state == 'edge-face':
                bme = next(iter(sel_edges))
                bmv0,bmv1 = bme.verts

            nearest_vert,d = self.rfcontext.nearest2D_vert_mouse()
            if d < 15:
                bmv2 = nearest_vert
            else:
                bmv2 = self.rfcontext.new2D_vert_mouse()
                if not bmv2:
                    self.rfcontext.undo_cancel()
                    return 'main'

            bmf = self.rfcontext.new_face([bmv0, bmv1, bmv2])
            if d < 15:
                self.rfcontext.clean_duplicate_bmedges(bmv2)
            self.rfcontext.select(bmf)
            self.mousedown = self.rfcontext.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv2.co)
            if not xy:
                print('Could not insert: ' + str(bmv2.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv2, xy)]
            return 'move'

        if self.next_state == 'tri-quad':
            hit_pos = self.rfcontext.actions.hit_pos
            if not hit_pos:
                self.rfcontext.undo_cancel()
                return 'main'
            if not sel_edges:
                return 'main'
            bme0,_ = self.rfcontext.nearest2D_edge_mouse(edges=sel_edges)
            bmv0,bmv2 = bme0.verts
            bme1,bmv1 = bme0.split()
            nearest_vert,d = self.rfcontext.nearest2D_vert_mouse()
            if d < 15:
                pos = nearest_vert.co
            else:
                pos = hit_pos
            bmv1.co = pos
            if d < 15:
                self.rfcontext.clean_duplicate_bmedges(bmv1)

            self.mousedown = self.rfcontext.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv1.co)
            self.rfcontext.select(bmv1.link_edges)
            if not xy:
                print('Could not insert: ' + str(bmv3.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv1, xy)]
            return 'move'

        bmv = self.rfcontext.new2D_vert_mouse()
        if not bmv:
            self.rfcontext.undo_cancel()
            return 'main'
        self.rfcontext.select(bmv)
        self.mousedown = self.rfcontext.actions.mousedown
        xy = self.rfcontext.Point_to_Point2D(bmv.co)
        if not xy:
            print('Could not insert: ' + str(bmv.co))
            self.rfcontext.undo_cancel()
            return 'main'
        self.bmverts = [(bmv, xy)]
        return 'move'

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
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            set2D_vert(bmv, xy + delta)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)

    def draw_lines(self, coords):
        # 2d lines
        self.drawing.line_width(2.0)
        bgl.glDisable(bgl.GL_CULL_FACE)
        bgl.glDepthMask(bgl.GL_FALSE)

        # draw above
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glColor4f(1,1,1,0.5)
        if len(coords) == 1:
            bgl.glBegin(bgl.GL_POINTS)
        if len(coords) == 2:
            bgl.glBegin(bgl.GL_LINES)
        elif len(coords) == 3:
            bgl.glBegin(bgl.GL_TRIANGLES)
        else:
            bgl.glBegin(bgl.GL_QUADS)
        for co in coords:
            bgl.glVertex3f(co.x, co.y, co.z)
        bgl.glEnd()

        # draw below
        bgl.glDepthFunc(bgl.GL_GREATER)
        bgl.glColor4f(1,1,1,0.1)
        if len(coords) == 1:
            bgl.glBegin(bgl.GL_POINTS)
        elif len(coords) == 2:
            bgl.glBegin(bgl.GL_LINES)
        elif len(coords) == 3:
            bgl.glBegin(bgl.GL_TRIANGLES)
        else:
            bgl.glBegin(bgl.GL_QUADS)
        for co in coords:
            bgl.glVertex3f(co.x, co.y, co.z)
        bgl.glEnd()

        bgl.glEnable(bgl.GL_CULL_FACE)
        bgl.glDepthMask(bgl.GL_TRUE)
        bgl.glDepthFunc(bgl.GL_LEQUAL)


    def draw_postview(self):
        hit_pos = self.rfcontext.actions.hit_pos
        if not hit_pos: return
        self.set_next_state()

        if self.next_state == 'new vertex':
            return

        if self.next_state == 'vert-edge':
            sel_verts = self.rfcontext.rftarget.get_selected_verts()
            bmv1 = next(iter(sel_verts))
            self.draw_lines([hit_pos, bmv1.co])
            return

        if self.next_state == 'edge-face':
            sel_edges = self.rfcontext.rftarget.get_selected_edges()
            e1 = next(iter(sel_edges))
            bmv1,bmv2 = e1.verts
            nearest_vert,d = self.rfcontext.nearest2D_vert_mouse()
            if d < 15:
                p0 = nearest_vert.co
            else:
                p0 = hit_pos
            self.draw_lines([p0, bmv1.co, bmv2.co])
            return

        if self.next_state == 'edges-face' or self.next_state == 'tri-quad':
            sel_edges = self.rfcontext.rftarget.get_selected_edges()
            e1,_ = self.rfcontext.nearest2D_edge_mouse(edges=sel_edges)
            bmv1,bmv2 = e1.verts
            nearest_vert,d = self.rfcontext.nearest2D_vert_mouse()
            if d < 15:
                p0 = nearest_vert.co
            else:
                p0 = hit_pos
            self.draw_lines([p0, bmv1.co, bmv2.co])
            return
