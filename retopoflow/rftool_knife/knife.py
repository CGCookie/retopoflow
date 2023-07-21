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

import time
import random

from mathutils.geometry import intersect_line_line_2d as intersect2d_segment_segment

from ..rftool import RFTool
from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory
from ..rfwidgets.rfwidget_hidden  import RFWidget_Hidden_Factory
from ..rfmesh.rfmesh_wrapper import RFVert, RFEdge, RFFace

from ...addon_common.common.drawing import (
    CC_DRAW,
    CC_2D_POINTS,
    CC_2D_LINES, CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES, CC_2D_TRIANGLE_FAN,
)
from ...addon_common.common import gpustate
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import Point, Point2D, Vec2D, Vec, Direction2D, intersection2d_line_line, closest2d_point_segment
from ...addon_common.common.globals import Globals
from ...addon_common.common.fsm import FSM
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString
from ...addon_common.common.decorators import timed_call
from ...addon_common.common.drawing import DrawCallbacks

from .knife_insert import Knife_Insert

from ...config.options import options, themes


class Knife(RFTool, Knife_Insert):
    name        = 'Knife'
    description = 'Cut complex topology into existing geometry on vertex-by-vertex basis'
    icon        = 'knife-icon.png'
    help        = 'knife.md'
    shortcut    = 'knife tool'
    quick_shortcut = 'knife quick'
    statusbar   = '{{insert}} Insert'
    ui_config   = 'knife_options.html'

    RFWidget_Default   = RFWidget_Default_Factory.create()
    RFWidget_Knife     = RFWidget_Default_Factory.create(cursor='KNIFE')
    RFWidget_Move      = RFWidget_Default_Factory.create(cursor='HAND')
    RFWidget_Hidden    = RFWidget_Hidden_Factory.create()

    @RFTool.on_init
    def init(self):
        self.rfwidgets = {
            'default': self.RFWidget_Default(self),
            'knife':   self.RFWidget_Knife(self),
            'hover':   self.RFWidget_Move(self),
            'hidden':  self.RFWidget_Hidden(self),
        }
        self.rfwidget = None
        self.knife_start = None
        self.update_hovered()

    def _fsm_in_main(self):
        # needed so main actions using Ctrl (ex: undo, redo, save) can still work
        return self._fsm.state in {'main', 'insert'}

    @RFTool.on_reset
    def reset(self):
        self.quickswitch = False

    @RFTool.on_events('reset', 'target change', 'view change', 'mouse move')
    @RFTool.once_per_frame
    @FSM.onlyinstate('main')
    def update_hovered(self):
        self.hovering_sel_geom = self.rfcontext.accel_nearest2D_geom(max_dist=options['action dist'], selected_only=True)

    @FSM.on_state('main', 'enter')
    def main_enter(self):
        self.update_hovered()

    @FSM.on_state('main')
    def main(self):
        if self.hovering_sel_geom and not self.hovering_sel_geom.is_valid: self.hoving_sel_geom = None

        if self.actions.using_onlymods('insert'):
            return 'insert'

        if self.hovering_sel_geom:
            self.set_widget('hover')
        else:
            self.set_widget('default')

        if self.handle_inactive_passthrough(): return

        if self.hovering_sel_geom and self.actions.pressed('action'):
            self.rfcontext.undo_push('grab')
            self.prep_move(
                action_confirm=(lambda: self.actions.released('action', ignoremods=True)),
            )
            return 'move after select'

        if self.actions.pressed({'select path add'}):
            return self.rfcontext.select_path(
                {'edge'},
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
            sel = self.rfcontext.accel_nearest2D_geom(max_dist=options['select dist'])
            if not sel_only and not sel: return
            self.rfcontext.undo_push('select')
            if sel_only: self.rfcontext.deselect_all()
            if not sel: return
            if sel.select: self.rfcontext.deselect(sel, subparts=False)
            else:          self.rfcontext.select(sel, supparts=False, only=sel_only)
            return

        if self.rfcontext.actions.pressed('knife reset'):
            self.knife_start = None
            self.rfcontext.deselect_all()
            return

        if self.actions.pressed('grab'):
            self.rfcontext.undo_push('move grabbed')
            self.prep_move()
            return 'move'


    @FSM.on_state('move after select')
    @RFTool.dirty_when_done
    def modal_move_after_select(self):
        if self.actions.released('action'):
            return 'main'

        if (self.actions.mouse - self.mousedown).length >= self.rfcontext.drawing.scale(options['move dist']):
            self.rfcontext.undo_push('move after select')
            return 'move'

    def prep_move(self, *, bmverts=None, bmverts_xys=None, action_confirm=None, action_cancel=None):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        if bmverts_xys is not None:
            self.bmverts_xys = bmverts_xys
            self.bmverts = [bmv for (bmv, _) in self.bmverts_xys]
        else:
            self.bmverts = bmverts if bmverts is not None else self.rfcontext.get_selected_verts()
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
        self.state_after_move = self._fsm.state

    @FSM.on_state('move', 'enter')
    def move_enter(self):
        self.move_opts = {
            'vis_accel': self.rfcontext.get_custom_vis_accel(selection_only=False, include_edges=False, include_faces=False, symmetry=False),
        }

        if options['hide cursor on tweak']: self.set_widget('hidden')

        # filter out any deleted bmverts (issue #1075) or bmverts that are not on screen
        self.bmverts_xys = [(bmv, xy) for (bmv, xy) in self.bmverts_xys if bmv and bmv.is_valid and xy]
        self.bmverts = [bmv for (bmv, _) in self.bmverts_xys]
        self.last_delta = None
        self.rfcontext.split_target_visualization_selected()
        self.rfcontext.set_accel_defer(True)
        self.rfcontext.fast_update_timer.enable(True)

    @FSM.on_state('move')
    def modal_move(self):
        if self.move_actions['confirm']():
            self.rfcontext.merge_verts_by_dist(self.bmverts, options['knife merge dist'])
            return self.state_after_move

        if self.move_actions['cancel']():
            self.rfcontext.undo_cancel()
            return self.state_after_move

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
            if options['knife automerge']:
                bmv1,d = self.rfcontext.accel_nearest2D_vert(point=xy_updated, vis_accel=self.move_opts['vis_accel'], max_dist=options['knife merge dist'])
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

        self.rfcontext.update_verts_faces(self.bmverts)
        self.rfcontext.dirty()
        tag_redraw_all('knife mouse move')

    @FSM.on_state('move', 'exit')
    def move_exit(self):
        self.rfcontext.fast_update_timer.enable(False)
        self.rfcontext.set_accel_defer(False)
        self.rfcontext.clear_split_target_visualization()


    # def _get_edge_quad_verts(self):
    #     '''
    #     this function is used in quad-only mode to find positions of quad verts based on selected edge and mouse position
    #     a Desmos construction of how this works: https://www.desmos.com/geometry/5w40xowuig
    #     '''
    #     e0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
    #     if not e0: return (None, None, None, None)
    #     bmv0,bmv1 = e0.verts
    #     xy0 = self.rfcontext.Point_to_Point2D(bmv0.co)
    #     xy1 = self.rfcontext.Point_to_Point2D(bmv1.co)
    #     d01 = (xy0 - xy1).length
    #     mid01 = xy0 + (xy1 - xy0) / 2
    #     mid23 = self.actions.mouse
    #     mid0123 = mid01 + (mid23 - mid01) / 2
    #     between = mid23 - mid01
    #     if between.length < 0.0001: return (None, None, None, None)
    #     perp = Direction2D((-between.y, between.x))
    #     if perp.dot(xy1 - xy0) < 0: perp.reverse()
    #     #pts = intersect_line_line(xy0, xy1, mid0123, mid0123 + perp)
    #     #if not pts: return (None, None, None, None)
    #     #intersection = pts[1]
    #     intersection = intersection2d_line_line(xy0, xy1, mid0123, mid0123 + perp)
    #     if not intersection: return (None, None, None, None)
    #     intersection = Point2D(intersection)

    #     toward = Direction2D(mid23 - intersection)
    #     if toward.dot(perp) < 0: d01 = -d01

    #     # push intersection out just a bit to make it more stable (prevent crossing) when |between| < d01
    #     between_len = between.length * Direction2D(xy1 - xy0).dot(perp)

    #     for tries in range(32):
    #         v = toward * (d01 / 2)
    #         xy2, xy3 = mid23 + v, mid23 - v

    #         # try to prevent quad from crossing
    #         v03 = xy3 - xy0
    #         if v03.dot(between) < 0 or v03.length < between_len:
    #             xy3 = xy0 + Direction2D(v03) * (between_len * (-1 if v03.dot(between) < 0 else 1))
    #         v12 = xy2 - xy1
    #         if v12.dot(between) < 0 or v12.length < between_len:
    #             xy2 = xy1 + Direction2D(v12) * (between_len * (-1 if v12.dot(between) < 0 else 1))

    #         if self.rfcontext.raycast_sources_Point2D(xy2)[0] and self.rfcontext.raycast_sources_Point2D(xy3)[0]: break
    #         d01 /= 2
    #     else:
    #         return (None, None, None, None)

    #     nearest_vert,_ = self.rfcontext.nearest2D_vert(point=xy2, verts=self.vis_verts, max_dist=options['knife merge dist'])
    #     if nearest_vert: xy2 = self.rfcontext.Point_to_Point2D(nearest_vert.co)
    #     nearest_vert,_ = self.rfcontext.nearest2D_vert(point=xy3, verts=self.vis_verts, max_dist=options['knife merge dist'])
    #     if nearest_vert: xy3 = self.rfcontext.Point_to_Point2D(nearest_vert.co)

    #     return (xy0, xy1, xy2, xy3)
