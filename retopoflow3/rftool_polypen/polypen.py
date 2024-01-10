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
        # needed so main actions using Ctrl (ex: undo, redo, save) can still work
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

    @RFTool.on_events('reset', 'target change', 'view change', 'mouse move')
    @RFTool.not_while_navigating
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

        if self.nearest_geom and self.nearest_geom.select and self.actions.pressed('action'):
            self.rfcontext.undo_push('grab')
            self.prep_move(
                action_confirm=lambda: self.actions.released('action', ignoremods=True),
            )
            return 'move after select'

        if self.actions.pressed('grab'):
            self.rfcontext.undo_push('move grabbed')
            self.prep_move(
                action_confirm=lambda: self.actions.pressed({'confirm', 'confirm drag'}),
            )
            return 'move'

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


    @FSM.on_state('move after select')
    def modal_move_after_select(self):
        if self.actions.released('action'):
            return 'main'

        if (self.actions.mouse - self.mousedown).length >= self.rfcontext.drawing.scale(options['move dist']):
            self.rfcontext.undo_push('move after select')
            return 'move'

    def prep_move(self, *, bmverts=None, action_confirm=None, action_cancel=None, defer_recomputing=True):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        self.bmverts = [bmv for bmv in bmverts if bmv and bmv.is_valid] if bmverts is not None else self.rfcontext.get_selected_verts()
        self.bmverts_xys = [
            (bmv, xy)
            for bmv in self.bmverts
            if bmv and bmv.is_valid and (xy := Point_to_Point2D(bmv.co)) is not None
        ]
        self.move_actions = {
            'confirm': action_confirm or (lambda: self.actions.pressed('confirm')),
            'cancel':  action_cancel  or (lambda: self.actions.pressed('cancel')),
        }
        self.mousedown = self.actions.mouse
        self.last_delta = None
        self.defer_recomputing = defer_recomputing

    @FSM.on_state('move', 'enter')
    def move_enter(self):
        self.move_vis_accel = self.rfcontext.get_accel_visible(selected_only=False)
        # if not self.move_done_released and options['hide cursor on tweak']: self.set_widget('hidden')
        if options['hide cursor on tweak']: self.set_widget('hidden')
        self.rfcontext.split_target_visualization_selected()
        self.rfcontext.fast_update_timer.start()
        self.rfcontext.set_accel_defer(True)
        self.last_delta = None

    @FSM.on_state('move')
    def modal_move(self):
        if self.move_actions['confirm']():
            self.defer_recomputing = False
            if options['polypen automerge']:
                self.rfcontext.merge_verts_by_dist(self.bmverts, options['polypen merge dist'])
            return 'main'

        if self.move_actions['cancel']():
            self.defer_recomputing = False
            self.rfcontext.undo_cancel()
            return 'main'

    @RFTool.on_mouse_move
    @RFTool.once_per_frame
    @FSM.onlyinstate('move')
    def modal_move_update(self):
        delta = Vec2D(self.actions.mouse - self.mousedown)
        if delta == self.last_delta: return
        self.last_delta = delta
        set2D_vert = self.rfcontext.set2D_vert

        for bmv,xy in self.bmverts_xys:
            if not xy: continue
            xy_updated = xy + delta
            # check if xy_updated is "close" to any visible verts (in image plane)
            # if so, snap xy_updated to vert position (in image plane)
            if options['polypen automerge']:
                bmv1,_ = self.rfcontext.accel_nearest2D_vert(point=xy_updated, vis_accel=self.move_vis_accel, max_dist=options['polypen merge dist'])
                if bmv1:
                    xy_updated = self.rfcontext.Point_to_Point2D(bmv1.co)
            set2D_vert(bmv, xy_updated)

        self.rfcontext.update_verts_faces(self.bmverts)
        self.rfcontext.dirty()
        tag_redraw_all('polypen mouse move')

    @FSM.on_state('move', 'exit')
    def move_exit(self):
        self.rfcontext.fast_update_timer.stop()
        self.rfcontext.set_accel_defer(False)
        self.rfcontext.clear_split_target_visualization()



