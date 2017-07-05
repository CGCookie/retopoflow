import bpy
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
        elif num_verts == 3 and num_edges == 3 and num_faces == 1:
            self.next_state = 'triangle-quad'
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
            bmv,_ = self.rfcontext.nearest2D_vert_mouse()
            self.rfcontext.select(bmv, only=False)
            return

        if self.rfcontext.actions.pressed('select'):
            self.rfcontext.undo_push('select')
            bmv,_ = self.rfcontext.nearest2D_vert_mouse()
            self.rfcontext.select(bmv)
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

        if self.next_state == 'edge-face':
            bme = next(iter(sel_edges))
            bmv0,bmv1 = bme.verts
            bmv2 = self.rfcontext.new2D_vert_mouse()
            if not bmv2:
                self.rfcontext.undo_cancel()
                return 'main'
            bmf = self.rfcontext.new_face([bmv0, bmv1, bmv2])
            self.rfcontext.select(bmf)
            self.mousedown = self.rfcontext.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv2.co)
            if not xy:
                print('Could not insert: ' + str(bmv2.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv2, xy)]
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

    def draw_postview(self):
        if self.next_state == 'vert-edge':
            p0 = self.rfcontext.hit_pos
            if p0 == None:
                return
            sel_verts = self.rfcontext.rftarget.get_selected_verts()
            bmv1 = next(iter(sel_verts))

            # 2d lines
            bgl.glLineWidth(2.0)
            bgl.glDisable(bgl.GL_CULL_FACE)
            bgl.glDepthMask(bgl.GL_FALSE)
            
            # draw above
            bgl.glDepthFunc(bgl.GL_LEQUAL)
            bgl.glColor4f(1,1,1,0.5)
            bgl.glBegin(bgl.GL_LINES)
            bgl.glVertex3f(p0.x, p0.y, p0.z)
            bgl.glVertex3f(bmv1.co.x, bmv1.co.y, bmv1.co.z)
            bgl.glEnd()
            
            # draw below
            bgl.glDepthFunc(bgl.GL_GREATER)
            bgl.glColor4f(1,1,1,0.1)
            bgl.glBegin(bgl.GL_LINES)
            bgl.glVertex3f(p0.x, p0.y, p0.z)
            bgl.glVertex3f(bmv1.co.x, bmv1.co.y, bmv1.co.z)
            bgl.glEnd()
            
            bgl.glEnable(bgl.GL_CULL_FACE)
            bgl.glDepthMask(bgl.GL_TRUE)
            bgl.glDepthFunc(bgl.GL_LEQUAL)

            # TODO: draw edge
            # print("draws edge")
            return
        if self.next_state == 'edge-face':
            # TODO: draw faces
            # print("draws face")
            return
        if self.next_state == 'triangle-quad':
            # TODO: draw quad
            # print("draws quad")
            return

