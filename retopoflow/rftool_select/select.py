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

import math
import time
from ..rftool import RFTool
from ..rfwidget import RFWidget
from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory
from ..rfwidgets.rfwidget_selectbox import RFWidget_SelectBox_Factory
from ..rfwidgets.rfwidget_hidden  import RFWidget_Hidden_Factory

from ...addon_common.common.maths import (
    Vec, Vec2D,
    Point, Point2D,
    Direction,
    Accel2D,
    Color,
    closest_point_segment,
)
from ...addon_common.common.fsm import FSM
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString
from ...addon_common.common.maths import segment2D_intersection, Point2D, triangle2D_overlap
from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import iter_pairs, delay_exec, Dict
from ...config.options import options, themes


class Select(RFTool):
    name        = 'Select'
    description = 'Select geometry'
    icon        = 'select-icon.png'
    help        = 'select.md'
    shortcut    = 'select tool'
    quick_shortcut = 'select quick'
    statusbar   = '{{select box}} Select\t{{select box del}}: Remove selection\t{{select box add}}: Add selection'
    ui_config   = 'select_options.html'

    RFWidget_Default   = RFWidget_Default_Factory.create()
    RFWidget_SelectBox = RFWidget_SelectBox_Factory.create('Select: Box')
    RFWidget_Hidden    = RFWidget_Hidden_Factory.create()

    @RFTool.on_init
    def init(self):
        self.rfwidgets = {
            'default':   self.RFWidget_Default(self),
            'selectbox': self.RFWidget_SelectBox(self),
            # circle select????
            'hidden':    self.RFWidget_Hidden(self),
        }
        self.rfwidget = None

    @RFTool.on_quickselect_start
    def quickselect_start(self):
        self.rfwidgets['selectbox'].quickselect_start()

    @FSM.on_state('main')
    def main(self):
        self.set_widget('selectbox')

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
            return 'move'


    def select_linked(self):
        self.rfcontext.undo_push('select linked')
        self.rfcontext.select_linked()

    def deselect_all(self):
        self.rfcontext.undo_push('deselect all')
        self.rfcontext.deselect_all()

    def select_invert(self):
        self.rfcontext.undo_push('invert selection')
        self.rfcontext.select_invert()

    @RFWidget.on_action('Select: Box')
    def selectbox(self):
        box = self.rfwidgets['selectbox']
        p0, p1 = box.box2D
        if not p0 or not p1: return

        (x0, y0), (x1, y1) = p0, p1
        left, right = min(x0, x1), max(x0, x1)
        bottom, top = min(y0, y1), max(y0, y1)
        c0, c1, c2, c3 = Point2D((left, top)), Point2D((left, bottom)), Point2D((right, bottom)), Point2D((right, top))
        tri0, tri1 = (c0, c1, c2), (c0, c2, c3)
        get_point2D = self.rfcontext.get_point2D

        def vert_inside(vert):
            p = get_point2D(vert.co)
            return left <= p.x <= right and bottom <= p.y <= top

        def edge_inside(edge):
            v0, v1 = edge.verts
            if vert_inside(v0) or vert_inside(v1): return True
            p0, p1 = get_point2D(v0.co), get_point2D(v1.co)
            return any((
                segment2D_intersection(c0, c1, p0, p1),
                segment2D_intersection(c1, c2, p0, p1),
                segment2D_intersection(c1, c3, p0, p1),
                segment2D_intersection(c3, c0, p0, p1),
            ))

        def face_inside(face):
            points = [get_point2D(v.co) for v in face.verts]
            p0 = points[0]
            return any((
                triangle2D_overlap((p0, p1, p2), tri0) or triangle2D_overlap((p0, p1, p2), tri1)
                for p1, p2 in zip(points[1:-1], points[2:])
            ))

        match options['select geometry']:
            case 'Verts':
                verts = {
                    vert
                    for vert in self.rfcontext.get_vis_verts()
                    if vert_inside(vert)
                }
            case 'Edges':
                verts = {
                    vert
                    for edge in self.rfcontext.get_vis_edges()
                    if edge_inside(edge)
                    for vert in edge.verts
                }
            case 'Faces':
                verts = {
                    vert
                    for face in self.rfcontext.get_vis_faces()
                    if face_inside(face)
                    for vert in face.verts
                }

        self.rfcontext.undo_push('select box')
        if   box.mods['ctrl']:  self.rfcontext.select(self.rfcontext.get_selected_verts() - verts, only=True)   # del verts from selection
        elif box.mods['shift']: self.rfcontext.select(verts, only=False)                                        # add vert to selection
        else:                   self.rfcontext.select(verts, only=True)                                         # replace selection


    @FSM.on_state('move', 'enter')
    def move_enter(self):
        self.move_data = Dict(
            bmverts=[ (bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in self.rfcontext.get_selected_verts() ],
            mousedown=self.actions.mouse,
            last_delta=None,
        )
        if options['select automerge']:
            self.move_data.vis_accel = self.rfcontext.get_custom_vis_accel(
                selection_only=False,
                include_edges=False,
                include_faces=False,
                symmetry=False,
            )
        self.rfcontext.split_target_visualization_selected()
        self.rfcontext.fast_update_timer.start()
        self.rfcontext.set_accel_defer(True)

        if options['hide cursor on tweak']: self.set_widget('hidden')

    @FSM.on_state('move')
    def modal_move(self):
        if self.actions.pressed(['confirm', 'confirm drag']):
            self.mergeSnapped()
            return 'main'
        if self.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        if not self.actions.mousemove_stop: return
        # # only update verts on timer events and when mouse has moved
        # if not self.actions.timer: return
        # if self.actions.mouse_prev == self.actions.mouse: return

        delta = Vec2D(self.actions.mouse - self.move_data.mousedown)
        if delta == self.move_data.last_delta: return
        self.move_data.last_delta = delta
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.move_data.bmverts:
            if not xy: continue
            xy_updated = xy + delta
            if options['select automerge']:
                # snap xy_updated to any visible verts close enough to current xy_updated (in image plane)
                bmv1, _ = self.rfcontext.accel_nearest2D_vert(point=xy_updated, vis_accel=self.move_data.vis_accel, max_dist=options['select merge dist'])
                xy1 = self.rfcontext.Point_to_Point2D(bmv1.co) if bmv1 else None
                if xy1: xy_updated = xy1
            set2D_vert(bmv, xy_updated)
        self.rfcontext.update_verts_faces(v for v,_ in self.move_data.bmverts)
        self.rfcontext.dirty()

    @FSM.on_state('move', 'exit')
    def move_exit(self):
        self.rfcontext.set_accel_defer(False)
        self.rfcontext.fast_update_timer.stop()
        self.rfcontext.clear_split_target_visualization()

    def mergeSnapped(self):
        """ Merging colocated visible verts """

        if not options['select automerge']: return

        vis_verts = self.rfcontext.get_vis_verts()
        sel_verts = self.rfcontext.get_selected_verts()
        vis_bmverts = [
            (bmv, self.rfcontext.Point_to_Point2D(bmv.co))
            for bmv in vis_verts
            if bmv.is_valid and bmv not in sel_verts
        ]

        # TODO: remove colocated faces
        if self.move_data.mousedown is None: return
        delta = Vec2D(self.actions.mouse - self.move_data.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        update_verts = []
        merge_dist = self.rfcontext.drawing.scale(options['select merge dist'])
        for bmv,xy in self.move_data.bmverts:
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
