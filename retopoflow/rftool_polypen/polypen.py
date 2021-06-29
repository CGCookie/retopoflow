'''
Copyright (C) 2021 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import random

import bgl
from mathutils.geometry import intersect_line_line_2d as intersect2d_segment_segment

from ..rftool import RFTool
from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory
from ..rfmesh.rfmesh_wrapper import RFVert, RFEdge, RFFace

from ...addon_common.common.drawing import (
    CC_DRAW,
    CC_2D_POINTS,
    CC_2D_LINES, CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES, CC_2D_TRIANGLE_FAN,
)
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import Point, Point2D, Vec2D, Vec, Direction2D, intersection2d_line_line, closest2d_point_segment
from ...addon_common.common.fsm import FSM
from ...addon_common.common.globals import Globals
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.drawing import DrawCallbacks
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString


from ...config.options import options, themes


class PolyPen(RFTool):
    name        = 'PolyPen'
    description = 'Create complex topology on vertex-by-vertex basis'
    icon        = 'polypen-icon.png'
    help        = 'polypen.md'
    shortcut    = 'polypen tool'
    statusbar   = '{{insert}} Insert'
    ui_config   = 'polypen_options.html'

    RFWidget_Default   = RFWidget_Default_Factory.create('PolyPen default')
    RFWidget_Crosshair = RFWidget_Default_Factory.create('PolyPen crosshair', 'CROSSHAIR')
    RFWidget_Move      = RFWidget_Default_Factory.create('PolyPen move', 'HAND')
    RFWidget_Knife     = RFWidget_Default_Factory.create('PolyPen knife', 'KNIFE')

    @RFTool.on_init
    def init(self):
        self.rfwidgets = {
            'default': self.RFWidget_Default(self),
            'insert':  self.RFWidget_Crosshair(self),
            'hover':   self.RFWidget_Move(self),
            'knife':   self.RFWidget_Knife(self),
        }
        self.rfwidget = None
        self.update_state_info()
        self.first_time = True
        self._var_merge_dist  = BoundFloat( '''options['polypen merge dist'] ''')
        self._var_automerge   = BoundBool(  '''options['polypen automerge']  ''')
        self._var_insert_mode = BoundString('''options['polypen insert mode']''')
        self.previs_timer = self.actions.start_timer(120.0, enabled=False)

    def update_insert_mode(self):
        mode = options['polypen insert mode']
        self.ui_options_label.innerText = f'PolyPen: {mode}'
        self.ui_insert_modes.dirty(cause='insert mode change', children=True)

    @RFTool.on_ui_setup
    def ui(self):
        ui_options = self.document.body.getElementById('polypen-options')
        self.ui_options_label = ui_options.getElementById('polypen-summary-label')
        self.ui_insert_modes  = ui_options.getElementById('polypen-insert-modes')
        self.update_insert_mode()

    @RFTool.on_reset
    def reset(self):
        self.previs_timer.stop()

    @RFTool.on_reset
    @RFTool.on_target_change
    @RFTool.on_view_change
    @FSM.onlyinstate('main')
    @profiler.function
    def update_state_info(self):
        with profiler.code('getting selected geometry'):
            self.sel_verts = self.rfcontext.rftarget.get_selected_verts()
            self.sel_edges = self.rfcontext.rftarget.get_selected_edges()
            self.sel_faces = self.rfcontext.rftarget.get_selected_faces()

        with profiler.code('getting visible geometry'):
            self.vis_accel = self.rfcontext.get_vis_accel()
            self.vis_verts = self.rfcontext.accel_vis_verts
            self.vis_edges = self.rfcontext.accel_vis_edges
            self.vis_faces = self.rfcontext.accel_vis_faces

        if self.rfcontext.loading_done:
            self.set_next_state(force=True)

    @RFTool.on_mouse_stop
    @FSM.onlyinstate({'main'})
    def update_next_state_mouse(self):
        self.set_next_state(force=True)
        tag_redraw_all('PolyPen mouse stop')

    @profiler.function
    def set_next_state(self, force=False):
        '''
        determines what the next state will be, based on selected mode, selected geometry, and hovered geometry
        '''
        if not self.actions.mouse and not force: return

        with profiler.code('getting nearest geometry'):
            self.nearest_vert,_ = self.rfcontext.accel_nearest2D_vert(max_dist=options['polypen merge dist'])
            self.nearest_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['polypen merge dist'])
            self.nearest_face,_ = self.rfcontext.accel_nearest2D_face(max_dist=options['polypen merge dist'])
            self.nearest_geom = self.nearest_vert or self.nearest_edge or self.nearest_face

        # determine next state based on current selection, hovered geometry
        num_verts = len(self.sel_verts)
        num_edges = len(self.sel_edges)
        num_faces = len(self.sel_faces)

        if self.nearest_edge and self.nearest_edge.select:      # overriding: if hovering over a selected edge, knife it!
            self.next_state = 'knife selected edge'

        elif options['polypen insert mode'] == 'Tri/Quad':
            if num_verts == 1 and num_edges == 0 and num_faces == 0:
                self.next_state = 'vert-edge'
            elif num_edges and num_faces == 0:
                quad_snap = False
                if not self.nearest_vert and self.nearest_edge:
                    quad_snap = True
                    quad_snap &= len(self.nearest_edge.link_faces) <= 1
                    quad_snap &= not any(v in self.sel_verts for v in self.nearest_edge.verts)
                    quad_snap &= not any(e in f.edges for v in self.nearest_edge.verts for f in v.link_faces for e in self.sel_edges)
                if quad_snap:
                    self.next_state = 'edge-quad-snap'
                else:
                    self.next_state = 'edge-face'
            elif num_verts == 3 and num_edges == 3 and num_faces == 1:
                self.next_state = 'tri-quad'
            else:
                self.next_state = 'new vertex'

        elif options['polypen insert mode'] == 'Quad-Only':
            # a Desmos construction of how this works: https://www.desmos.com/geometry/bmmx206thi
            if num_verts == 1 and num_edges == 0 and num_faces == 0:
                self.next_state = 'vert-edge'
            elif num_edges:
                quad_snap = False
                if not self.nearest_vert and self.nearest_edge:
                    quad_snap = True
                    quad_snap &= len(self.nearest_edge.link_faces) <= 1
                    quad_snap &= not any(v in self.sel_verts for v in self.nearest_edge.verts)
                    quad_snap &= not any(e in f.edges for v in self.nearest_edge.verts for f in v.link_faces for e in self.sel_edges)
                if quad_snap:
                    self.next_state = 'edge-quad-snap'
                else:
                    self.next_state = 'edge-quad'
            else:
                self.next_state = 'new vertex'

        elif options['polypen insert mode'] == 'Tri-Only':
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
                    self.next_state = 'edge-quad-snap'
                else:
                    self.next_state = 'edge-face'
            elif num_verts == 3 and num_edges == 3 and num_faces == 1:
                self.next_state = 'edge-face'
            else:
                self.next_state = 'new vertex'

        elif options['polypen insert mode'] == 'Edge-Only':
            if num_verts == 0:
                self.next_state = 'new vertex'
            else:
                if self.nearest_edge:
                    self.next_state = 'vert-edge'
                else:
                    self.next_state = 'vert-edge-vert'

        else:
            assert False, f'Unhandled PolyPen insert mode: {options["polypen insert mode"]}'

    @FSM.on_state('main', 'enter')
    def main_enter(self):
        self.update_state_info()

    @FSM.on_state('main')
    def main(self):
        if self.first_time:
            self.set_next_state(force=True)
            self.first_time = False
            tag_redraw_all('PolyPen mousemove')

        self.previs_timer.enable(self.actions.using_onlymods('insert'))
        if self.actions.using_onlymods('insert'):
            if self.next_state == 'knife selected edge':
                self.rfwidget = self.rfwidgets['knife']
            else:
                self.rfwidget = self.rfwidgets['insert']
        elif self.nearest_geom and self.nearest_geom.select:
            self.rfwidget = self.rfwidgets['hover']
        else:
            self.rfwidget = self.rfwidgets['default']

        for rfwidget in self.rfwidgets.values():
            if self.rfwidget == rfwidget: continue
            if rfwidget.inactive_passthrough():
                self.rfwidget = rfwidget
                return

        if self.actions.pressed('pie menu alt0'):
            def callback(option):
                if not option: return
                options['polypen insert mode'] = option
                self.update_insert_mode()
            self.rfcontext.show_pie_menu([
                'Tri/Quad',
                'Quad-Only',
                'Tri-Only',
                'Edge-Only',
            ], callback, highlighted=options['polypen insert mode'])
            return

        if self.actions.pressed('insert'):
            return 'insert'

        if self.nearest_geom and self.nearest_geom.select:
            if self.actions.pressed('action'):
                self.rfcontext.undo_push('grab')
                self.prep_move(defer_recomputing=False)
                return 'move after select'

        if self.actions.pressed({'select path add'}):
            return self.rfcontext.select_path(
                {'edge', 'face'},
                kwargs_select={'supparts': False},
            )

        if self.actions.pressed({'select paint', 'select paint add'}, unpress=False):
            sel_only = self.actions.pressed('select paint')
            self.actions.unpress()
            return self.rfcontext.setup_smart_selection_painting(
                {'vert','edge','face'},
                selecting=not sel_only,
                deselect_all=sel_only,
                kwargs_select={'supparts': False},
                kwargs_deselect={'subparts': False},
            )

        if self.actions.pressed({'select single', 'select single add'}, unpress=False):
            sel_only = self.actions.pressed('select single')
            self.actions.unpress()
            bmv,_ = self.rfcontext.accel_nearest2D_vert(max_dist=options['select dist'])
            bme,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['select dist'])
            bmf,_ = self.rfcontext.accel_nearest2D_face(max_dist=options['select dist'])
            sel = bmv or bme or bmf
            if not sel_only and not sel: return
            self.rfcontext.undo_push('select')
            if sel_only: self.rfcontext.deselect_all()
            if not sel: return
            if sel.select: self.rfcontext.deselect(sel, subparts=False)
            else:          self.rfcontext.select(sel, supparts=False, only=sel_only)
            return

        if self.actions.pressed('grab'):
            self.rfcontext.undo_push('move grabbed')
            self.prep_move()
            self.move_done_pressed = ['confirm', 'confirm drag']
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move'


    def set_vis_bmverts(self):
        self.vis_bmverts = [
            (bmv, self.rfcontext.Point_to_Point2D(bmv.co))
            for bmv in self.vis_verts
            if bmv.is_valid and bmv not in self.sel_verts
        ]


    @FSM.on_state('insert')
    def insert(self):
        self.rfcontext.undo_push('insert')
        return self._insert()

    def _get_edge_quad_verts(self):
        '''
        this function is used in quad-only mode to find positions of quad verts based on selected edge and mouse position
        a Desmos construction of how this works: https://www.desmos.com/geometry/5w40xowuig
        '''
        e0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
        if not e0: return (None, None, None, None)
        bmv0,bmv1 = e0.verts
        xy0 = self.rfcontext.Point_to_Point2D(bmv0.co)
        xy1 = self.rfcontext.Point_to_Point2D(bmv1.co)
        d01 = (xy0 - xy1).length
        mid01 = xy0 + (xy1 - xy0) / 2
        mid23 = self.actions.mouse
        mid0123 = mid01 + (mid23 - mid01) / 2
        between = mid23 - mid01
        if between.length < 0.0001: return (None, None, None, None)
        perp = Direction2D((-between.y, between.x))
        if perp.dot(xy1 - xy0) < 0: perp.reverse()
        #pts = intersect_line_line(xy0, xy1, mid0123, mid0123 + perp)
        #if not pts: return (None, None, None, None)
        #intersection = pts[1]
        intersection = intersection2d_line_line(xy0, xy1, mid0123, mid0123 + perp)
        if not intersection: return (None, None, None, None)
        intersection = Point2D(intersection)

        toward = Direction2D(mid23 - intersection)
        if toward.dot(perp) < 0: d01 = -d01

        # push intersection out just a bit to make it more stable (prevent crossing) when |between| < d01
        between_len = between.length * Direction2D(xy1 - xy0).dot(perp)

        for tries in range(32):
            v = toward * (d01 / 2)
            xy2, xy3 = mid23 + v, mid23 - v

            # try to prevent quad from crossing
            v03 = xy3 - xy0
            if v03.dot(between) < 0 or v03.length < between_len:
                xy3 = xy0 + Direction2D(v03) * (between_len * (-1 if v03.dot(between) < 0 else 1))
            v12 = xy2 - xy1
            if v12.dot(between) < 0 or v12.length < between_len:
                xy2 = xy1 + Direction2D(v12) * (between_len * (-1 if v12.dot(between) < 0 else 1))

            if self.rfcontext.raycast_sources_Point2D(xy2)[0] and self.rfcontext.raycast_sources_Point2D(xy3)[0]: break
            d01 /= 2
        else:
            return (None, None, None, None)

        nearest_vert,_ = self.rfcontext.nearest2D_vert(point=xy2, verts=self.vis_verts, max_dist=options['polypen merge dist'])
        if nearest_vert: xy2 = self.rfcontext.Point_to_Point2D(nearest_vert.co)
        nearest_vert,_ = self.rfcontext.nearest2D_vert(point=xy3, verts=self.vis_verts, max_dist=options['polypen merge dist'])
        if nearest_vert: xy3 = self.rfcontext.Point_to_Point2D(nearest_vert.co)

        return (xy0, xy1, xy2, xy3)

    @RFTool.dirty_when_done
    def _insert(self):
        self.last_delta = None
        self.move_done_pressed = None
        self.move_done_released = 'insert'
        self.move_cancelled = 'cancel'

        if self.actions.shift and not self.actions.ctrl and not self.next_state in ['new vertex', 'vert-edge']:
            self.next_state = 'vert-edge'
            nearest_vert,_ = self.rfcontext.nearest2D_vert(verts=self.sel_verts, max_dist=options['polypen merge dist'])
            self.rfcontext.select(nearest_vert)

        sel_verts = self.sel_verts
        sel_edges = self.sel_edges
        sel_faces = self.sel_faces

        if self.next_state == 'knife selected edge':            # overriding: if hovering over a selected edge, knife it!
            # self.nearest_edge and self.nearest_edge.select:
            #print('knifing selected, hovered edge')
            bmv = self.rfcontext.new2D_vert_mouse()
            if not bmv:
                self.rfcontext.undo_cancel()
                return 'main'
            bme0,bmv2 = self.nearest_edge.split()
            bmv.merge(bmv2)
            self.rfcontext.select(bmv)
            self.mousedown = self.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv.co)
            if not xy:
                #print('Could not insert: ' + str(bmv.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv, xy)] if bmv else []
            self.set_vis_bmverts()
            return 'move'

        if self.next_state in {'vert-edge', 'vert-edge-vert'}:
            bmv0 = next(iter(sel_verts))

            if self.next_state == 'vert-edge':
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

            elif self.next_state == 'vert-edge-vert':
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

            self.mousedown = self.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv1.co)
            if not xy:
                dprint('Could not insert: ' + str(bmv1.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv1, xy)] if bmv1 else []
            self.set_vis_bmverts()
            return 'move'

        if self.next_state == 'edge-face':
            bme,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
            if not bme: return
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
            self.mousedown = self.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv2.co)
            if not xy:
                dprint('Could not insert: ' + str(bmv2.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv2, xy)] if bmv2 else []
            self.set_vis_bmverts()
            return 'move'

        if self.next_state == 'edge-quad':
            xy0,xy1,xy2,xy3 = self._get_edge_quad_verts()
            if xy0 is None or xy1 is None or xy2 is None or xy3 is None: return
            # a Desmos construction of how this works: https://www.desmos.com/geometry/bmmx206thi
            e0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
            if not e0: return
            bmv0,bmv1 = e0.verts

            bmv2,_ = self.rfcontext.nearest2D_vert(point=xy2, verts=self.vis_verts, max_dist=options['polypen merge dist'])
            if not bmv2: bmv2 = self.rfcontext.new2D_vert_point(xy2)
            bmv3,_ = self.rfcontext.nearest2D_vert(point=xy3, verts=self.vis_verts, max_dist=options['polypen merge dist'])
            if not bmv3: bmv3 = self.rfcontext.new2D_vert_point(xy3)
            if not bmv2 or not bmv3:
                self.rfcontext.undo_cancel()
                return 'main'
            e1 = bmv2.shared_edge(bmv3)
            if not e1: e1 = self.rfcontext.new_edge([bmv2, bmv3])
            bmf = self.rfcontext.new_face([bmv0, bmv1, bmv2, bmv3])
            bmes = [bmv1.shared_edge(bmv2), bmv0.shared_edge(bmv3), bmv2.shared_edge(bmv3)]
            self.rfcontext.select(bmes, subparts=False)
            self.mousedown = self.actions.mousedown
            self.bmverts = []
            if bmv2: self.bmverts.append((bmv2, self.rfcontext.Point_to_Point2D(bmv2.co)))
            if bmv3: self.bmverts.append((bmv3, self.rfcontext.Point_to_Point2D(bmv3.co)))
            self.set_vis_bmverts()
            return 'move'

        if self.next_state == 'edge-quad-snap':
            e0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
            e1 = self.nearest_edge
            if not e0 or not e1: return
            bmv0,bmv1 = e0.verts
            bmv2,bmv3 = e1.verts
            p0,p1 = self.rfcontext.Point_to_Point2D(bmv0.co),self.rfcontext.Point_to_Point2D(bmv1.co)
            p2,p3 = self.rfcontext.Point_to_Point2D(bmv2.co),self.rfcontext.Point_to_Point2D(bmv3.co)
            if intersect2d_segment_segment(p1, p2, p3, p0): bmv2,bmv3 = bmv3,bmv2
            # if e0.vector2D(self.rfcontext.Point_to_Point2D).dot(e1.vector2D(self.rfcontext.Point_to_Point2D)) > 0:
            #     bmv2,bmv3 = bmv3,bmv2
            bmf = self.rfcontext.new_face([bmv0, bmv1, bmv2, bmv3])
            # select all non-manifold edges that share vertex with e1
            bmes = [e for e in bmv2.link_edges + bmv3.link_edges if not e.is_manifold and not e.share_face(e1)]
            if not bmes:
                bmes = [bmv1.shared_edge(bmv2), bmv0.shared_edge(bmv3)]
            self.rfcontext.select(bmes, subparts=False)
            return 'main'

        if self.next_state == 'tri-quad':
            hit_pos = self.actions.hit_pos
            if not hit_pos:
                self.rfcontext.undo_cancel()
                return 'main'
            if not self.sel_edges:
                return 'main'
            bme0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
            if not bme0: return
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
            self.mousedown = self.actions.mousedown
            self.rfcontext.select(bmv1, only=False)
            xy = self.rfcontext.Point_to_Point2D(bmv1.co)
            if not xy:
                dprint('Could not insert: ' + str(bmv3.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv1, xy)] if bmv1 else []
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
        self.mousedown = self.actions.mousedown
        xy = self.rfcontext.Point_to_Point2D(bmv.co)
        if not xy:
            dprint('Could not insert: ' + str(bmv.co))
            self.rfcontext.undo_cancel()
            return 'main'
        self.bmverts = [(bmv, xy)] if bmv else []
        self.set_vis_bmverts()
        return 'move'


    def mergeSnapped(self):
        """ Merging colocated visible verts """

        if not options['polypen automerge']: return

        # TODO: remove colocated faces
        if self.mousedown is None: return
        delta = Vec2D(self.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        update_verts = []
        merge_dist = self.rfcontext.drawing.scale(options['polypen merge dist'])
        for bmv,xy in self.bmverts:
            if not xy: continue
            xy_updated = xy + delta
            for bmv1,xy1 in self.vis_bmverts:
                if not xy1: continue
                if bmv1 == bmv: continue
                if not bmv1.is_valid: continue
                d = (xy_updated - xy1).length
                if (xy_updated - xy1).length > merge_dist:
                    continue
                bmv1.merge_robust(bmv)
                self.rfcontext.select(bmv1)
                update_verts += [bmv1]
                break
        if update_verts:
            self.rfcontext.update_verts_faces(update_verts)
            self.set_next_state()


    def prep_move(self, bmverts=None, defer_recomputing=True):
        if not bmverts: bmverts = self.sel_verts
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts if bmv and bmv.is_valid]
        self.set_vis_bmverts()
        self.mousedown = self.actions.mouse
        self.last_delta = None
        self.defer_recomputing = defer_recomputing

    @FSM.on_state('move after select')
    @profiler.function
    def modal_move_after_select(self):
        if self.actions.released('action'):
            return 'main'
        if (self.actions.mouse - self.mousedown).length > 7:
            self.last_delta = None
            self.move_done_pressed = None
            self.move_done_released = 'action'
            self.move_cancelled = 'cancel'
            self.rfcontext.undo_push('move after select')
            return 'move'

    @FSM.on_state('move', 'enter')
    def move_enter(self):
        self.move_opts = {
            'vis_accel': self.rfcontext.get_custom_vis_accel(selection_only=False, include_edges=False, include_faces=False),
        }
        self.rfcontext.split_target_visualization_selected()
        self.previs_timer.start()
        self.rfcontext.set_accel_defer(True)

    @FSM.on_state('move')
    @profiler.function
    def modal_move(self):
        if self.move_done_pressed and self.actions.pressed(self.move_done_pressed):
            self.defer_recomputing = False
            self.mergeSnapped()
            return 'main'
        if self.move_done_released and self.actions.released(self.move_done_released, ignoremods=True):
            self.defer_recomputing = False
            self.mergeSnapped()
            return 'main'
        if self.move_cancelled and self.actions.pressed('cancel'):
            self.defer_recomputing = False
            self.rfcontext.undo_cancel()
            return 'main'

        if not self.actions.mousemove_stop: return
        # # only update verts on timer events and when mouse has moved
        # if not self.actions.timer: return
        # if self.actions.mouse_prev == self.actions.mouse: return

        delta = Vec2D(self.actions.mouse - self.mousedown)
        if delta == self.last_delta: return
        self.last_delta = delta
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            if not xy: continue
            xy_updated = xy + delta
            # check if xy_updated is "close" to any visible verts (in image plane)
            # if so, snap xy_updated to vert position (in image plane)
            if options['polypen automerge']:
                bmv1,d = self.rfcontext.accel_nearest2D_vert(point=xy_updated, vis_accel=self.move_opts['vis_accel'], max_dist=options['polypen merge dist'])
                if bmv1 is None:
                    set2D_vert(bmv, xy_updated)
                    continue
                xy1 = self.rfcontext.Point_to_Point2D(bmv1.co)
                if not xy1:
                    set2D_vert(bmv, xy_updated)
                    continue
                set2D_vert(bmv, xy1)
            else:
                set2D_vert(bmv, xy_updated)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)
        self.rfcontext.dirty()

    @FSM.on_state('move', 'exit')
    def move_exit(self):
        self.previs_timer.stop()
        self.rfcontext.set_accel_defer(False)
        self.rfcontext.clear_split_target_visualization()


    def draw_lines(self, coords, poly_alpha=0.2):
        line_color = themes['new']
        poly_color = [line_color[0], line_color[1], line_color[2], line_color[3] * poly_alpha]
        l = len(coords)
        coords = [self.rfcontext.Point_to_Point2D(co) for co in coords]
        if not all(coords): return

        if l == 1:
            with Globals.drawing.draw(CC_2D_POINTS) as draw:
                draw.color(line_color)
                for c in coords:
                    draw.vertex(c)

        elif l == 2:
            with Globals.drawing.draw(CC_2D_LINES) as draw:
                draw.color(line_color)
                draw.vertex(coords[0])
                draw.vertex(coords[1])

        else:
            with Globals.drawing.draw(CC_2D_LINE_LOOP) as draw:
                draw.color(line_color)
                for co in coords: draw.vertex(co)

            with Globals.drawing.draw(CC_2D_TRIANGLE_FAN) as draw:
                draw.color(poly_color)
                draw.vertex(coords[0])
                for co1,co2 in iter_pairs(coords[1:], False):
                    draw.vertex(co1)
                    draw.vertex(co2)

    @DrawCallbacks.on_draw('post2d')
    @FSM.onlyinstate('main')
    def draw_postpixel(self):
        # TODO: put all logic into set_next_state(), such as vertex snapping, edge splitting, etc.

        #if self.rfcontext.nav or self.mode != 'main': return
        if not self.actions.using_onlymods('insert'): return  # 'insert alt1'??
        hit_pos = self.actions.hit_pos
        if not hit_pos: return

        self.set_next_state()

        bgl.glEnable(bgl.GL_BLEND)
        CC_DRAW.stipple(pattern=[4,4])
        CC_DRAW.point_size(8)
        CC_DRAW.line_width(2)

        if self.next_state == 'knife selected edge':
            bmv1,bmv2 = self.nearest_edge.verts
            faces = self.nearest_edge.link_faces
            if faces:
                for f in faces:
                    lco = []
                    for v0,v1 in iter_pairs(f.verts, True):
                        lco.append(v0.co)
                        if (v0 == bmv1 and v1 == bmv2) or (v0 == bmv2 and v1 == bmv1):
                            lco.append(hit_pos)
                    self.draw_lines(lco)
            else:
                self.draw_lines([bmv1.co, hit_pos])
                self.draw_lines([bmv2.co, hit_pos])

        elif self.next_state == 'new vertex':
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

        elif self.next_state in {'vert-edge', 'vert-edge-vert'}:
            sel_verts = self.sel_verts
            bmv0 = next(iter(sel_verts))
            if self.nearest_vert:
                p0 = self.nearest_vert.co
            elif self.next_state == 'vert-edge':
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
            elif self.next_state == 'vert-edge-vert':
                p0 = hit_pos
            else:
                return
            self.draw_lines([bmv0.co, p0])

        elif self.actions.shift and not self.actions.ctrl:
            if self.next_state in ['edge-face', 'edge-quad', 'edge-quad-snap', 'tri-quad']:
                nearest_vert,_ = self.rfcontext.nearest2D_vert(verts=self.sel_verts, max_dist=options['polypen merge dist'])
                if nearest_vert:
                    self.draw_lines([nearest_vert.co, hit_pos])

        elif not self.actions.shift and self.actions.ctrl:
            if self.next_state == 'edge-face':
                e0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges) #next(iter(self.sel_edges))
                if not e0: return
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
                # a Desmos construction of how this works: https://www.desmos.com/geometry/bmmx206thi
                xy0, xy1, xy2, xy3 = self._get_edge_quad_verts()
                if xy0 is None: return
                co0 = self.rfcontext.raycast_sources_Point2D(xy0)[0]
                co1 = self.rfcontext.raycast_sources_Point2D(xy1)[0]
                co2 = self.rfcontext.raycast_sources_Point2D(xy2)[0]
                co3 = self.rfcontext.raycast_sources_Point2D(xy3)[0]
                self.draw_lines([co1, co2, co3, co0])

            elif self.next_state == 'edge-quad-snap':
                e0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
                e1 = self.nearest_edge
                if not e0 or not e1: return
                bmv0,bmv1 = e0.verts
                bmv2,bmv3 = e1.verts
                p0,p1 = self.rfcontext.Point_to_Point2D(bmv0.co),self.rfcontext.Point_to_Point2D(bmv1.co)
                p2,p3 = self.rfcontext.Point_to_Point2D(bmv2.co),self.rfcontext.Point_to_Point2D(bmv3.co)
                if intersect2d_segment_segment(p1, p2, p3, p0): bmv2,bmv3 = bmv3,bmv2
                # if e0.vector2D(self.rfcontext.Point_to_Point2D).dot(e1.vector2D(self.rfcontext.Point_to_Point2D)) > 0:
                #     bmv2,bmv3 = bmv3,bmv2
                self.draw_lines([bmv0.co, bmv1.co, bmv2.co, bmv3.co])

            elif self.next_state == 'tri-quad':
                if self.nearest_vert and not self.nearest_vert.select:
                    p0 = self.nearest_vert.co
                else:
                    p0 = hit_pos
                e1,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
                if not e1: return
                bmv1,bmv2 = e1.verts
                f = next(iter(e1.link_faces), None)
                if not f: return
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

        # self.drawing.disable_stipple()