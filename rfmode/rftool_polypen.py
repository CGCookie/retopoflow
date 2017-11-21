import bpy
import bmesh
import math
import bgl
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec,Accel2D
from ..common.ui import UI_Image
from ..common.decorators import stats_wrapper
from ..lib.classes.profiler.profiler import profiler
from .rfmesh import RFVert, RFEdge, RFFace

from ..options import help_polypen

@RFTool.action_call('polypen tool')
class RFTool_PolyPen(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['insert'] = self.modal_insert
        self.FSM['insert alt0'] = self.modal_insert
        self.FSM['move']  = self.modal_move
        self.FSM['move after select'] = self.modal_move_after_select

    def name(self): return "PolyPen"
    def icon(self): return "rf_polypen_icon"
    def description(self): return 'Insert vertices one at a time'
    def helptext(self): return help_polypen

    def start(self):
        self.rfwidget.set_widget('default', color=(1.0, 1.0, 1.0))
        self.next_state = None
        
        self.accel2D = None
        self.target_version = None
        self.view_version = None
        self.mouse_prev = None
        self.recompute = True
        self.defer_recomputing = False
        self.selecting = False

    def get_ui_icon(self):
        self.ui_icon = UI_Image('polypen_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    @profiler.profile
    def update(self):
        # selection has changed, undo/redo was called, etc.
        #self.target_version = None
        self.target_version = self.rfcontext.get_target_version() if self.selecting else None
        self.set_next_state()
    
    @profiler.profile
    def set_next_state(self):
        # TODO: optimize this!!!
        target_version = self.rfcontext.get_target_version()
        view_version = self.rfcontext.get_view_version()
        
        mouse_cur = self.rfcontext.actions.mouse
        mouse_prev = self.mouse_prev
        mouse_moved = 1 if not mouse_prev else mouse_prev.distance_squared_to(mouse_cur)
        self.mouse_prev = mouse_cur
        
        recompute = self.recompute
        recompute |= self.target_version != target_version
        recompute |= self.view_version != view_version
        
        if mouse_moved > 0:
            # mouse is still moving, so defer recomputing until mouse has stopped
            self.recompute = recompute
            return
        
        self.recompute = False
        
        if recompute and not self.defer_recomputing:
            self.target_version = target_version
            self.view_version = view_version
            
            # get visible geometry
            pr = profiler.start('determining visible geometry')
            self.vis_verts = self.rfcontext.visible_verts()
            self.vis_edges = self.rfcontext.visible_edges(verts=self.vis_verts)
            self.vis_faces = self.rfcontext.visible_faces(verts=self.vis_verts)
            pr.done()
            
            pr = profiler.start('creating 2D acceleration structure')
            p2p = self.rfcontext.Point_to_Point2D
            self.accel2D = Accel2D(self.vis_verts, self.vis_edges, self.vis_faces, p2p)
            pr.done()
            
        # get selected geometry
        pr = profiler.start('getting selected geometry')
        self.sel_verts = self.rfcontext.rftarget.get_selected_verts()
        self.sel_edges = self.rfcontext.rftarget.get_selected_edges()
        self.sel_faces = self.rfcontext.rftarget.get_selected_faces()
        pr.done()
        
        # get visible geometry near mouse
        pr = profiler.start('getting nearby and hovered geometry')
        max_dist = self.drawing.scale(10)
        geom = self.accel2D.get(mouse_cur, max_dist)
        verts,edges,faces = ([g for g in geom if type(g) is t] for t in [RFVert,RFEdge,RFFace])
        nearby_verts = self.rfcontext.nearest2D_verts(verts=verts, max_dist=10)
        nearby_edges = self.rfcontext.nearest2D_edges(edges=edges, max_dist=10)
        nearby_face  = self.rfcontext.nearest2D_face(faces=faces, max_dist=10)
        # get hover geometry in sorted order
        self.hover_verts = [v for v,_ in sorted(nearby_verts, key=lambda vd:vd[1])]
        self.hover_edges = [e for e,_ in sorted(nearby_edges, key=lambda ed:ed[1])]
        self.hover_faces = [nearby_face]
        # get nearest geometry
        self.nearest_vert = next(iter(self.hover_verts), None)
        self.nearest_edge = next(iter(self.hover_edges), None)
        self.nearest_face = next(iter(self.hover_faces), None)
        pr.done()
        
        # determine next state based on current selection, hovered geometry
        num_verts = len(self.sel_verts)
        num_edges = len(self.sel_edges)
        num_faces = len(self.sel_faces)
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
        

    @profiler.profile
    def modal_main(self):
        self.set_next_state()

        if self.rfcontext.actions.pressed('insert'):
            return 'insert'

        if self.rfcontext.actions.pressed('insert alt0'):
            return 'insert alt0'

        if self.rfcontext.actions.pressed(['select','select add'], unpress=False):
            pr = profiler.start('selecting geometry')
            
            sel_only = self.rfcontext.actions.pressed('select')
            self.rfcontext.actions.unpress()
            
            if sel_only: self.rfcontext.undo_push('select')
            else: self.rfcontext.undo_push('select add')
            
            sel = self.nearest_vert or self.nearest_edge or self.nearest_face
            self.selecting = True
            self.rfcontext.select(sel, only=sel_only)
            self.selecting = False
            
            if not sel_only:
                # do not move selection if adding
                pr.done()
                return
            
            self.prep_move()
            pr.done()
            return 'move after select'

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

    def set_vis_bmverts(self):
        self.vis_bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in self.vis_verts if bmv not in self.sel_verts]

    def prep_move(self, bmverts=None):
        if not bmverts: bmverts = self.sel_verts
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.set_vis_bmverts()
        self.mousedown = self.rfcontext.actions.mouse
        self.defer_recomputing = True

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
                if d is not None and d < self.rfcontext.drawing.scale(15):
                    bme0,bmv2 = nearest_edge.split()
                    bmv1.merge(bmv2)
                    bmf = None
                    for f0 in bmv0.link_faces:
                        for f1 in bmv1.link_faces:
                            if f0 == f1:
                                bmf = f0
                                break
                    if bmf is not None:
                        if not bmv0.share_edge(bmv1):
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
                bme = bmv0.shared_edge(bmv1) or self.rfcontext.new_edge((bmv0, bmv1))
                self.rfcontext.select(bmv1)
            self.mousedown = self.rfcontext.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv1.co)
            if not xy:
                print('Could not insert: ' + str(bmv1.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv1, xy)]
            self.set_vis_bmverts()
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
            self.set_vis_bmverts()
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
            bme0.select = True
            bme1.select = True
            self.rfcontext.select(bmv1.link_edges)
            if self.nearest_vert and not self.nearest_vert.select:
                self.nearest_vert.merge(bmv1)
                bmv1 = self.nearest_vert
                self.rfcontext.clean_duplicate_bmedges(bmv1)
                for bme in bmv1.link_edges: bme.select &= len(bme.link_faces)==1
                bme01,bme12 = bmv0.shared_edge(bmv1),bmv1.shared_edge(bmv2)
                if len(bme01.link_faces) == 1: bme01.select = True
                if len(bme12.link_faces) == 1: bme12.select = True
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
            self.set_vis_bmverts()
            return 'move'

        nearest_edge,d = self.rfcontext.nearest2D_edge(edges=self.vis_edges)
        bmv = self.rfcontext.new2D_vert_mouse()
        if not bmv:
            self.rfcontext.undo_cancel()
            return 'main'
        if d is not None and d < self.rfcontext.drawing.scale(15):
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
        self.set_vis_bmverts()
        return 'move'

    def mergeSnapped(self):
        """ Merging colocated visible verts """
        # TODO: remove colocated faces
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        update_verts = []
        for bmv,xy in self.bmverts:
            xy_updated = xy + delta
            for bmv1,xy1 in self.vis_bmverts:
                if not bmv1.is_valid: continue
                if (xy_updated - xy1).length < self.rfcontext.drawing.scale(10):
                    shared_edge = bmv.shared_edge(bmv1)
                    if shared_edge:
                        bmv1 = shared_edge.collapse()
                    else:
                        shared_faces = bmv.shared_faces(bmv1)
                        self.rfcontext.delete_faces(shared_faces, del_empty_edges=False, del_empty_verts=False)
                        bmv1.merge(bmv)
                    self.rfcontext.select(bmv1)
                    update_verts += [bmv1]
                    break
        if update_verts:
            self.rfcontext.update_verts_faces(update_verts)
            self.update()

    @profiler.profile
    def modal_move_after_select(self):
        if self.rfcontext.actions.released(['select','select add']):
            return 'main'
        if (self.rfcontext.actions.mouse - self.mousedown).length > 7:
            self.move_done_pressed = 'confirm'
            self.move_done_released = ['select']
            self.move_cancelled = 'cancel no select'
            self.rfcontext.undo_push('move after select')
            return 'move'
    
    @RFTool.dirty_when_done
    @profiler.profile
    def modal_move(self):
        released = self.rfcontext.actions.released
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            self.defer_recomputing = False
            self.mergeSnapped()
            return 'main'
        if self.move_done_released and all(released(item) for item in self.move_done_released):
            self.defer_recomputing = False
            self.mergeSnapped()
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.defer_recomputing = False
            self.rfcontext.undo_cancel()
            return 'main'

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            xy_updated = xy + delta
            # check if xy_updated is "close" to any visible verts (in image plane)
            # if so, snap xy_updated to vert position (in image plane)
            for bmv1,xy1 in self.vis_bmverts:
                if (xy_updated - xy1).length < self.rfcontext.drawing.scale(10):
                    set2D_vert(bmv, xy1)
                    break
            else:
                set2D_vert(bmv, xy_updated)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)

    def draw_lines(self, coords):
        l = len(coords)
        
        # 2d lines
        self.drawing.line_width(2.0)
        bgl.glDisable(bgl.GL_CULL_FACE)
        bgl.glDepthMask(bgl.GL_FALSE)

        # draw above
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glColor4f(1,1,1,0.5)
        if l == 1:
            bgl.glBegin(bgl.GL_POINTS)
            bgl.glVertex3f(*coords[0])
            bgl.glEnd()
        elif l == 2:
            bgl.glBegin(bgl.GL_LINES)
            bgl.glVertex3f(*coords[0])
            bgl.glVertex3f(*coords[1])
            bgl.glEnd()
        elif l == 3:
            bgl.glBegin(bgl.GL_TRIANGLES)
            bgl.glVertex3f(*coords[0])
            bgl.glVertex3f(*coords[1])
            bgl.glVertex3f(*coords[2])
            bgl.glEnd()
        else:
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex3f(*coords[0])
            bgl.glVertex3f(*coords[1])
            bgl.glVertex3f(*coords[2])
            bgl.glVertex3f(*coords[3])
            bgl.glEnd()

        # draw below
        bgl.glDepthFunc(bgl.GL_GREATER)
        bgl.glColor4f(1,1,1,0.1)
        if l == 1:
            bgl.glBegin(bgl.GL_POINTS)
            bgl.glVertex3f(*coords[0])
            bgl.glEnd()
        elif l == 2:
            bgl.glBegin(bgl.GL_LINES)
            bgl.glVertex3f(*coords[0])
            bgl.glVertex3f(*coords[1])
            bgl.glEnd()
        elif l == 3:
            bgl.glBegin(bgl.GL_TRIANGLES)
            bgl.glVertex3f(*coords[0])
            bgl.glVertex3f(*coords[1])
            bgl.glVertex3f(*coords[2])
            bgl.glEnd()
        else:
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex3f(*coords[0])
            bgl.glVertex3f(*coords[1])
            bgl.glVertex3f(*coords[2])
            bgl.glVertex3f(*coords[3])
            bgl.glEnd()

        bgl.glEnable(bgl.GL_CULL_FACE)
        bgl.glDepthMask(bgl.GL_TRUE)
        bgl.glDepthFunc(bgl.GL_LEQUAL)


    @profiler.profile
    def draw_postview(self):
        if self.rfcontext.nav: return
        if not self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl: return
        hit_pos = self.rfcontext.actions.hit_pos
        if not hit_pos: return

        self.set_next_state()

        if self.next_state == 'new vertex':
            nearest_edge,d = self.rfcontext.nearest2D_edge(edges=self.vis_edges)
            if d is not None and d < self.rfcontext.drawing.scale(15):
                self.draw_lines([nearest_edge.verts[0].co, hit_pos])
                self.draw_lines([nearest_edge.verts[1].co, hit_pos])

        elif self.next_state == 'vert-edge':
            sel_verts = self.sel_verts
            bmv0 = next(iter(sel_verts))
            if self.nearest_vert:
                p0 = self.nearest_vert.co
            else:
                p0 = hit_pos
                nearest_edge,d = self.rfcontext.nearest2D_edge(edges=self.vis_edges)
                if d is not None and d < self.rfcontext.drawing.scale(15):
                    self.draw_lines([nearest_edge.verts[0].co, p0])
                    self.draw_lines([nearest_edge.verts[1].co, p0])
            self.draw_lines([bmv0.co, p0])

        elif self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl:
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

            elif self.next_state == 'edges-face' or self.next_state == 'tri-quad':
                e1,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
                bmv1,bmv2 = e1.verts
                if self.nearest_vert and not self.nearest_vert.select:
                    p0 = self.nearest_vert.co
                else:
                    p0 = hit_pos
                self.draw_lines([p0, bmv1.co, bmv2.co])
