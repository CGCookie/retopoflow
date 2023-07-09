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
import random

import bpy
import gpu

from mathutils import Matrix, Vector
from mathutils.geometry import intersect_point_tri_2d, intersect_point_tri_2d

from ..rftool import RFTool
from ...addon_common.common.decorators import timed_call
from ...addon_common.common import gpustate


################################################################################################
# following imports must happen *after* the above class, because each subclass depends on
# above class to be defined

from .polystrips_ops   import PolyStrips_Ops
from .polystrips_props import PolyStrips_Props
from .polystrips_utils import (
    RFTool_PolyStrips_Strip,
    hash_face_pair,
    crawl_strip,
    is_boundaryvert, is_boundaryedge,
    process_stroke_filter, process_stroke_source,
    process_stroke_get_next, process_stroke_get_marks,
    mark_info,
)

from ...addon_common.common.bezier import CubicBezierSpline, CubicBezier
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.debug import dprint
from ...addon_common.common.drawing import Drawing, Cursors, DrawCallbacks
from ...addon_common.common.fsm import FSM
from ...addon_common.common.maths import Vec2D, Point, rotate2D, Direction2D, Point2D, RelPoint2D
from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import iter_pairs

from ...config.options import options, themes

from ..rfwidgets.rfwidget_brushstroke import RFWidget_BrushStroke_Factory
from ..rfwidgets.rfwidget_default     import RFWidget_Default_Factory
from ..rfwidgets.rfwidget_hidden      import RFWidget_Hidden_Factory

from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString


