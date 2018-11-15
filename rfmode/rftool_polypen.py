'''
Copyright (C) 2018 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, Christopher Gearhart

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import math
import bpy
import bmesh
import bgl
from .rftool import RFTool
from .rfmesh import RFVert, RFEdge, RFFace
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.ui import UI_Image, UI_Checkbox, UI_Number
from ..common.utils import iter_pairs
from ..common.decorators import stats_wrapper
from ..common.debug import dprint
from ..common.profiler import profiler
from ..keymaps import default_rf_keymaps
from ..options import themes, options
from ..help import help_polypen

@RFTool.action_call('polypen tool')
class RFTool_PolyPen(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['selectadd/deselect'] = self.modal_selectadd_deselect
        self.FSM['select'] = self.modal_select
        self.FSM['insert'] = self.modal_insert
        self.FSM['insert alt0'] = self.modal_insert
        self.FSM['move']  = self.modal_move
        self.FSM['move after select'] = self.modal_move_after_select

    def name(self): return "PolyPen"
    def icon(self): return "rf_polypen_icon"
    def description(self): return 'Insert vertices one at a time'
    def helptext(self): return help_polypen
    def get_label(self): return 'PolyPen (%s)' % ','.join(default_rf_keymaps['polypen tool'])
    def get_tooltip(self): return 'PolyPen (%s)' % ','.join(default_rf_keymaps['polypen tool'])

    def start(self):
        self.rfwidget.set_widget('default', color=(1.0, 1.0, 1.0))
        self.next_state = None

    def get_ui_icon(self):
        self.ui_icon = UI_Image('polypen_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon

    def get_ui_options(self):
        return [
            UI_Number('Merge Dist', *options.gettersetter('polypen merge dist', setwrap=lambda v:max(1, int(v))), tooltip='Pixel distance for merging and snapping'),
            UI_Checkbox('Automerge', *options.gettersetter('polypen automerge'), tooltip='Automatically merge nearby vertices'),
            UI_Checkbox('Triangle Only', *options.gettersetter('polypen triangle only'), tooltip='If enabled, PolyPen prefers to insert triangles only.'),
            ]

    @profiler.profile
    def update(self):
        # selection has changed, undo/redo was called, etc.
        self.set_next_state()

    @profiler.profile
    def set_next_state(self):
        if not self.rfcontext.actions.mouse: return

        pr = profiler.start('getting selected geometry')
        self.sel_verts = self.rfcontext.rftarget.get_selected_verts()
        self.sel_edges = self.rfcontext.rftarget.get_selected_edges()
        self.sel_faces = self.rfcontext.rftarget.get_selected_faces()
        pr.done()

        pr = profiler.start('getting visible geometry')
        self.vis_accel = self.rfcontext.get_vis_accel()
        self.vis_verts = self.rfcontext.accel_vis_verts
        self.vis_edges = self.rfcontext.accel_vis_edges
        self.vis_faces = self.rfcontext.accel_vis_faces
        pr.done()

        pr = profiler.start('getting nearest geometry')
        self.nearest_vert,_ = self.rfcontext.accel_nearest2D_vert(max_dist=options['polypen merge dist'])
        self.nearest_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['polypen merge dist'])
        self.nearest_face = self.rfcontext.accel_nearest2D_face(max_dist=options['polypen merge dist'])
        pr.done()

        # determine next state based on current selection, hovered geometry
        num_verts = len(self.sel_verts)
        num_edges = len(self.sel_edges)
        num_faces = len(self.sel_faces)
        if num_verts == 1 and num_edges == 0 and num_faces == 0:
            self.next_state = 'vert-edge'
        elif num_edges and num_faces == 0:
            quad = False
            if not self.nearest_vert and self.nearest_edge:
                quad = True
                quad &= len(self.nearest_edge.link_faces) <= 1
                quad &= not any(v in self.sel_verts for v in self.nearest_edge.verts)
                quad &= not any(e in f.edges for v in self.nearest_edge.verts for f in v.link_faces for e in self.sel_edges)
            if quad:
                self.next_state = 'edge-quad'
            else:
                self.next_state = 'edge-face'
        elif num_verts == 3 and num_edges == 3 and num_faces == 1:
            if options['polypen triangle only']:
                self.next_state = 'edge-face'
            else:
                self.next_state = 'tri-quad'
        else:
            self.next_state = 'new vertex'


    @profiler.profile
    def modal_main(self):
        self.set_next_state()

        # if self.rfcontext.actions.pressed('F5'):
        #     assert False
        # if self.rfcontext.actions.pressed('F6'):
        #     x = 42 / 0

        if self.rfcontext.actions.pressed('insert'):
            return 'insert'

        if self.rfcontext.actions.pressed('insert alt0'):
            return 'insert alt0'

        if self.rfcontext.actions.pressed('action'):
            self.rfcontext.undo_push('grab')
            # sel = self.nearest_vert or self.nearest_edge or self.nearest_face
            # if not sel:
            #     self.rfcontext.deselect_all()
            #     return
            # self.rfcontext.select(sel, only=True)
            self.prep_move(defer_recomputing=False)
            return 'move after select'

        if self.rfcontext.actions.pressed('select'):
            self.rfcontext.undo_push('select')
            self.rfcontext.deselect_all()
            return 'select'

        if self.rfcontext.actions.pressed('select add'):
            bmv,_ = self.rfcontext.accel_nearest2D_vert(max_dist=options['select dist'])
            bme,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['select dist'])
            bmf = self.rfcontext.accel_nearest2D_face(max_dist=options['select dist'])
            sel = bmv or bme or bmf
            if not sel: return
            if sel.select:
                self.mousedown = self.rfcontext.actions.mouse
                return 'selectadd/deselect'
            return 'select'

        if self.rfcontext.actions.pressed('grab'):
            self.rfcontext.undo_push('move grabbed')
            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move'

    @profiler.profile
    def modal_selectadd_deselect(self):
        if not self.rfcontext.actions.using(['select','select add']):
            self.rfcontext.undo_push('deselect')
            bmv,_ = self.rfcontext.accel_nearest2D_vert(max_dist=options['select dist'])
            bme,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['select dist'])
            bmf = self.rfcontext.accel_nearest2D_face(max_dist=options['select dist'])
            sel = bmv or bme or bmf
            if sel and sel.select: self.rfcontext.deselect(sel)
            return 'main'
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        if delta.length > self.drawing.scale(5):
            self.rfcontext.undo_push('select add')
            return 'select'

    @profiler.profile
    def modal_select(self):
        if not self.rfcontext.actions.using(['select','select add']):
            return 'main'
        bmv,_ = self.rfcontext.accel_nearest2D_vert(max_dist=options['select dist'])
        bme,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['select dist'])
        bmf = self.rfcontext.accel_nearest2D_face(max_dist=options['select dist'])
        sel = bmv or bme or bmf
        if not sel or sel.select: return
        self.rfcontext.select(sel, supparts=False, only=False)

    def set_vis_bmverts(self):
        self.vis_bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in self.vis_verts if bmv not in self.sel_verts]

    def prep_move(self, bmverts=None, defer_recomputing=True):
        if not bmverts: bmverts = self.sel_verts
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.set_vis_bmverts()
        self.mousedown = self.rfcontext.actions.mouse
        self.defer_recomputing = defer_recomputing

    @RFTool.dirty_when_done
    def modal_insert(self):
        self.rfcontext.undo_push('insert')

        self.move_done_pressed = None
        self.move_done_released = ['insert', 'insert alt0']
        self.move_cancelled = 'cancel'

        insert_normal     = self.rfcontext.actions.ctrl  and not self.rfcontext.actions.shift
        insert_edges_only = self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl

        if self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl and not self.next_state in ['new vertex', 'vert-edge']:
            self.next_state = 'vert-edge'
            nearest_vert,_ = self.rfcontext.nearest2D_vert(verts=self.sel_verts, max_dist=options['polypen merge dist'])
            self.rfcontext.select(nearest_vert)

        sel_verts = self.sel_verts
        sel_edges = self.sel_edges
        sel_faces = self.sel_faces

        # overriding
        # if hovering over a selected edge, knife it!
        if self.nearest_edge and self.nearest_edge.select:
            if insert_normal:
                #print('knifing selected, hovered edge')
                bmv = self.rfcontext.new2D_vert_mouse()
                if not bmv:
                    self.rfcontext.undo_cancel()
                    return 'main'
                bme0,bmv2 = self.nearest_edge.split()
                bmv.merge(bmv2)
                self.rfcontext.select(bmv)
                self.mousedown = self.rfcontext.actions.mousedown
                xy = self.rfcontext.Point_to_Point2D(bmv.co)
                if not xy:
                    #print('Could not insert: ' + str(bmv.co))
                    self.rfcontext.undo_cancel()
                    return 'main'
                self.bmverts = [(bmv, xy)]
                self.set_vis_bmverts()
                return 'move'


        if self.next_state == 'vert-edge':
            bmv0 = next(iter(sel_verts))
            if insert_normal:
                nearest_vert,dist = self.rfcontext.nearest2D_vert(verts=self.vis_verts, max_dist=options['polypen merge dist'])
                if nearest_vert:
                    bmv1 = nearest_vert
                    lbmf = bmv0.shared_faces(bmv1)
                    if len(lbmf) == 1 and not bmv0.share_edge(bmv1):
                        # split face
                        bmf = lbmf[0]
                        bmf.split(bmv0, bmv1)
                        self.rfcontext.select(bmv1)
                        return 'main'

                nearest_edge,dist = self.rfcontext.nearest2D_edge(edges=self.vis_edges)
                bmv1 = self.rfcontext.new2D_vert_mouse()
                if not bmv1:
                    self.rfcontext.undo_cancel()
                    return 'main'
                if dist is not None and dist < self.rfcontext.drawing.scale(15):
                    if bmv0 in nearest_edge.verts:
                        # selected vert already part of edge; split
                        bme0,bmv2 = nearest_edge.split()
                        bmv1.merge(bmv2)
                        self.rfcontext.select(bmv1)
                    else:
                        bme0,bmv2 = nearest_edge.split()
                        bmv1.merge(bmv2)
                        bmf = next(iter(bmv0.shared_faces(bmv1)), None)
                        if bmf:
                            if not bmv0.share_edge(bmv1):
                                bmf.split(bmv0, bmv1)
                        if not bmv0.share_face(bmv1):
                            bme = self.rfcontext.new_edge((bmv0, bmv1))
                            self.rfcontext.select(bme)
                        self.rfcontext.select(bmv1)
                else:
                    bme = self.rfcontext.new_edge((bmv0, bmv1))
                    self.rfcontext.select(bme)
            elif insert_edges_only:
                if self.nearest_vert:
                    bmv1 = self.nearest_vert
                else:
                    bmv1 = self.rfcontext.new2D_vert_mouse()
                    if not bmv1:
                        self.rfcontext.undo_cancel()
                        return 'main'
                bme = bmv0.shared_edge(bmv1) or self.rfcontext.new_edge((bmv0, bmv1))
                self.rfcontext.select(bmv1)
            else:
                return 'main'
            self.mousedown = self.rfcontext.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv1.co)
            if not xy:
                dprint('Could not insert: ' + str(bmv1.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv1, xy)]
            self.set_vis_bmverts()
            return 'move'

        if self.next_state == 'edge-face':
            bme,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
            bmv0,bmv1 = bme.verts

            if self.nearest_vert and not self.nearest_vert.select:
                bmv2 = self.nearest_vert
                bmf = self.rfcontext.new_face([bmv0, bmv1, bmv2])
                self.rfcontext.clean_duplicate_bmedges(bmv2)
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
                dprint('Could not insert: ' + str(bmv2.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv2, xy)]
            self.set_vis_bmverts()
            return 'move'

        if self.next_state == 'edge-quad':
            e0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
            e1 = self.nearest_edge
            bmv0,bmv1 = e0.verts
            bmv2,bmv3 = e1.verts
            if e0.vector2D(self.rfcontext.Point_to_Point2D).dot(e1.vector2D(self.rfcontext.Point_to_Point2D)) > 0:
                bmv2,bmv3 = bmv3,bmv2
            bmf = self.rfcontext.new_face([bmv0, bmv1, bmv2, bmv3])
            # select all non-manifold edges that share vertex with e1
            bmes = [e for e in bmv2.link_edges + bmv3.link_edges if not e.is_manifold and not e.share_face(e1)]
            if not bmes:
                bmes = [bmv1.shared_edge(bmv2), bmv0.shared_edge(bmv3)]
            self.rfcontext.select(bmes, subparts=False)
            return 'main'

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
                dprint('Could not insert: ' + str(bmv3.co))
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
            dprint('Could not insert: ' + str(bmv.co))
            self.rfcontext.undo_cancel()
            return 'main'
        self.bmverts = [(bmv, xy)]
        self.set_vis_bmverts()
        return 'move'

    def mergeSnapped(self):
        """ Merging colocated visible verts """

        if not options['polypen automerge']: return

        # TODO: remove colocated faces
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        update_verts = []
        for bmv,xy in self.bmverts:
            xy_updated = xy + delta
            for bmv1,xy1 in self.vis_bmverts:
                if not bmv1.is_valid: continue
                if (xy_updated - xy1).length < self.rfcontext.drawing.scale(options['polypen merge dist']):
                    shared_edge = bmv.shared_edge(bmv1)
                    if shared_edge:
                        bmv1 = shared_edge.collapse()
                    else:
                        shared_faces = bmv.shared_faces(bmv1)
                        self.rfcontext.delete_faces(shared_faces, del_empty_edges=False, del_empty_verts=False)
                        bmv1.merge(bmv)
                        self.rfcontext.remove_duplicate_bmfaces(bmv1)
                        self.rfcontext.clean_duplicate_bmedges(bmv1)
                    self.rfcontext.select(bmv1)
                    update_verts += [bmv1]
                    break
        if update_verts:
            self.rfcontext.update_verts_faces(update_verts)
            self.update()

    @profiler.profile
    def modal_move_after_select(self):
        if self.rfcontext.actions.released('action'):
            return 'main'
        if (self.rfcontext.actions.mouse - self.mousedown).length > 7:
            self.move_done_pressed = None
            self.move_done_released = ['action']
            self.move_cancelled = 'cancel'
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
            if options['polypen automerge']:
                for bmv1,xy1 in self.vis_bmverts:
                    if (xy_updated - xy1).length < self.rfcontext.drawing.scale(options['polypen merge dist']):
                        set2D_vert(bmv, xy1)
                        break
                else:
                    set2D_vert(bmv, xy_updated)
            else:
                set2D_vert(bmv, xy_updated)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)

    def draw_lines(self, coords, poly_alpha=0.2):
        line_color = themes['new']
        poly_color = [line_color[0], line_color[1], line_color[2], line_color[3] * poly_alpha]
        l = len(coords)
        coords = [self.rfcontext.Point_to_Point2D(co) for co in coords]

        if l == 1:
            bgl.glColor4f(*line_color)
            bgl.glBegin(bgl.GL_POINTS)
            bgl.glVertex2f(*coords[0])
            bgl.glEnd()
        elif l == 2:
            bgl.glColor4f(*line_color)
            bgl.glBegin(bgl.GL_LINES)
            bgl.glVertex2f(*coords[0])
            bgl.glVertex2f(*coords[1])
            bgl.glEnd()
        else:
            bgl.glColor4f(*line_color)
            bgl.glBegin(bgl.GL_LINE_LOOP)
            for co in coords: bgl.glVertex2f(*co)
            bgl.glEnd()

            bgl.glColor4f(*poly_color)
            co0 = coords[0]
            bgl.glBegin(bgl.GL_TRIANGLES)
            for co1,co2 in iter_pairs(coords[1:],False):
                bgl.glVertex2f(*co0)
                bgl.glVertex2f(*co1)
                bgl.glVertex2f(*co2)
            bgl.glEnd()



    @profiler.profile
    def draw_postpixel(self):
        # TODO: put all logic into set_next_state(), such as vertex snapping, edge splitting, etc.

        if self.rfcontext.nav or self.mode != 'main': return
        if not self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl: return
        hit_pos = self.rfcontext.actions.hit_pos
        if not hit_pos: return

        self.set_next_state()

        bgl.glEnable(bgl.GL_BLEND)
        self.drawing.enable_stipple()
        self.drawing.line_width(2.0)
        self.drawing.point_size(4.0)

        if self.next_state == 'new vertex':
            p0 = hit_pos
            e1,d = self.rfcontext.nearest2D_edge(edges=self.vis_edges)
            if e1:
                bmv1,bmv2 = e1.verts
                if d is not None and d < self.rfcontext.drawing.scale(15):
                    f = next(iter(e1.link_faces), None)
                    if f:
                        lco = []
                        for v0,v1 in iter_pairs(f.verts, True):
                            lco.append(v0.co)
                            if (v0 == bmv1 and v1 == bmv2) or (v0 == bmv2 and v1 == bmv1):
                                lco.append(p0)
                        self.draw_lines(lco)
                    else:
                        self.draw_lines([bmv1.co, hit_pos])
                        self.draw_lines([bmv2.co, hit_pos])
                else:
                    self.draw_lines([hit_pos])
            else:
                self.draw_lines([hit_pos])

        elif self.next_state == 'vert-edge':
            sel_verts = self.sel_verts
            bmv0 = next(iter(sel_verts))
            if self.nearest_vert:
                p0 = self.nearest_vert.co
            else:
                p0 = hit_pos
                e1,d = self.rfcontext.nearest2D_edge(edges=self.vis_edges)
                if e1:
                    bmv1,bmv2 = e1.verts
                    if d is not None and d < self.rfcontext.drawing.scale(15):
                        f = next(iter(e1.link_faces), None)
                        if f:
                            lco = []
                            for v0,v1 in iter_pairs(f.verts, True):
                                lco.append(v0.co)
                                if (v0 == bmv1 and v1 == bmv2) or (v0 == bmv2 and v1 == bmv1):
                                    lco.append(p0)
                            self.draw_lines(lco)
                        else:
                            self.draw_lines([bmv1.co, p0])
                            self.draw_lines([bmv2.co, p0])
            self.draw_lines([bmv0.co, p0])

        elif self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl:
            if self.next_state in ['edge-face', 'edge-quad', 'tri-quad']:
                nearest_vert,_ = self.rfcontext.nearest2D_vert(verts=self.sel_verts, max_dist=options['polypen merge dist'])
                if nearest_vert:
                    self.draw_lines([nearest_vert.co, hit_pos])

        elif not self.rfcontext.actions.shift and self.rfcontext.actions.ctrl:
            if self.next_state == 'edge-face':
                e0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges) #next(iter(self.sel_edges))
                e1,d = self.rfcontext.nearest2D_edge(edges=self.vis_edges)
                if e1 and d < self.rfcontext.drawing.scale(15) and e0 == e1:
                    bmv1,bmv2 = e1.verts
                    p0 = hit_pos
                    f = next(iter(e1.link_faces), None)
                    if f:
                        lco = []
                        for v0,v1 in iter_pairs(f.verts, True):
                            lco.append(v0.co)
                            if (v0 == bmv1 and v1 == bmv2) or (v0 == bmv2 and v1 == bmv1):
                                lco.append(p0)
                        self.draw_lines(lco)
                    else:
                        self.draw_lines([bmv1.co, hit_pos])
                        self.draw_lines([bmv2.co, hit_pos])
                else:
                    # self.draw_lines([hit_pos])
                    bmv1,bmv2 = e0.verts
                    if self.nearest_vert and not self.nearest_vert.select:
                        p0 = self.nearest_vert.co
                    else:
                        p0 = hit_pos
                    self.draw_lines([p0, bmv1.co, bmv2.co])

            elif self.next_state == 'edge-quad':
                e0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
                e1 = self.nearest_edge
                bmv0,bmv1 = e0.verts
                bmv2,bmv3 = e1.verts
                if e0.vector2D(self.rfcontext.Point_to_Point2D).dot(e1.vector2D(self.rfcontext.Point_to_Point2D)) > 0:
                    bmv2,bmv3 = bmv3,bmv2
                self.draw_lines([bmv0.co, bmv1.co, bmv2.co, bmv3.co])

            elif self.next_state == 'tri-quad':
                if self.nearest_vert and not self.nearest_vert.select:
                    p0 = self.nearest_vert.co
                else:
                    p0 = hit_pos
                e1,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
                bmv1,bmv2 = e1.verts
                f = next(iter(e1.link_faces), None)
                lco = []
                for v0,v1 in iter_pairs(f.verts, True):
                    lco.append(v0.co)
                    if (v0 == bmv1 and v1 == bmv2) or (v0 == bmv2 and v1 == bmv1):
                        lco.append(p0)
                self.draw_lines(lco)
                #self.draw_lines([p0, bmv1.co, bmv2.co])

            # elif self.next_state == 'edges-face':
            #     if self.nearest_vert and not self.nearest_vert.select:
            #         p0 = self.nearest_vert.co
            #     else:
            #         p0 = hit_pos
            #     e1,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
            #     bmv1,bmv2 = e1.verts
            #     self.draw_lines([p0, bmv1.co, bmv2.co])

        self.drawing.disable_stipple()
