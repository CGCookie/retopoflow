'''
Copyright (C) 2023 CG Cookie
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

from mathutils.geometry import intersect_line_line_2d as intersect2d_segment_segment

from ..rftool import RFTool
from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory
from ..rfwidgets.rfwidget_hidden  import RFWidget_Hidden_Factory
from ..rfmesh.rfmesh_wrapper import RFVert, RFEdge, RFFace

from ...addon_common.common import gpustate
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
from ...addon_common.common.timerhandler import CallGovernor
from ...addon_common.common.debug import dprint


from .polypen_insert import PolyPen_Insert


from ...config.options import options, themes


class PolyPen(RFTool, PolyPen_Insert):
    name        = 'PolyPen'
    description = 'Create complex topology on vertex-by-vertex basis'
    icon        = 'polypen-icon.png'
    help        = 'polypen.md'
    shortcut    = 'polypen tool'
    statusbar   = '{{insert}} Insert'
    ui_config   = 'polypen_options.html'

    RFWidget_Default   = RFWidget_Default_Factory.create()
    RFWidget_Crosshair = RFWidget_Default_Factory.create(cursor='CROSSHAIR')
    RFWidget_Move      = RFWidget_Default_Factory.create(cursor='HAND')
    RFWidget_Knife     = RFWidget_Default_Factory.create(cursor='KNIFE')
    RFWidget_Hidden    = RFWidget_Hidden_Factory.create()

    @RFTool.on_init
    def init(self):
        self.rfwidgets = {
            'default': self.RFWidget_Default(self),
            'insert':  self.RFWidget_Crosshair(self),
            'hover':   self.RFWidget_Move(self),
            'knife':   self.RFWidget_Knife(self),
            'hidden':  self.RFWidget_Hidden(self),
        }
        self.rfwidget = None
        self.next_state = 'unset'
        self.nearest_vert, self.nearest_edge, self.nearest_face, self.nearest_geom = None, None, None, None
        self.vis_verts, self.vis_edges, self.vis_faces = [], [], []
        self.update_selection()
        self._var_merge_dist  = BoundFloat( '''options['polypen merge dist'] ''')
        self._var_automerge   = BoundBool(  '''options['polypen automerge']  ''')
        self._var_insert_mode = BoundString('''options['polypen insert mode']''')

    def _fsm_in_main(self):
        return self._fsm.state in {'main', 'previs insert'}

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
    @RFTool.on_target_change
    @FSM.onlyinstate('main')
    def update_selection(self):
        self.sel_verts, self.sel_edges, self.sel_faces = self.rfcontext.get_selected_geom()

    @RFTool.on_reset
    @RFTool.on_target_change
    @RFTool.on_view_change
    @RFTool.on_mouse_move
    @FSM.onlyinstate('main')
    def update_nearest(self):
        self.nearest_vert,_ = self.rfcontext.accel_nearest2D_vert(max_dist=options['polypen merge dist'], selected_only=True)
        self.nearest_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['polypen merge dist'], selected_only=True)
        self.nearest_face,_ = self.rfcontext.accel_nearest2D_face(max_dist=options['polypen merge dist'], selected_only=True)
        self.nearest_geom = self.nearest_vert or self.nearest_edge or self.nearest_face

    @FSM.on_state('main', 'enter')
    def main_enter(self):
        self.update_selection()
        self.update_nearest()

    @FSM.on_state('main')
    def main(self):
        if self.actions.using_onlymods('insert'):
            return 'previs insert'

        if self.nearest_geom and self.nearest_geom.select:
            self.set_widget('hover')
        else:
            self.set_widget('default')

        if self.handle_inactive_passthrough(): return

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

        if self.actions.pressed('rip'):
            self._rip_fill = False
            return 'rip'
        if self.actions.pressed('rip fill'):
            self._rip_fill = True
            return 'rip'

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
                use_select_tool=True,
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
            return 'move'


    @FSM.on_state('rip')
    def rip(self):
        # find highest order geometry selected
        # - faces: error
        # - edges: for each selected edge, find nearest adjacent face to mouse cursor and rip edge from other face
        # - verts: for each selected vert, find nearest adjacent edge to mouse cursor and rip vert from faces not adjacent to that edge

        if self.sel_faces:
            self.rfcontext.alert_user('Can only rip a single edge, but a face is selected')
            return 'main'

        if not self.sel_edges and not self.sel_verts:
            self.rfcontext.alert_user('Can only rip a single edge, but none are selected')
            return 'main'

        if self.sel_verts and not self.sel_edges:
            self.rfcontext.alert_user('Ripping vertices is not supported yet')
            return 'main'

        if self.sel_edges and len(self.sel_edges) > 1:
            # a temporary limitation
            self.rfcontext.alert_user('Ripping more than one selected edge is not supported yet')
            return 'main'

        if self.sel_edges:
            # working with first selected edge (current implementation limitation)
            bme = next(iter(self.sel_edges))

            adj_faces = set(bme.link_faces)
            if len(adj_faces) < 2:
                self.rfcontext.alert_user('Edge must have at least two adjacent faces')
                return 'main'

            bmv0, bmv1 = bme.verts
            nearest_face, _ = self.rfcontext.accel_nearest2D_face(faces_only=adj_faces)
            other_face = next(iter({bmf for bmf in bme.link_faces if bmf != nearest_face}), None)

            self.rfcontext.undo_push('rip edge')
            if True:
                bmv2 = bmv0.face_separate(nearest_face)
                bmv3 = bmv1.face_separate(nearest_face)
                move_verts = [bmv2, bmv3]
            else:
                bmv2 = bmv0.face_separate(other_face)
                bmv3 = bmv1.face_separate(other_face)
                move_verts = [bmv0, bmv1]
            self.rfcontext.select(move_verts, only=True)

            if self._rip_fill:
                # only implemented simple fill for now
                self.rfcontext.new_face([bmv0, bmv1, bmv3, bmv2])

            # self.rfcontext.undo_push('move ripped edge')
            self.bmverts = [
                (bmv, self.rfcontext.Point_to_Point2D(bmv.co))
                for bmv in move_verts
            ]
            self.last_delta = None
            self.mousedown = self.actions.mouse
            self.move_done_pressed = ['confirm', 'confirm drag']
            self.move_done_released = None
            return 'move'

        return 'main'

    @FSM.on_state('rip fill')
    def rip_fill(self):
        self.rfcontext.undo_push('rip fill')
        return 'main' # 'move'


    def mergeSnapped(self):
        """ Merging colocated visible verts """

        if not options['polypen automerge']: return

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        accel_data = self.rfcontext.generate_accel_data_struct(selected_only=False, force=True)
        vis_bmverts = [ (bmv, Point_to_Point2D(bmv.co)) for bmv in accel_data.verts ]

        # TODO: remove colocated faces
        if self.mousedown is None: return
        delta = Vec2D(self.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        update_verts = []
        merge_dist = self.rfcontext.drawing.scale(options['polypen merge dist'])
        for bmv,xy in self.bmverts:
            if not xy: continue
            xy_updated = xy + delta
            for bmv1,xy1 in vis_bmverts:
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


    def prep_move(self, bmverts=None, defer_recomputing=True):
        if not bmverts: bmverts = self.sel_verts
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts if bmv and bmv.is_valid]
        self.mousedown = self.actions.mouse
        self.last_delta = None
        self.defer_recomputing = defer_recomputing

    @FSM.on_state('move after select')
    @profiler.function
    def modal_move_after_select(self):
        if self.actions.released('action'):
            return 'main'

        if (self.actions.mouse - self.mousedown).length < options['move dist']:
            return

        self.last_delta = None
        self.move_done_pressed = None
        self.move_done_released = 'action'
        self.rfcontext.undo_push('move after select')
        return 'move'

    @FSM.on_state('move', 'enter')
    def move_enter(self):
        self.move_vis_accel = None
        if not self.move_done_released and options['hide cursor on tweak']: self.set_widget('hidden')
        self.rfcontext.split_target_visualization_selected()
        self.rfcontext.fast_update_timer.start()
        self.rfcontext.set_accel_defer(True)

    @FSM.on_state('move')
    def modal_move(self):
        if self.move_done_pressed and self.actions.pressed(self.move_done_pressed):
            self.defer_recomputing = False
            self.mergeSnapped()
            return 'main'
        if self.move_done_released and self.actions.released(self.move_done_released, ignoremods=True):
            self.defer_recomputing = False
            self.mergeSnapped()
            return 'main'
        if self.actions.pressed('cancel'):
            self.defer_recomputing = False
            self.actions.unuse(self.move_done_released, ignoremods=True, ignoremulti=True)
            self.rfcontext.undo_cancel()
            return 'main'

        if self.actions.mousedown_drag and options['hide cursor on tweak']: self.set_widget('hidden')

        if self.actions.mousemove: self.modal_move_update()

    @RFTool.once_per_frame
    @FSM.onlyinstate('move')
    def modal_move_update(self):
        if self.move_vis_accel is None:
            self.move_vis_accel = self.rfcontext.get_accel_visible(selected_only=False)

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
                bmv1,d = self.rfcontext.accel_nearest2D_vert(point=xy_updated, vis_accel=self.move_vis_accel, max_dist=options['polypen merge dist'])
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
        self.rfcontext.fast_update_timer.stop()
        self.rfcontext.set_accel_defer(False)
        self.rfcontext.clear_split_target_visualization()