class PolyStrips(RFTool, PolyStrips_Props, PolyStrips_Ops):
    name        = 'PolyStrips'
    description = 'Create and edit strips of quads'
    icon        = 'polystrips-icon.png'
    help        = 'polystrips.md'
    shortcut    = 'polystrips tool'
    statusbar   = '{{insert}} Insert strip of quads\t{{brush radius}} Brush size\t{{action}} Grab selection\t{{increase count}} Increase segments\t{{decrease count}} Decrease segments'
    ui_config   = 'polystrips_options.html'

    RFWidget_Default     = RFWidget_Default_Factory.create()
    RFWidget_Move        = RFWidget_Default_Factory.create(cursor='HAND')
    RFWidget_Hidden      = RFWidget_Hidden_Factory.create()
    RFWidget_BrushStroke = RFWidget_BrushStroke_Factory.create(
        'PolyStrips stroke',
        BoundInt('''options['polystrips radius']''', min_value=1),
        outer_border_color=themes['polystrips']
    )

    @RFTool.on_init
    def init(self):
        self.rfwidgets = {
            'default':     self.RFWidget_Default(self),
            'brushstroke': self.RFWidget_BrushStroke(self),
            'move':        self.RFWidget_Move(self),
            'hidden':      self.RFWidget_Hidden(self),
        }
        self.rfwidget = None

    @RFTool.on_reset
    def reset(self):
        self.strips = []
        self.strip_pts = []
        self.hovering_strips = set()
        self.hovering_handles = []
        self.hovering_sel_face = None
        self.sel_cbpts = []
        self.stroke_cbs = CubicBezierSpline()
        self.clear_count_data()

    @RFTool.on_target_change
    @profiler.function
    def update_target(self, force=False):
        if not force and self._fsm.state in {'move handle', 'rotate', 'scale'}: return

        self.strips = []
        self._var_cut_count.disabled = True

        # get selected quads
        bmquads = set(bmf for bmf in self.rfcontext.get_selected_faces() if len(bmf.verts) == 4)
        if not bmquads: return

        # find junctions at corners
        junctions = set()
        for bmf in bmquads:
            # skip if in middle of a selection
            if not any(is_boundaryvert(bmv, bmquads) for bmv in bmf.verts): continue
            # skip if in middle of possible strip
            edge0,edge1,edge2,edge3 = [is_boundaryedge(bme, bmquads) for bme in bmf.edges]
            if (edge0 or edge2) and not (edge1 or edge3): continue
            if (edge1 or edge3) and not (edge0 or edge2): continue
            junctions.add(bmf)

        # find junctions that might be in middle of strip but are ends to other strips
        boundaries = set((bme,bmf) for bmf in bmquads for bme in bmf.edges if is_boundaryedge(bme, bmquads))
        while boundaries:
            bme,bmf = boundaries.pop()
            for bme_ in bmf.neighbor_edges(bme):
                strip = crawl_strip(bmf, bme_, bmquads, junctions)
                if strip is None: continue
                junctions.add(strip[-1])

        # find strips between junctions
        touched = set()
        for bmf0 in junctions:
            bme0,bme1,bme2,bme3 = bmf0.edges
            edge0,edge1,edge2,edge3 = [is_boundaryedge(bme, bmquads) for bme in bmf0.edges]

            def add_strip(bme):
                strip = crawl_strip(bmf0, bme, bmquads, junctions)
                if not strip:
                    return
                bmf1 = strip[-1]
                if len(strip) > 1 and hash_face_pair(bmf0, bmf1) not in touched:
                    touched.add(hash_face_pair(bmf0,bmf1))
                    touched.add(hash_face_pair(bmf1,bmf0))
                    self.strips.append(RFTool_PolyStrips_Strip(strip))

            if not edge0: add_strip(bme0)
            if not edge1: add_strip(bme1)
            if not edge2: add_strip(bme2)
            if not edge3: add_strip(bme3)
            if options['polystrips max strips'] and len(self.strips) > options['polystrips max strips']:
                self.strips = []
                break

        self.update_strip_viz()
        if len(self.strips) == 1:
            self._var_cut_count.set(len(self.strips[0]))
            self._var_cut_count.disabled = False

        if self.rfcontext.get_last_action() != 'change segment count':
            self.setup_change_count()

    @profiler.function
    def update_strip_viz(self):
        self.strip_pts = [[strip.curve.eval(i/10) for i in range(10+1)] for strip in self.strips]

    @RFTool.on_target_change
    @RFTool.on_view_change
    @FSM.onlyinstate('main')
    def update_next_state(self):
        self.vis_accel = self.rfcontext.get_vis_accel()


    @FSM.on_state('main')
    def main(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        mouse = self.actions.mouse

        if not self.actions.using('action', ignoredrag=True):
            # only update while not pressing action, because action includes drag, and
            # the artist might move mouse off selected edge before drag kicks in!
            self.hovering_sel_face,_ = self.rfcontext.accel_nearest2D_face(max_dist=options['action dist'], selected_only=True)

        self.hovering_handles.clear()
        self.hovering_strips.clear()
        for strip in self.strips:
            for i,cbpt in enumerate(strip.curve):
                v = Point_to_Point2D(cbpt)
                if v is None: continue
                if (mouse - v).length > self.drawing.scale(options['select dist']): continue
                # do not filter out non-visible handles, because otherwise
                # they might not be movable if they are inside the model
                self.hovering_handles.append(cbpt)
                self.hovering_strips.add(strip)

        if self.actions.using_onlymods('insert'):
            self.set_widget('brushstroke')
        elif self.hovering_handles:
            self.set_widget('move')
        elif self.hovering_sel_face:
            self.set_widget('move')
        else:
            self.set_widget('default')

        if self.handle_inactive_passthrough(): return 

        # handle edits
        if self.hovering_handles:
            if self.actions.pressed('action'):
                return 'move handle'
            if self.actions.pressed('action alt0'):
                return 'rotate'
            if self.actions.pressed('action alt1'):
                return 'scale'

        if self.hovering_sel_face:
            if self.actions.pressed('action', unpress=False):
                return 'move all'

        if self.actions.pressed('grab', unpress=False):
            return 'move all'

        if self.actions.pressed('increase count'):
            self.change_count(delta=1)
            return

        if self.actions.pressed('decrease count'):
            self.change_count(delta=-1)
            return

        if self.actions.pressed({'select path add'}):
            return self.rfcontext.select_path(
                {'face'},
                kwargs_select={'supparts': False},
            )

        if self.actions.pressed({'select paint', 'select paint add'}, unpress=False):
            sel_only = self.actions.pressed('select paint')
            return self.rfcontext.setup_smart_selection_painting(
                {'face'},
                use_select_tool=True,
                selecting=not sel_only,
                deselect_all=sel_only,
                # fn_filter_bmelem=self.filter_edge_selection,
                kwargs_select={'supparts': False},
                kwargs_deselect={'subparts': False},
            )

        if self.actions.pressed({'select single', 'select single add'}, unpress=False):
            # TODO: DO NOT PAINT!
            sel_only = self.actions.pressed('select single')
            return self.rfcontext.setup_smart_selection_painting(
                {'face'},
                use_select_tool=False,
                selecting=not sel_only,
                deselect_all=sel_only,
                # fn_filter_bmelem=self.filter_edge_selection,
                kwargs_select={'supparts': False},
                kwargs_deselect={'subparts': False},
            )


    @FSM.on_state('move handle', 'can enter')
    def movehandle_canenter(self):
        return len(self.hovering_handles) > 0

    @FSM.on_state('move handle', 'enter')
    def movehandle_enter(self):
        self.sel_cbpts = []
        self.mod_strips = set()

        cbpts = list(self.hovering_handles)
        self.mod_strips |= self.hovering_strips
        for strip in self.strips:
            p0,p1,p2,p3 = strip.curve.points()
            if p0 in cbpts and p1 not in cbpts:
                cbpts.append(p1)
                self.mod_strips.add(strip)
            if p3 in cbpts and p2 not in cbpts:
                cbpts.append(p2)
                self.mod_strips.add(strip)

        for strip in self.mod_strips: strip.capture_edges()
        inners = [ p for strip in self.strips for p in strip.curve.points()[1:3] ]

        self.sel_cbpts = [(cbpt, cbpt in inners, Point(cbpt), self.rfcontext.Point_to_Point2D(cbpt)) for cbpt in cbpts]
        self.mousedown = self.actions.mouse
        self.move_done_pressed = 'confirm'
        self.move_done_released = 'action'
        self.move_cancelled = 'cancel'
        self.rfcontext.undo_push('manipulate bezier')
        self.set_widget('hidden' if options['hide cursor on tweak'] else 'move')

        self._timer = self.actions.start_timer(120.0)
        self.rfcontext.split_target_visualization(verts=self.rfcontext.get_selected_verts())
        self.rfcontext.set_accel_defer(True)


    @FSM.on_state('move handle')
    def movehandle(self):
        if self.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.actions.released(self.move_done_released):
            return 'main'
        if self.actions.pressed(self.move_cancelled):
            self.rfcontext.undo_cancel()
            return 'main'

        if self.actions.mousemove or not self.actions.mousemove_prev: return

        delta = Vec2D(self.actions.mouse - self.mousedown)
        up,rt,fw = self.rfcontext.Vec_up(),self.rfcontext.Vec_right(),self.rfcontext.Vec_forward()
        for cbpt,inner,oco,oco2D in self.sel_cbpts:
            nco2D = oco2D + delta
            if not inner:
                xyz,_,_,_ = self.rfcontext.raycast_sources_Point2D(nco2D)
                if xyz: cbpt.xyz = xyz
            else:
                ov = self.rfcontext.Point2D_to_Vec(oco2D)
                nr = self.rfcontext.Point2D_to_Ray(nco2D)
                od = self.rfcontext.Point_to_depth(oco)
                cbpt.xyz = nr.eval(od / ov.dot(nr.d))

        for strip in self.hovering_strips:
            strip.update(self.rfcontext.nearest_sources_Point, self.rfcontext.raycast_sources_Point, self.rfcontext.update_face_normal)

        self.update_strip_viz()
        self.rfcontext.dirty()

    @FSM.on_state('move handle', 'exit')
    def movehandle_exit(self):
        self._timer.done()
        self.rfcontext.clear_split_target_visualization()
        self.rfcontext.set_accel_defer(False)
        self.update_target(force=True)
        tag_redraw_all('PolyStrips done moving handles')


    @FSM.on_state('rotate', 'can enter')
    def rotate_canenter(self):
        if not self.hovering_handles: return False

        self.sel_cbpts = []
        self.mod_strips = set()
        Point_to_Point2D = self.rfcontext.Point_to_Point2D

        # find hovered inner point, the corresponding outer point and its face
        innerP,outerP,outerF = None,None,None
        for strip in self.strips:
            bmf0,bmf1 = strip.end_faces()
            p0,p1,p2,p3 = strip.curve.points()
            if p1 in self.hovering_handles: innerP,outerP,outerF = p1,p0,bmf0
            if p2 in self.hovering_handles: innerP,outerP,outerF = p2,p3,bmf1
        if not innerP or not outerP or not outerF: return False

        # scan through all selected strips and collect all inner points next to outerP
        for strip in self.strips:
            bmf0,bmf3 = strip.end_faces()
            if outerF != bmf0 and outerF != bmf3: continue
            p0,p1,p2,p3 = strip.curve.points()
            if outerF == bmf0: self.sel_cbpts.append( (p1, Point(p1), Point_to_Point2D(p1)) )
            else:              self.sel_cbpts.append( (p2, Point(p2), Point_to_Point2D(p2)) )
            self.mod_strips.add(strip)
        self.rotate_about = Point_to_Point2D(outerP)
        if not self.rotate_about: return False

    @FSM.on_state('rotate', 'enter')
    def rotate_enter(self):
        for strip in self.mod_strips: strip.capture_edges()

        self.mousedown = self.actions.mouse
        self.move_done_pressed = 'confirm'
        self.move_done_released = 'action alt0'
        self.move_cancelled = 'cancel'
        self.rfcontext.undo_push('rotate')
        self._timer = self.actions.start_timer(120.0)
        self.rfcontext.set_accel_defer(True)
        self.set_widget('hidden' if options['hide cursor on tweak'] else 'move')

    @FSM.on_state('rotate')
    @profiler.function
    def rotate(self):
        if not self.rotate_about: return 'main'
        if self.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.actions.released(self.move_done_released):
            return 'main'
        if self.actions.pressed(self.move_cancelled):
            self.rfcontext.undo_cancel()
            return 'main'

        if self.actions.mousemove or not self.actions.mousemove_prev: return

        prev_diff = self.mousedown - self.rotate_about
        prev_rot = math.atan2(prev_diff.x, prev_diff.y)
        cur_diff = self.actions.mouse - self.rotate_about
        cur_rot = math.atan2(cur_diff.x, cur_diff.y)
        angle = prev_rot - cur_rot

        for cbpt,oco,oco2D in self.sel_cbpts:
            xy = rotate2D(oco2D, angle, origin=self.rotate_about)
            xyz,_,_,_ = self.rfcontext.raycast_sources_Point2D(xy)
            if xyz: cbpt.xyz = xyz

        for strip in self.mod_strips:
            strip.update(self.rfcontext.nearest_sources_Point, self.rfcontext.raycast_sources_Point, self.rfcontext.update_face_normal)

        self.update_strip_viz()
        self.rfcontext.dirty()

    @FSM.on_state('rotate', 'exit')
    def rotate_exit(self):
        self._timer.done()
        self.rfcontext.set_accel_defer(False)
        self.update_target(force=True)



    @FSM.on_state('scale', 'can enter')
    @profiler.function
    def scale_canenter(self):
        if not self.hovering_handles: return False

        self.mod_strips = set()

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        innerP,outerP,outerF = None,None,None
        for strip in self.strips:
            bmf0,bmf1 = strip.end_faces()
            p0,p1,p2,p3 = strip.curve.points()
            if p1 in self.hovering_handles: innerP,outerP,outerF = p1,p0,bmf0
            if p2 in self.hovering_handles: innerP,outerP,outerF = p2,p3,bmf1
        if not innerP or not outerP or not outerF: return False

        self.scale_strips = []
        for strip in self.strips:
            bmf0,bmf1 = strip.end_faces()
            if bmf0 == outerF:
                self.scale_strips.append((strip, 1))
                self.mod_strips.add(strip)
            if bmf1 == outerF:
                self.scale_strips.append((strip, 2))
                self.mod_strips.add(strip)

        for strip in self.mod_strips: strip.capture_edges()

        if not self.scale_strips: return False

        self.scale_from = Point_to_Point2D(outerP)

    @FSM.on_state('scale', 'enter')
    def scale_enter(self):
        self.mousedown = self.actions.mouse
        self.rfcontext.undo_push('scale')
        self.move_done_pressed = None
        self.move_done_released = 'action'
        self.move_cancelled = 'cancel'

        falloff = options['polystrips scale falloff']

        self.scale_bmf = {}
        self.scale_bmv = {}
        for strip,iinner in self.scale_strips:
            iend = 0 if iinner == 1 else 3
            s0,s1 = (1,0) if iend == 0 else (0,1)
            l = len(strip.bmf_strip)
            for ibmf,bmf in enumerate(strip.bmf_strip):
                if bmf in self.scale_bmf: continue
                p = ibmf/(l-1)
                s = (s0 + (s1-s0) * p) ** falloff
                self.scale_bmf[bmf] = s
        for bmf in self.scale_bmf.keys():
            c = bmf.center()
            s = self.scale_bmf[bmf]
            for bmv in bmf.verts:
                if bmv not in self.scale_bmv:
                    self.scale_bmv[bmv] = []
                self.scale_bmv[bmv] += [(c, bmv.co-c, s)]

        self._timer = self.actions.start_timer(120.0)
        self.rfcontext.set_accel_defer(True)

        self.set_widget('hidden' if options['hide cursor on tweak'] else 'default') # None

    @FSM.on_state('scale')
    @profiler.function
    def scale(self):
        if self.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.actions.released(self.move_done_released, ignoremods=True):
            return 'main'
        if self.actions.pressed(self.move_cancelled):
            self.rfcontext.undo_cancel()
            return 'main'

        if self.actions.mousemove or not self.actions.mousemove_prev: return

        vec0 = self.mousedown - self.scale_from
        vec1 = self.actions.mouse - self.scale_from
        scale = vec1.length / vec0.length

        snap2D_vert = self.rfcontext.snap2D_vert
        snap_vert = self.rfcontext.snap_vert
        for bmv in self.scale_bmv.keys():
            l = self.scale_bmv[bmv]
            n = Vector()
            for c,v,sc in l:
                n += c + v * max(0, 1 + (scale-1) * sc)
            bmv.co = n / len(l)
            snap_vert(bmv)

        self.rfcontext.dirty()

    @FSM.on_state('scale', 'exit')
    def scale_exit(self):
        self._timer.done()
        self.rfcontext.set_accel_defer(False)
        self.update_target(force=True)


    @FSM.on_state('move all', 'can enter')
    @profiler.function
    def moveall_canenter(self):
        bmfaces = self.rfcontext.get_selected_faces()
        if not bmfaces: return False
        bmverts = set(bmv for bmf in bmfaces for bmv in bmf.verts)
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]

    @FSM.on_state('move all', 'enter')
    def moveall_enter(self):
        lmb_drag = self.actions.using('action')
        self.actions.unpress()
        self.rfcontext.undo_push('move grabbed')
        self.moveall_opts = {
            'mousedown': self.actions.mouse,
            'move_done_pressed': None if lmb_drag else 'confirm',
            'move_done_released': 'action' if lmb_drag else None,
            'move_cancelled': 'cancel',
            'timer': self.actions.start_timer(120.0),
        }
        self.rfcontext.split_target_visualization_selected()
        self.rfcontext.set_accel_defer(True)
        self.set_widget('hidden' if options['hide cursor on tweak'] else 'default')  # None

    @FSM.on_state('move all')
    @profiler.function
    def moveall(self):
        opts = self.moveall_opts

        if self.actions.pressed(opts['move_done_pressed']):
            return 'main'
        if self.actions.released(opts['move_done_released']):
            return 'main'
        if self.actions.pressed(opts['move_cancelled']):
            self.rfcontext.undo_cancel()
            return 'main'

        if self.actions.mousemove or not self.actions.mousemove_prev: return

        delta = Vec2D(self.actions.mouse - opts['mousedown'])
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            if not bmv.is_valid: continue
            set2D_vert(bmv, xy + delta)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)
        self.rfcontext.dirty()
        #self.update()

    @FSM.on_state('move all', 'exit')
    def moveall_exit(self):
        self.moveall_opts['timer'].done()
        self.rfcontext.set_accel_defer(False)
        self.rfcontext.clear_split_target_visualization()
        self.update_target(force=True)



    @DrawCallbacks.on_draw('post3d')
    def draw_post3d_spline(self):
        if not self.strips: return

        strips = self.strips
        hov_strips = self.hovering_strips

        Point_to_Point2D = self.rfcontext.Point_to_Point2D

        def is_visible(v):
            return True   # self.rfcontext.is_visible(v, None)

        def draw(alphamult, hov_alphamult, hover):
            nonlocal strips

            if not hover: hov_alphamult = alphamult

            size_outer = options['polystrips handle outer size']
            size_inner = options['polystrips handle inner size']
            border_outer = options['polystrips handle border']
            border_inner = options['polystrips handle border']

            gpustate.blend('ALPHA')

            # draw outer-inner lines
            pts = [Point_to_Point2D(p) for strip in strips for p in strip.curve.points()]
            self.rfcontext.drawing.draw2D_lines(pts, (1,1,1,0.45), width=2)

            # draw junction handles (outer control points of curve)
            faces_drawn = set() # keep track of faces, so don't draw same handles 2+ times
            pts_outer,pts_inner = [],[]
            for strip in strips:
                bmf0,bmf1 = strip.end_faces()
                p0,p1,p2,p3 = strip.curve.points()
                if bmf0 not in faces_drawn:
                    if is_visible(p0): pts_outer += [Point_to_Point2D(p0)]
                    faces_drawn.add(bmf0)
                if bmf1 not in faces_drawn:
                    if is_visible(p3): pts_outer += [Point_to_Point2D(p3)]
                    faces_drawn.add(bmf1)
                if is_visible(p1): pts_inner += [Point_to_Point2D(p1)]
                if is_visible(p2): pts_inner += [Point_to_Point2D(p2)]
            pts_outer = [p for p in pts_outer if p]
            pts_inner = [p for p in pts_inner if p]
            self.rfcontext.drawing.draw2D_points(pts_outer, (1.00,1.00,1.00,1.0), radius=size_outer, border=border_outer, borderColor=(0.00,0.00,0.00,0.5))
            self.rfcontext.drawing.draw2D_points(pts_inner, (0.25,0.25,0.25,0.8), radius=size_inner, border=border_inner, borderColor=(0.75,0.75,0.75,0.4))

        gpustate.blend('ALPHA')
        gpustate.depth_test('NONE')
        gpustate.depth_mask(False)
        draw(1.0, 1.0, False)
        gpustate.depth_mask(True)
        gpustate.depth_test('LESS_EQUAL')

    @DrawCallbacks.on_draw('post2d')
    def draw_post2d(self):
        self.rfcontext.drawing.set_font_size(12)
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        text_draw2D = self.rfcontext.drawing.text_draw2D

        for strip in self.strips:
            strip = [f for f in strip if f.is_valid]
            c = len(strip)
            vs = [Point_to_Point2D(f.center()) for f in strip]
            vs = [Vec2D(v) for v in vs if v]
            if not vs: continue
            ctr = sum(vs, Vec2D((0,0))) / len(vs)
            text_draw2D('%d' % c, ctr+Vec2D((2,14)), color=(1,1,0,1), dropshadow=(0,0,0,0.5))
