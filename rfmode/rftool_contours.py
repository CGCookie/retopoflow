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

import bpy
import bgl
import blf
import os
import math
from itertools import chain
from .rftool import RFTool
from ..lib.common_utilities import showErrorMessage
from ..lib.classes.profiler.profiler import profiler
from ..common.utils import max_index
from ..common.maths import Point,Point2D,Vec2D,Vec,Plane
from ..common.ui import UI_Label, UI_IntValue, UI_Image
from .rftool_contours_utils import *
from .rftool_contours_ops import RFTool_Contours_Ops
from mathutils import Matrix

from ..options import options, help_contours


@RFTool.action_call('contours tool')
class RFTool_Contours(RFTool, RFTool_Contours_Ops):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['move']  = self.modal_move
        self.FSM['shift'] = self.modal_shift
        self.FSM['rotate'] = self.modal_rotate
    
    def name(self): return "Contours"
    def icon(self): return "rf_contours_icon"
    def description(self): return 'Contours'
    
    def helptext(self): return help_contours

    def start(self):
        self.rfwidget.set_widget('line', color=(1.0, 1.0, 1.0))
        self.rfwidget.set_line_callback(self.line)
        self.update()

        self.show_cut = False
        self.show_arrows = False
        self.pts = []
        self.cut_pts = []
        self.connected = False
        self.cuts = []
        
        self.update_tool_options()
    
    def get_count(self): return options['contours count']
    def set_count(self, v): options['contours count'] = max(3, v)
    def get_ui_options(self):
        self.ui_count = UI_IntValue('Count', self.get_count, self.set_count)
        return [self.ui_count]
    
    def get_ui_icon(self):
        self.ui_icon = UI_Image('contours_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    def update(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        sel_strings = find_strings(sel_edges)
        self.loops_data = [{
            'loop': loop,
            'plane': loop_plane(loop),
            'count': len(loop),
            'radius': loop_radius(loop),
            'cl': Contours_Loop(loop, True),
            } for loop in sel_loops]
        self.strings_data = [{
            'string': string,
            'plane': loop_plane(string),
            'count': len(string),
            'cl': Contours_Loop(string, False),
            } for string in sel_strings]
        self.sel_loops = [Contours_Loop(loop, True) for loop in sel_loops]


    def modal_main(self):
        if self.rfcontext.actions.pressed('select'):
            self.rfcontext.undo_push('select')
            edges = self.rfcontext.visible_edges()
            edge,_ = self.rfcontext.nearest2D_edge(edges=edges)
            if not edge:
                self.rfcontext.deselect_all()
                return
            self.rfcontext.select_edge_loop(edge, only=True)
            self.update()
            return

        if self.rfcontext.actions.pressed('select add'):
            self.rfcontext.undo_push('select add')
            edges = self.rfcontext.visible_edges()
            edge,_ = self.rfcontext.nearest2D_edge(edges=edges)
            if not edge: return
            self.rfcontext.select_edge_loop(edge, only=False)
            self.update()
            return

        if self.rfcontext.actions.pressed('grab'):
            ''' grab for translations '''
            return self.prep_move()
        
        if self.rfcontext.actions.pressed('shift'):
            ''' rotation of loops '''
            return self.prep_shift()
        
        if self.rfcontext.actions.pressed('rotate'): return self.prep_rotate()

        if self.rfcontext.actions.pressed('delete'):
            self.rfcontext.undo_push('delete')
            self.rfcontext.delete_selection()
            self.rfcontext.dirty()
            self.update()
            return
        
        if self.rfcontext.actions.pressed('dissolve'):
            self.dissolve_loops()
            return

        if self.rfcontext.actions.pressed('increase count'):
            self.change_count(1)
            return
        
        if self.rfcontext.actions.pressed('decrease count'):
            self.change_count(-1)
            return

    def prep_shift(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        if not sel_loops: return
        
        self.move_cloops = [Contours_Loop(loop, True) for loop in sel_loops]
        self.move_verts = [[bmv for bmv in cloop.verts] for cloop in self.move_cloops]
        self.move_pts = [[Point(pt) for pt in cloop.pts] for cloop in self.move_cloops]
        self.move_dists = [list(cloop.dists) for cloop in self.move_cloops]
        self.move_circumferences = [cloop.circumference for cloop in self.move_cloops]
        self.move_origins = [cloop.plane.o for cloop in self.move_cloops]
        self.move_proj_dists = [list(cloop.proj_dists) for cloop in self.move_cloops]
        
        self.move_cuts = []
        for cloop in self.move_cloops:
            xy = self.rfcontext.Point_to_Point2D(cloop.plane.o)
            ray = self.rfcontext.Point2D_to_Ray(xy)
            crawl = self.rfcontext.plane_intersection_crawl(ray, cloop.plane, walk=True)
            if not crawl:
                self.move_cuts += [None]
                continue
            crawl_pts = [c for _,_,_,c in crawl]
            connected = crawl[0][0] is not None
            crawl_pts,connected = self.rfcontext.clip_pointloop(crawl_pts, connected)
            if not crawl_pts or connected != cloop.connected:
                self.move_cuts += [None]
                continue
            cl_cut = Contours_Loop(crawl_pts, connected)
            cl_cut.align_to(cloop)
            self.move_cuts += [cl_cut]
        
        self.rfcontext.undo_push('shift contours')
        
        self.mousedown = self.rfcontext.actions.mouse
        self.move_prevmouse = None
        self.move_done_pressed = 'confirm'
        self.move_done_released = None
        self.move_cancelled = 'cancel'
        
        return 'shift'
    
    @RFTool.dirty_when_done
    @profiler.profile
    def modal_shift(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'
        
        # only update cut on timer events and when mouse has moved
        if not self.rfcontext.actions.timer: return
        if self.move_prevmouse == self.rfcontext.actions.mouse: return
        self.move_prevmouse = self.rfcontext.actions.mouse
        
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        shift_offset = self.rfcontext.drawing.unscale(delta.x) / 100
        
        raycast,project = self.rfcontext.raycast_sources_Point2D,self.rfcontext.Point_to_Point2D
        for i_cloop in range(len(self.move_cloops)):
            cloop  = self.move_cloops[i_cloop]
            cl_cut = self.move_cuts[i_cloop]
            if not cl_cut: continue
            verts  = self.move_verts[i_cloop]
            dists  = self.move_dists[i_cloop]
            proj_dists = self.move_proj_dists[i_cloop]
            circumference = self.move_circumferences[i_cloop]
            
            lc = cl_cut.circumference
            shft = (cl_cut.offset + shift_offset * lc) % lc
            ndists = [shft] + [0.999 * lc * (d/circumference) for d in dists]
            i,dist = 0,ndists[0]
            l = len(ndists)-1 if cloop.connected else len(ndists)
            for c0,c1 in cl_cut.iter_pts(repeat=True):
                d = (c1-c0).length
                while dist - d <= 0:
                    # create new vert between c0 and c1
                    p = c0 + (c1 - c0) * (dist / d) + (cloop.plane.n * proj_dists[i])
                    p,_,_,_ = self.rfcontext.nearest_sources_Point(p)
                    verts[i].co = p
                    i += 1
                    if i == l: break
                    dist += ndists[i]
                dist -= d
                if i == l: break
            
            self.rfcontext.update_verts_faces(verts)

    def prep_move(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        sel_strings = find_strings(sel_edges, min_length=2)
        if not sel_loops and not sel_strings: return
        
        # prefer to move loops over strings
        if sel_loops: self.move_cloops = [Contours_Loop(loop, True) for loop in sel_loops]
        else: self.move_cloops = [Contours_Loop(string, False) for string in sel_strings]
        self.move_verts = [[bmv for bmv in cloop.verts] for cloop in self.move_cloops]
        self.move_pts = [[Point(pt) for pt in cloop.pts] for cloop in self.move_cloops]
        self.move_dists = [list(cloop.dists) for cloop in self.move_cloops]
        self.move_circumferences = [cloop.circumference for cloop in self.move_cloops]
        self.move_origins = [cloop.plane.o for cloop in self.move_cloops]
        self.move_proj_dists = [list(cloop.proj_dists) for cloop in self.move_cloops]
        
        self.rfcontext.undo_push('move contours')
        
        self.mousedown = self.rfcontext.actions.mouse
        self.move_prevmouse = None
        self.move_done_pressed = 'confirm'
        self.move_done_released = None
        self.move_cancelled = 'cancel'
        
        return 'move'
    
    @RFTool.dirty_when_done
    @profiler.profile
    def modal_move(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'
        
        # only update cut on timer events and when mouse has moved
        if not self.rfcontext.actions.timer: return
        if self.move_prevmouse == self.rfcontext.actions.mouse: return
        self.move_prevmouse = self.rfcontext.actions.mouse
        
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        
        raycast,project = self.rfcontext.raycast_sources_Point2D,self.rfcontext.Point_to_Point2D
        for i_cloop in range(len(self.move_cloops)):
            cloop  = self.move_cloops[i_cloop]
            verts  = self.move_verts[i_cloop]
            pts    = self.move_pts[i_cloop]
            dists  = self.move_dists[i_cloop]
            origin = self.move_origins[i_cloop]
            proj_dists = self.move_proj_dists[i_cloop]
            circumference = self.move_circumferences[i_cloop]
            
            depth = self.rfcontext.Point_to_depth(origin)
            origin2D_new = self.rfcontext.Point_to_Point2D(origin) + delta
            origin_new = self.rfcontext.Point2D_to_Point(origin2D_new, depth)
            plane_new = Plane(origin_new, cloop.plane.n)
            ray_new = self.rfcontext.Point2D_to_Ray(origin2D_new)
            crawl = self.rfcontext.plane_intersection_crawl(ray_new, plane_new, walk=True)
            if not crawl: continue
            crawl_pts = [c for _,_,_,c in crawl]
            connected = crawl[0][0] is not None
            crawl_pts,connected = self.rfcontext.clip_pointloop(crawl_pts, connected)
            if not crawl_pts or connected != cloop.connected: continue
            cl_cut = Contours_Loop(crawl_pts, connected)
            
            cl_cut.align_to(cloop)
            lc = cl_cut.circumference
            ndists = [cl_cut.offset] + [0.999 * lc * (d/circumference) for d in dists]
            i,dist = 0,ndists[0]
            l = len(ndists)-1 if cloop.connected else len(ndists)
            for c0,c1 in cl_cut.iter_pts(repeat=True):
                d = (c1-c0).length
                while dist - d <= 0:
                    # create new vert between c0 and c1
                    p = c0 + (c1 - c0) * (dist / d) + (cloop.plane.n * proj_dists[i])
                    p,_,_,_ = self.rfcontext.nearest_sources_Point(p)
                    verts[i].co = p
                    i += 1
                    if i == l: break
                    dist += ndists[i]
                dist -= d
                if i == l: break
            
            self.rfcontext.update_verts_faces(verts)

    def prep_rotate(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        sel_strings = find_strings(sel_edges, min_length=2)
        if not sel_loops and not sel_strings: return
        
        # prefer to move loops over strings
        if sel_loops: self.move_cloops = [Contours_Loop(loop, True) for loop in sel_loops]
        else: self.move_cloops = [Contours_Loop(string, False) for string in sel_strings]
        self.move_verts = [[bmv for bmv in cloop.verts] for cloop in self.move_cloops]
        self.move_pts = [[Point(pt) for pt in cloop.pts] for cloop in self.move_cloops]
        self.move_dists = [list(cloop.dists) for cloop in self.move_cloops]
        self.move_circumferences = [cloop.circumference for cloop in self.move_cloops]
        self.move_origins = [cloop.plane.o for cloop in self.move_cloops]
        self.move_proj_dists = [list(cloop.proj_dists) for cloop in self.move_cloops]
        
        self.rfcontext.undo_push('rotate contours')
        
        self.mousedown = self.rfcontext.actions.mouse
        
        self.rotate_about = self.rfcontext.Point_to_Point2D(sum(self.move_origins, Vec((0,0,0))) / len(self.move_origins))
        self.rotate_start = math.atan2(self.rotate_about.y - self.mousedown.y, self.rotate_about.x - self.mousedown.x)
        
        self.move_prevmouse = None
        self.move_done_pressed = 'confirm'
        self.move_done_released = None
        self.move_cancelled = 'cancel'
        
        return 'rotate'
    
    @RFTool.dirty_when_done
    @profiler.profile
    def modal_rotate(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'
        
        # only update cut on timer events and when mouse has moved
        if not self.rfcontext.actions.timer: return
        if self.move_prevmouse == self.rfcontext.actions.mouse: return
        self.move_prevmouse = self.rfcontext.actions.mouse
        
        delta = Vec2D(self.rfcontext.actions.mouse - self.rotate_about)
        rotate = (math.atan2(delta.y, delta.x) - self.rotate_start + math.pi) % (math.pi * 2)
        
        raycast,project = self.rfcontext.raycast_sources_Point2D,self.rfcontext.Point_to_Point2D
        for i_cloop in range(len(self.move_cloops)):
            cloop  = self.move_cloops[i_cloop]
            verts  = self.move_verts[i_cloop]
            pts    = self.move_pts[i_cloop]
            dists  = self.move_dists[i_cloop]
            origin = self.move_origins[i_cloop]
            proj_dists = self.move_proj_dists[i_cloop]
            circumference = self.move_circumferences[i_cloop]
            
            origin2D = self.rfcontext.Point_to_Point2D(origin)
            ray = self.rfcontext.Point_to_Ray(origin)
            rmat = Matrix.Rotation(rotate, 4, -ray.d)
            normal = rmat * cloop.plane.n
            plane = Plane(cloop.plane.o, normal)
            ray = self.rfcontext.Point2D_to_Ray(origin2D)
            crawl = self.rfcontext.plane_intersection_crawl(ray, plane, walk=True)
            if not crawl: continue
            crawl_pts = [c for _,_,_,c in crawl]
            connected = crawl[0][0] is not None
            crawl_pts,connected = self.rfcontext.clip_pointloop(crawl_pts, connected)
            if not crawl_pts or connected != cloop.connected: continue
            cl_cut = Contours_Loop(crawl_pts, connected)
            
            cl_cut.align_to(cloop)
            lc = cl_cut.circumference
            ndists = [cl_cut.offset] + [0.999 * lc * (d/circumference) for d in dists]
            i,dist = 0,ndists[0]
            l = len(ndists)-1 if cloop.connected else len(ndists)
            for c0,c1 in cl_cut.iter_pts(repeat=True):
                d = (c1-c0).length
                d = max(0.00000001, d)
                while dist - d <= 0:
                    # create new vert between c0 and c1
                    p = c0 + (c1 - c0) * (dist / d) + (cloop.plane.n * proj_dists[i])
                    p,_,_,_ = self.rfcontext.nearest_sources_Point(p)
                    verts[i].co = p
                    i += 1
                    if i == l: break
                    dist += ndists[i]
                dist -= d
                if i == l: break
            
            self.rfcontext.update_verts_faces(verts)

    def draw_postview(self):
        if self.show_cut:
            self.drawing.line_width(1.0)
            
            bgl.glBegin(bgl.GL_LINES)
            bgl.glColor4f(1,1,0,1)
            for pt0,pt1 in iter_pairs(self.pts, self.connected):
                bgl.glVertex3f(*pt0)
                bgl.glVertex3f(*pt1)
            
            bgl.glColor4f(0,1,1,1)
            for pt0,pt1 in iter_pairs(self.cut_pts, self.connected):
                bgl.glVertex3f(*pt0)
                bgl.glVertex3f(*pt1)
            bgl.glEnd()

    def draw_postpixel(self):
        point_to_point2d = self.rfcontext.Point_to_Point2D
        up = self.rfcontext.Vec_up()
        size_to_size2D = self.rfcontext.size_to_size2D
        text_draw2D = self.rfcontext.drawing.text_draw2D
        self.rfcontext.drawing.text_size(12)

        for loop_data in self.loops_data:
            loop = loop_data['loop']
            radius = loop_data['radius']
            count = loop_data['count']
            plane = loop_data['plane']
            cl = loop_data['cl']
            
            # draw segment count label
            cos = [point_to_point2d(vert.co) for vert in loop]
            cos = [co for co in cos if co]
            if cos:
                xy = max(cos, key=lambda co:co.y)
                xy.y += 10
                text_draw2D(count, xy, (1,1,0,1), dropshadow=(0,0,0,0.5))

            # draw arrows
            if self.show_arrows:
                self.drawing.line_width(2.0)
                p0 = point_to_point2d(plane.o)
                p1 = point_to_point2d(plane.o+plane.n*0.1)
                if p0 and p1:
                    bgl.glColor4f(1,1,0,0.5)
                    draw2D_arrow(p0, p1)
                p1 = point_to_point2d(plane.o+cl.up_dir*0.1)
                if p0 and p1:
                    bgl.glColor4f(1,0,1,0.5)
                    draw2D_arrow(p0, p1)

        for string_data in self.strings_data:
            string = string_data['string']
            count = string_data['count']
            plane = string_data['plane']
            
            # draw segment count label
            cos = [point_to_point2d(vert.co) for vert in string]
            cos = [co for co in cos if co]
            if cos:
                xy = max(cos, key=lambda co:co.y)
                xy.y += 10
                text_draw2D(count, xy, (1,1,0,1), dropshadow=(0,0,0,0.5))
            
            # draw arrows
            if self.show_arrows:
                p0 = point_to_point2d(plane.o)
                p1 = point_to_point2d(plane.o+plane.n*0.1)
                if p0 and p1:
                    bgl.glColor4f(1,1,0,0.5)
                    draw2D_arrow(p0, p1)
                p1 = point_to_point2d(plane.o+cl.up_dir*0.1)
                if p0 and p1:
                    bgl.glColor4f(1,0,1,0.5)
                    draw2D_arrow(p0, p1)
        
        # draw new cut info
        if self.show_cut:
            for cl in self.cuts:
                plane = cl.plane
                self.drawing.line_width(2.0)
                p0 = point_to_point2d(plane.o)
                p1 = point_to_point2d(plane.o+plane.n*0.1)
                if p0 and p1:
                    bgl.glColor4f(1,1,0,0.5)
                    draw2D_arrow(p0, p1)
                p1 = point_to_point2d(plane.o+cl.up_dir*0.1)
                if p0 and p1:
                    bgl.glColor4f(1,0,1,0.5)
                    draw2D_arrow(p0, p1)
        
        if self.mode == 'rotate':
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glColor4f(1,1,1,0.5)
            self.drawing.line_width(1.0)
            bgl.glBegin(bgl.GL_LINES)
            bgl.glVertex2f(*self.rotate_about)
            bgl.glVertex2f(*self.rfcontext.actions.mouse)
            bgl.glEnd()
