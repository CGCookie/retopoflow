'''
Copyright (C) 2017 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

import bgl
import bpy
import math
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_point_tri_2d
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec,clamp,Accel2D,Direction
from ..common.bezier import CubicBezierSpline, CubicBezier
from ..common.ui import UI_Image, UI_IntValue, UI_BoolValue
from ..lib.common_utilities import showErrorMessage, dprint
from ..lib.classes.logging.logger import Logger
from ..lib.classes.profiler.profiler import profiler
from ..common.shaders import circleShader, edgeShortenShader, arrowShader
from ..options import options, help_polystrips
from .rfcontext_actions import Actions

from .rftool_polystrips_ops import RFTool_PolyStrips_Ops
from .rftool_polystrips_utils import (
    RFTool_PolyStrips_Strip,
    hash_face_pair,
    strip_details,
    crawl_strip,
    is_boundaryvert,
    is_boundaryedge,
    )


@RFTool.action_call('polystrips tool')
class RFTool_PolyStrips(RFTool, RFTool_PolyStrips_Ops):
    def init(self):
        self.FSM['handle'] = self.modal_handle
        self.FSM['move']   = self.modal_move
        self.FSM['rotate'] = self.modal_rotate
        self.FSM['scale']  = self.modal_scale
    
    def name(self): return "PolyStrips"
    def icon(self): return "rf_polystrips_icon"
    def description(self): return 'Strips of quads made easy'
    def helptext(self): return help_polystrips
    def get_tooltip(self): return 'PolyStrips (%s)' % ','.join(Actions.default_keymap['polystrips tool'])
    
    def start(self):
        self.mode = 'main'
        self.rfwidget.set_widget('brush stroke', color=(1.0, 0.5, 0.5))
        self.rfwidget.set_stroke_callback(self.stroke)
        self.hovering_handles = []
        self.hovering_strips = set()
        self.sel_cbpts = []
        self.strokes = []
        self.stroke_cbs = CubicBezierSpline()
        
        self.vis_verts = None
        self.vis_edges = None
        self.vis_faces = None
        self.vis_accel = None
        self.target_version = None
        self.view_version = None
        self.recompute = True
        self.defer_recomputing = False
        
        self.update()
    
    def get_ui_icon(self):
        self.ui_icon = UI_Image('polystrips_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    def get_scale_falloff(self): return options['polystrips scale falloff']
    def set_scale_falloff(self, v): options['polystrips scale falloff'] = clamp(v, -10, 10)
    def get_scale_falloff_actual(self): return 2 ** (options['polystrips scale falloff'] * 0.1)
    def get_scale_falloff_print(self): return '%0.2f' % self.get_scale_falloff_actual()
    def set_scale_falloff_print(self, v): options['polystrips scale falloff'] = 10 * math.log(v) / math.log(2)
    def get_ui_options(self):
        def get_draw_curve(): return options['polystrips draw curve']
        def set_draw_curve(v): options['polystrips draw curve'] = v
        def get_max_strips(): return options['polystrips max strips']
        def set_max_strips(v):
            v = max(0, min(100, v))
            if v == options['polystrips max strips']: return
            options['polystrips max strips'] = v
            self.update()
        return [
            UI_IntValue('Scale Falloff', self.get_scale_falloff, self.set_scale_falloff, fn_get_print_value=self.get_scale_falloff_print, fn_set_print_value=self.set_scale_falloff_print),
            UI_IntValue('Max Strips', get_max_strips, set_max_strips),
            UI_BoolValue('Draw Curve', get_draw_curve, set_draw_curve),
        ]
    
    @profiler.profile
    def update(self):
        self.strips = []
        
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
    
    @profiler.profile
    def update_strip_viz(self):
        self.strip_pts = [[strip.curve.eval(i/10) for i in range(10+1)] for strip in self.strips]
    
    @profiler.profile
    def update_accel_struct(self):
        target_version = self.rfcontext.get_target_version(selection=False)
        view_version = self.rfcontext.get_view_version()
        
        recompute = self.recompute
        recompute |= self.target_version != target_version
        recompute |= self.view_version != view_version
        recompute |= self.vis_verts is None
        recompute |= self.vis_edges is None
        recompute |= self.vis_faces is None
        recompute |= self.vis_accel is None
        
        self.recompute = False
        
        if recompute and not self.defer_recomputing:
            self.target_version = target_version
            self.view_version = view_version
            
            self.vis_verts = self.rfcontext.visible_verts()
            self.vis_edges = self.rfcontext.visible_edges(verts=self.vis_verts)
            self.vis_faces = self.rfcontext.visible_faces(verts=self.vis_verts)
            self.vis_accel = Accel2D(self.vis_verts, self.vis_edges, self.vis_faces, self.rfcontext.get_point2D)
    
    @profiler.profile
    def modal_main(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        mouse = self.rfcontext.actions.mouse
        
        self.update_accel_struct()
        
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
        
        if self.rfcontext.actions.ctrl and not self.rfcontext.actions.shift:
            self.rfwidget.set_widget('brush stroke')
        else:
            self.rfwidget.set_widget('move' if self.hovering_handles else 'brush stroke')
        
        # handle edits
        if self.rfcontext.actions.pressed('action'):
            return self.prep_handle()
        if self.rfcontext.actions.pressed('action alt0'):
            return self.prep_rotate()
        if self.rfcontext.actions.pressed('action alt1'):
            return self.prep_scale()
        
        if self.rfcontext.actions.using('select'):
            self.defer_recomputing = True
            if self.rfcontext.actions.pressed('select'):
                self.rfcontext.undo_push('select')
                self.rfcontext.deselect_all()
            pr = profiler.start('finding nearest')
            xy = self.rfcontext.get_point2D(self.rfcontext.actions.mouse)
            bmf = self.vis_accel.nearest_face(xy)
            pr.done()
            if bmf and not bmf.select:
                self.rfcontext.select(bmf, supparts=False, only=False)
            return
        
        if self.rfcontext.actions.using('select add'):
            self.defer_recomputing = True
            if self.rfcontext.actions.pressed('select add'):
                self.rfcontext.undo_push('select add')
            if not self.vis_faces:
                self.vis_faces = self.rfcontext.visible_faces()
            pr = profiler.start('finding nearest')
            xy = self.rfcontext.get_point2D(self.rfcontext.actions.mouse)
            bmf = self.vis_accel.nearest_face(xy)
            pr.done()
            if bmf and not bmf.select:
                self.rfcontext.select(bmf, supparts=False, only=False)
            return
        
        self.defer_recomputing = False
        
        if self.rfcontext.actions.pressed('grab'):
            return self.prep_move()
        
        if self.rfcontext.actions.pressed('delete'):
            self.rfcontext.undo_push('delete')
            faces = self.rfcontext.get_selected_faces()
            self.rfcontext.delete_faces(faces)
            self.rfcontext.deselect_all()
            self.rfcontext.dirty()
            self.update()
            return
        
        if self.rfcontext.actions.pressed('increase count'):
            self.rfcontext.undo_push('change segment count', repeatable=True)
            self.change_count(1)
            return
        
        if self.rfcontext.actions.pressed('decrease count'):
            self.rfcontext.undo_push('change segment count', repeatable=True)
            self.change_count(-1)
            return
    
    @profiler.profile
    def prep_rotate(self):
        self.sel_cbpts = []
        self.mod_strips = set()
        
        if not self.hovering_handles: return
        
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        innerP,outerP,outerF = None,None,None
        for strip in self.strips:
            bmf0,bmf1 = strip.end_faces()
            p0,p1,p2,p3 = strip.curve.points()
            if p1 in self.hovering_handles: innerP,outerP,outerF = p1,p0,bmf0
            if p2 in self.hovering_handles: innerP,outerP,outerF = p2,p3,bmf1
        if not innerP or not outerP or not outerF: return ''
        # find all strips that share outerF
        for strip in self.strips:
            bmf0,bmf1 = strip.end_faces()
            if outerF != bmf0 and outerF != bmf1: continue
            p0,p1,p2,p3 = strip.curve.points()
            if outerF == bmf0:
                self.sel_cbpts += [(p1, False, Point(p1), Point_to_Point2D(p1))]
                self.mod_strips.add(strip)
            if outerF == bmf1:
                self.sel_cbpts += [(p2, False, Point(p2), Point_to_Point2D(p2))]
                self.mod_strips.add(strip)
        self.rotate_about = Point_to_Point2D(outerP)
        if not self.rotate_about: return ''
        
        for strip in self.mod_strips: strip.capture_edges()
        
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('move')
        self.move_done_pressed = 'confirm'
        self.move_done_released = 'action alt0'
        self.move_cancelled = 'cancel'
        self.rfcontext.undo_push('rotate')
        return 'rotate'
    
    @RFTool.dirty_when_done
    @profiler.profile
    def modal_rotate(self):
        if self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.rfcontext.actions.pressed(self.move_cancelled):
            self.rfcontext.undo_cancel()
            return 'main'
        
        prev_diff = self.mousedown - self.rotate_about
        prev_rot = math.atan2(prev_diff.x, prev_diff.y)
        cur_diff = self.rfcontext.actions.mouse - self.rotate_about
        cur_rot = math.atan2(cur_diff.x, cur_diff.y)
        angle = prev_rot - cur_rot
        
        rot = Matrix.Rotation(angle, 2)
        
        for cbpt,inner,oco,oco2D in self.sel_cbpts:
            xy = rot * (oco2D - self.rotate_about) + self.rotate_about
            xyz,_,_,_ = self.rfcontext.raycast_sources_Point2D(xy)
            if xyz: cbpt.xyz = xyz
        
        for strip in self.mod_strips:
            strip.update(self.rfcontext.nearest_sources_Point, self.rfcontext.raycast_sources_Point, self.rfcontext.update_face_normal)
        
        self.update_strip_viz()
    
    @profiler.profile
    def prep_handle(self):
        self.sel_cbpts = []
        self.mod_strips = set()
        
        if not self.hovering_handles: return
        
        
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
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('move')
        self.move_done_pressed = 'confirm'
        self.move_done_released = 'action'
        self.move_cancelled = 'cancel'
        self.rfcontext.undo_push('manipulate bezier')
        
        return 'handle'
    
    @RFTool.dirty_when_done
    @profiler.profile
    def modal_handle(self):
        if self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.rfcontext.actions.pressed(self.move_cancelled):
            self.rfcontext.undo_cancel()
            return 'main'
        
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
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
    
    @profiler.profile
    def prep_move(self, bmfaces=None):
        if not bmfaces: bmfaces = self.rfcontext.get_selected_faces()
        bmverts = set(bmv for bmf in bmfaces for bmv in bmf.verts)
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('default')
        self.rfcontext.undo_push('move grabbed')
        self.move_done_pressed = 'confirm'
        self.move_done_released = None
        self.move_cancelled = 'cancel'
        return 'move'
    
    @RFTool.dirty_when_done
    @profiler.profile
    def modal_move(self):
        if self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.rfcontext.actions.pressed(self.move_cancelled):
            self.rfcontext.undo_cancel()
            return 'main'

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            set2D_vert(bmv, xy + delta)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)
        self.update()
    
    @profiler.profile
    def prep_scale(self):
        self.mod_strips = set()
        
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        innerP,outerP,outerF = None,None,None
        for strip in self.strips:
            bmf0,bmf1 = strip.end_faces()
            p0,p1,p2,p3 = strip.curve.points()
            if p1 in self.hovering_handles: innerP,outerP,outerF = p1,p0,bmf0
            if p2 in self.hovering_handles: innerP,outerP,outerF = p2,p3,bmf1
        if not innerP or not outerP or not outerF: return ''
        
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
        
        if not self.scale_strips: return
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('default')
        self.rfcontext.undo_push('scale')
        self.move_done_pressed = None
        self.move_done_released = {'insert', 'insert alt0', 'insert alt1'}
        self.move_cancelled = 'cancel'
        
        falloff = self.get_scale_falloff_actual()
        
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
        return 'scale'
    
    @RFTool.dirty_when_done
    @profiler.profile
    def modal_scale(self):
        if self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.rfcontext.actions.pressed(self.move_cancelled):
            self.rfcontext.undo_cancel()
            return 'main'
        
        delta = self.rfcontext.actions.mouse.x - self.mousedown.x
        scale = delta / self.drawing.scale(100)
        snap2D_vert = self.rfcontext.snap2D_vert
        snap_vert = self.rfcontext.snap_vert
        for bmv in self.scale_bmv.keys():
            l = self.scale_bmv[bmv]
            n = Vector()
            for c,v,sc in l:
                n += c + v * max(0, 1 + scale * sc)
            bmv.co = n / len(l)
            snap_vert(bmv)
    
    
    def draw_postview(self):
        self.draw_spline()
        
        if False:
            stroke_pts = [[cb.eval(i / 5) for i in range(5+1)] for cb in self.stroke_cbs]
            stroke_der = [[cb.eval_derivative(i / 5) for i in range(5+1)] for cb in self.stroke_cbs]
            self.drawing.line_width(1.0)
            bgl.glColor4f(1,1,1,0.5)
            for pts in stroke_pts:
                bgl.glBegin(bgl.GL_LINE_STRIP)
                for pt in pts:
                    bgl.glVertex3f(*pt)
                bgl.glEnd()
            bgl.glColor4f(0,0,1,0.5)
            bgl.glBegin(bgl.GL_LINES)
            for pts,ders in zip(stroke_pts,stroke_der):
                for pt,der in zip(pts,ders):
                    bgl.glVertex3f(*pt)
                    ptder = pt + der.normalized() * 0.3
                    bgl.glVertex3f(*ptder)
            bgl.glEnd()
        
    
    def draw_spline(self):
        if not self.strips: return
        
        strips = self.strips
        hov_strips = self.hovering_strips
        
        def draw(alphamult, hov_alphamult):
            nonlocal strips
            
            bgl.glEnable(bgl.GL_BLEND)
            
            # draw outer-inner lines
            self.drawing.line_width(2.0)
            edgeShortenShader.enable()
            edgeShortenShader['uMVPMatrix'] = self.drawing.get_view_matrix_buffer()
            edgeShortenShader['uScreenSize'] = self.rfcontext.actions.size
            bgl.glBegin(bgl.GL_LINES)
            for strip in strips:
                a = hov_alphamult if strip in hov_strips else alphamult
                p0,p1,p2,p3 = strip.curve.points()
                edgeShortenShader['vColor'] = (1.00, 1.00, 1.00, 0.45 * a)
                edgeShortenShader['vFrom'] = (p1.x, p1.y, p1.z, 1.0)
                edgeShortenShader['vRadius'] = 22
                bgl.glVertex3f(*p0)
                edgeShortenShader['vColor'] = (1.00, 1.00, 1.00, 0.45 * a)
                edgeShortenShader['vFrom'] = (p0.x, p0.y, p0.z, 1.0)
                edgeShortenShader['vRadius'] = 17
                bgl.glVertex3f(*p1)
                
                edgeShortenShader['vColor'] = (1.00, 1.00, 1.00, 0.45 * a)
                edgeShortenShader['vFrom'] = (p3.x, p3.y, p3.z, 1.0)
                edgeShortenShader['vRadius'] = 17
                bgl.glVertex3f(*p2)
                edgeShortenShader['vColor'] = (1.00, 1.00, 1.00, 0.45 * a)
                edgeShortenShader['vFrom'] = (p2.x, p2.y, p2.z, 1.0)
                edgeShortenShader['vRadius'] = 22
                bgl.glVertex3f(*p3)
            bgl.glEnd()
            
            # draw junction handles (outer control points of curve)
            faces_drawn = set() # keep track of faces, so don't draw same handles 2+ times
            circleShader.enable()
            circleShader['uMVPMatrix'] = self.drawing.get_view_matrix_buffer()
            circleShader['uInOut'] = 0.8
            self.drawing.point_size(20)
            bgl.glBegin(bgl.GL_POINTS)
            for strip in strips:
                a = hov_alphamult if strip in hov_strips else alphamult
                circleShader['vOutColor'] = (0.00, 0.00, 0.00, 0.5*a)
                circleShader['vInColor']  = (1.00, 1.00, 1.00, 1.0*a)
                bmf0,bmf1 = strip.end_faces()
                p0,p1,p2,p3 = strip.curve.points()
                if bmf0 not in faces_drawn:
                    bgl.glVertex3f(*p0)
                    faces_drawn.add(bmf0)
                if bmf1 not in faces_drawn:
                    bgl.glVertex3f(*p3)
                    faces_drawn.add(bmf1)
            bgl.glEnd()
            circleShader.disable()
            
            # draw control handles (inner control points of curve)
            if options['polystrips arrows']:
                arrowShader.enable()
                arrowShader['uMVPMatrix'] = self.drawing.get_view_matrix_buffer()
                arrowShader['uInOut'] = 0.8
                self.drawing.point_size(20)
                bgl.glBegin(bgl.GL_POINTS)
                for strip in strips:
                    a = hov_alphamult if strip in hov_strips else alphamult
                    p0,p1,p2,p3 = strip.curve.points()
                    arrowShader['vOutColor'] = (0.75, 0.75, 0.75, 0.3*a)
                    arrowShader['vInColor']  = (0.25, 0.25, 0.25, 0.8*a)
                    arrowShader['vFrom'] = (p0.x, p0.y, p0.z, 1.0)
                    bgl.glVertex3f(*p1)
                    arrowShader['vFrom'] = (p3.x, p3.y, p3.z, 1.0)
                    bgl.glVertex3f(*p2)
                bgl.glEnd()
                arrowShader.disable()
            else:
                circleShader.enable()
                circleShader['uMVPMatrix'] = self.drawing.get_view_matrix_buffer()
                circleShader['uInOut'] = 0.8
                self.drawing.point_size(15)
                bgl.glBegin(bgl.GL_POINTS)
                for strip in strips:
                    a = hov_alphamult if strip in hov_strips else alphamult
                    circleShader['vOutColor'] = (0.75, 0.75, 0.75, 0.3*a)
                    circleShader['vInColor']  = (0.25, 0.25, 0.25, 0.3*a)
                    p0,p1,p2,p3 = strip.curve.points()
                    bgl.glVertex3f(*p1)
                    bgl.glVertex3f(*p2)
                bgl.glEnd()
                circleShader.disable()
            
            # draw curve
            if options['polystrips draw curve']:
                self.drawing.line_width(2.0)
                self.drawing.enable_stipple()
                bgl.glBegin(bgl.GL_LINES)
                for pts in self.strip_pts:
                    a = hov_alphamult if strip in hov_strips else alphamult
                    bgl.glColor4f(1,1,1,0.5*a)
                    for v0,v1 in zip(pts[:-1],pts[1:]):
                        bgl.glVertex3f(*v0)
                        bgl.glVertex3f(*v1)
                bgl.glEnd()
                self.drawing.disable_stipple()


        bgl.glDepthRange(0, 0.9999)     # squeeze depth just a bit 
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
        bgl.glEnable(bgl.GL_DEPTH_TEST)
        
        # draw in front of geometry
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        draw(1.00, 1.00)
        # draw behind geometry
        bgl.glDepthFunc(bgl.GL_GREATER)
        draw(0.10, 0.10)
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glDepthMask(bgl.GL_TRUE)
    
    def draw_postpixel(self):
        pass
    

