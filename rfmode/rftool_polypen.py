import bpy
import bmesh
import math
import bgl
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.ui import UI_Image
from . import rftool_polypen_icon


@RFTool.action_call('polypen tool')
class RFTool_PolyPen(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['insert'] = self.modal_insert
        self.FSM['insert alt0'] = self.modal_insert
        self.FSM['move']  = self.modal_move

    def name(self): return "PolyPen"
    def icon(self): return "rf_polypen_icon"
    def description(self): return 'Insert vertices one at a time'

    def start(self):
        self.rfwidget.set_widget('default', color=(1.0, 1.0, 1.0))
        self.next_state = None

        self.target_version = None
        self.view_version = None

    def get_ui_icon(self):
        icon = rftool_polypen_icon.image
        self.ui_icon = UI_Image(icon)
        self.ui_icon.set_size(16, 16)
        return self.ui_icon

    def update(self):
        # selection has changed, undo/redo was called, etc.
        self.target_version = None
        self.set_next_state()

    def set_next_state(self):
        # TODO: optimize this!!!
        target_version = self.rfcontext.get_target_version()
        view_version = self.rfcontext.get_view_version()

        recompute = False
        recompute |= self.target_version != target_version
        recompute |= self.view_version != view_version

        if recompute:
            # print('recompute! ' + str(view_version))

            self.target_version = target_version
            self.view_version = view_version

            # get visible geometry
            self.vis_verts = self.rfcontext.visible_verts()
            self.vis_edges = self.rfcontext.visible_edges(verts=self.vis_verts)
            self.vis_faces = self.rfcontext.visible_faces(verts=self.vis_verts)

            # get selected geometry
            self.sel_verts = self.rfcontext.rftarget.get_selected_verts()
            self.sel_edges = self.rfcontext.rftarget.get_selected_edges()
            self.sel_faces = self.rfcontext.rftarget.get_selected_faces()
            num_verts = len(self.sel_verts)
            num_edges = len(self.sel_edges)
            num_faces = len(self.sel_faces)

            # determine next state based on current selection
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

        # get visible geometry near mouse
        nearby_verts = self.rfcontext.nearest2D_verts(verts=self.vis_verts)
        nearby_edges = self.rfcontext.nearest2D_edges(edges=self.vis_edges)
        nearby_face = self.rfcontext.nearest2D_face(faces=self.vis_faces)

        # get hover geometry in sorted order
        self.hover_verts = [v for v,_ in sorted(nearby_verts, key=lambda vd:vd[1])]
        self.hover_edges = [e for e,_ in sorted(nearby_edges, key=lambda ed:ed[1])]
        self.hover_faces = [nearby_face]

        # get nearest geometry
        self.nearest_vert = next(iter(self.hover_verts), None)
        self.nearest_edge = next(iter(self.hover_edges), None)
        self.nearest_face = next(iter(self.hover_faces), None)


    def modal_main(self):
        self.set_next_state()

        if self.rfcontext.actions.pressed('insert'):
            return 'insert'

        if self.rfcontext.actions.pressed('insert alt0'):
            return 'insert alt0'

        if self.rfcontext.actions.pressed(['select','select add'], unpress=False):
            sel_only = self.rfcontext.actions.pressed('select')
            self.rfcontext.actions.unpress()

            if sel_only: self.rfcontext.undo_push('select')
            else: self.rfcontext.undo_push('select add')

            sel = self.nearest_vert or self.nearest_edge or self.nearest_face
            self.rfcontext.select(sel, only=sel_only)

            if not sel_only: return     # do not move selection if adding

            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = ['select']
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

        # if self.rfcontext.actions.pressed('SPACE'):
        #     bmes = self.sel_edges
        #     bmvs = []
        #     for bme in bmes:
        #         _,bmv = bme.split()
        #         bmvs.append(bmv)
        #     self.rfcontext.select(bmvs)
        #     self.rfcontext.dirty()

        if self.rfcontext.actions.pressed('delete'):
            self.rfcontext.undo_push('delete')
            self.rfcontext.delete_selection()
            self.rfcontext.dirty()
            return

    def prep_move(self, bmverts=None):
        if not bmverts: bmverts = self.sel_verts
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.mousedown = self.rfcontext.actions.mouse

    @RFTool.dirty_when_done
    def modal_insert(self):
        self.rfcontext.undo_push('insert')

        self.move_done_pressed = None
        self.move_done_released = ['insert', 'insert alt0']
        self.move_cancelled = 'cancel'



        if self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl and not self.next_state in ['new vertex', 'vert-edge']:
            self.next_state = 'vert-edge'
            nearest_vert,_ = self.rfcontext.nearest2D_vert(verts=self.sel_verts)
            self.rfcontext.select(nearest_vert)

        sel_verts = self.sel_verts
        sel_edges = self.sel_edges
        sel_faces = self.sel_faces

        if self.next_state == 'vert-edge':
            bmv0 = next(iter(sel_verts))
            if not self.rfcontext.actions.shift and self.rfcontext.actions.ctrl:
                nearest_edge,d = self.rfcontext.nearest2D_edge(edges=self.vis_edges)
                bmv1 = self.rfcontext.new2D_vert_mouse()
                if not bmv1:
                    self.rfcontext.undo_cancel()
                    return 'main'
                if d is not None and d < 15:
                    bme0,bmv2 = nearest_edge.split()
                    bmv1.merge(bmv2)
                    bmf = None
                    for f0 in bmv0.link_faces:
                        for f1 in bmv1.link_faces:
                            if f0 == f1:
                                bmf = f0
                                break
                    if bmf is not None:
                        bmf.split(bmv0, bmv1)
                    self.rfcontext.select(bmv1)
                else:
                    bme = self.rfcontext.new_edge((bmv0, bmv1))
                    self.rfcontext.select(bme)
            elif self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl:
                if self.nearest_vert:
                    bmv1 = self.nearest_vert
                else:
                    bmv1 = self.rfcontext.new2D_vert_mouse()
                    if not bmv1:
                        self.rfcontext.undo_cancel()
                        return 'main'
                bme = self.rfcontext.new_edge((bmv0, bmv1))
                self.rfcontext.select(bmv1)
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
                bme0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
                bmv0,bmv1 = bme0.verts

            if self.next_state == 'edge-face':
                bme = next(iter(self.sel_edges))
                bmv0,bmv1 = bme.verts

            if self.nearest_vert and not self.nearest_vert.select:
                bmv2 = self.nearest_vert
                bmf = self.rfcontext.new_face([bmv0, bmv1, bmv2])
                self.rfcontext.clean_duplicate_bmedges(bmv2)
                # else:
                #     self.rfcontext.undo_cancel()
                #     return 'main'
            else:
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

        if self.next_state == 'tri-quad':
            hit_pos = self.rfcontext.actions.hit_pos
            if not hit_pos:
                self.rfcontext.undo_cancel()
                return 'main'
            if not self.sel_edges:
                return 'main'
            bme0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
            bmv0,bmv2 = bme0.verts
            bme1,bmv1 = bme0.split()
            self.rfcontext.select(bmv1.link_edges)
            if self.nearest_vert and not self.nearest_vert.select:
                self.nearest_vert.merge(bmv1)
                bmv1 = self.nearest_vert
                self.rfcontext.clean_duplicate_bmedges(bmv1)
                for bme in bmv1.link_edges: bme.select &= len(bme.link_faces)==1
                # else:
                #     self.rfcontext.undo_cancel()
                #     return 'main'
            else:
                bmv1.co = hit_pos
            self.mousedown = self.rfcontext.actions.mousedown
            self.rfcontext.select(bmv1, only=False)
            xy = self.rfcontext.Point_to_Point2D(bmv1.co)
            if not xy:
                print('Could not insert: ' + str(bmv3.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv1, xy)]
            return 'move'

        nearest_edge,d = self.rfcontext.nearest2D_edge(edges=self.vis_edges)
        bmv = self.rfcontext.new2D_vert_mouse()
        if not bmv:
            self.rfcontext.undo_cancel()
            return 'main'
        if d is not None and d < 15:
            bme0,bmv2 = nearest_edge.split()
            bmv.merge(bmv2)
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
        released = self.rfcontext.actions.released
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            # call function for going through visible verts and merging them if they are colocated
            return 'main'
        if self.move_done_released and all(released(item) for item in self.move_done_released):
            # call function for going through visible verts and merging them if they are colocated
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            # get visible verts before entering modal move
            # check visible verts, if xy + delta is within 5 pixels,
            if (xy + delta)  < rfcontext.drawing.scale(5) :
                set2D_vert(bmv, bmv0.co)
            else:
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
        if self.rfcontext.actions.shift or self.rfcontext.actions.ctrl:
            hit_pos = self.rfcontext.actions.hit_pos
            if not hit_pos: return

            self.set_next_state()

            if self.next_state == 'new vertex':
                nearest_edge,d = self.rfcontext.nearest2D_edge(edges=self.vis_edges)
                if d is not None and d < 15:
                    self.draw_lines([nearest_edge.verts[0].co, hit_pos])
                    self.draw_lines([nearest_edge.verts[1].co, hit_pos])
                return

            if self.next_state == 'vert-edge':
                sel_verts = self.sel_verts
                bmv0 = next(iter(sel_verts))
                if self.nearest_vert:
                    p0 = self.nearest_vert.co
                else:
                    p0 = hit_pos
                    nearest_edge,d = self.rfcontext.nearest2D_edge(edges=self.vis_edges)
                    if d is not None and d < 15:
                        self.draw_lines([nearest_edge.verts[0].co, p0])
                        self.draw_lines([nearest_edge.verts[1].co, p0])
                self.draw_lines([bmv0.co, p0])
                return

            if self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl:
                if self.next_state in ['edge-face', 'edges-face', 'tri-quad']:
                    nearest_vert,_ = self.rfcontext.nearest2D_vert(verts=self.sel_verts)
                    self.draw_lines([nearest_vert.co, hit_pos])

            elif not self.rfcontext.actions.shift and self.rfcontext.actions.ctrl:
                if self.next_state == 'edge-face':
                    sel_edges = self.sel_edges
                    e1 = next(iter(sel_edges))
                    bmv1,bmv2 = e1.verts
                    if self.nearest_vert and not self.nearest_vert.select:
                        p0 = self.nearest_vert.co
                    else:
                        p0 = hit_pos
                    self.draw_lines([p0, bmv1.co, bmv2.co])
                    return

                if self.next_state == 'edges-face' or self.next_state == 'tri-quad':
                    e1,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
                    bmv1,bmv2 = e1.verts
                    if self.nearest_vert and not self.nearest_vert.select:
                        p0 = self.nearest_vert.co
                    else:
                        p0 = hit_pos
                    self.draw_lines([p0, bmv1.co, bmv2.co])
                    return
