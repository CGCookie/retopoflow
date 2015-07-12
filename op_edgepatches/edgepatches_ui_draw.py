'''
Copyright (C) 2015 CG Cookie
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

# System imports
import math
import itertools
import time
from mathutils import Vector, Quaternion, Matrix
from mathutils.geometry import intersect_point_line, intersect_line_plane

# Blender imports
import bgl
import blf
import bmesh
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d

# Common imports
from ..lib import common_utilities
from ..lib import common_drawing_px
from ..lib.common_utilities import iter_running_sum, dprint, get_object_length_scale, profiler, AddonLocator

from ..preferences import RetopoFlowPreferences


class EdgePatches_UI_Draw():
    
    def draw_postview(self, context):
        ''' Place post view drawing code in here '''
        self.draw_3d(context)
        pass
    
    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
        
        settings = common_utilities.get_settings()
        region,r3d = context.region,context.space_data.region_3d

        new_matrix = [v for l in r3d.view_matrix for v in l]
        if self.post_update or self.last_matrix != new_matrix:
            # update_visibility?
            self.post_update = False
            self.last_matrix = new_matrix

        self.draw_2D(context)


    def draw_3d(self, context):
        settings = common_utilities.get_settings()
        region,r3d = context.region,context.space_data.region_3d
        
        color_inactive = RetopoFlowPreferences.theme_colors_mesh[settings.theme]
        color_selection = RetopoFlowPreferences.theme_colors_selection[settings.theme]
        color_active = RetopoFlowPreferences.theme_colors_active[settings.theme]

        color_frozen = RetopoFlowPreferences.theme_colors_frozen[settings.theme]
        color_warning = RetopoFlowPreferences.theme_colors_warning[settings.theme]

        bgl.glEnable(bgl.GL_POINT_SMOOTH)
        bgl.glEnable(bgl.GL_BLEND)

        color_handle = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
        color_border = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
        color_fill   = (color_inactive[0], color_inactive[1], color_inactive[2], 0.20)
        color_mirror = (color_frozen[0], color_frozen[1], color_frozen[2], 0.20)
        
        bgl.glDepthRange(0.0, 0.999)
        
        def draw3d_polyline(points, color, thickness, LINE_TYPE):
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glLineStipple(4, 0x5555)  #play with this later
                bgl.glEnable(bgl.GL_LINE_STIPPLE)  
            bgl.glColor4f(*color)
            bgl.glLineWidth(thickness)
            bgl.glDepthRange(0.0, 0.997)
            bgl.glBegin(bgl.GL_LINE_STRIP)
            for coord in points: bgl.glVertex3f(*coord)
            bgl.glEnd()
            bgl.glLineWidth(1)
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glDisable(bgl.GL_LINE_STIPPLE)
                bgl.glEnable(bgl.GL_BLEND)  # back to uninterrupted lines  
        def draw3d_closed_polylines(lpoints, color, thickness, LINE_TYPE):
            lpoints = list(lpoints)
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glLineStipple(4, 0x5555)  #play with this later
                bgl.glEnable(bgl.GL_LINE_STIPPLE)  
            bgl.glLineWidth(thickness)
            bgl.glDepthRange(0.0, 0.997)
            bgl.glColor4f(*color)
            for points in lpoints:
                bgl.glBegin(bgl.GL_LINE_STRIP)
                for coord in points:
                    bgl.glVertex3f(*coord)
                bgl.glVertex3f(*points[0])
                bgl.glEnd()
            if settings.symmetry_plane == 'x':
                bgl.glColor4f(*color_mirror)
                for points in lpoints:
                    bgl.glBegin(bgl.GL_LINE_STRIP)
                    for coord in points:
                        bgl.glVertex3f(-coord.x, coord.y, coord.z)
                    bgl.glVertex3f(-points[0].x, points[0].y, points[0].z)
                    bgl.glEnd()
                
            bgl.glLineWidth(1)
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glDisable(bgl.GL_LINE_STIPPLE)
                bgl.glEnable(bgl.GL_BLEND)  # back to uninterrupted lines  
        def draw3d_quad(points, color):
            bgl.glDepthRange(0.0, 0.999)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glColor4f(*color)
            for coord in points:
                bgl.glVertex3f(*coord)
            if settings.symmetry_plane == 'x':
                bgl.glColor4f(*color_mirror)
                for coord in points:
                    bgl.glVertex3f(-coord.x,coord.y,coord.z)
            bgl.glEnd()
        def draw3d_quads(lpoints, color, color_mirror):
            lpoints = list(lpoints)
            bgl.glDepthRange(0.0, 0.999)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glColor4f(*color)
            for points in lpoints:
                for coord in points:
                    bgl.glVertex3f(*coord)
            if settings.symmetry_plane == 'x':
                bgl.glColor4f(*color_mirror)
                for points in lpoints:
                    for coord in points:
                        bgl.glVertex3f(-coord.x,coord.y,coord.z)
            bgl.glEnd()
        def draw3d_points(points, color, size):
            bgl.glColor4f(*color)
            bgl.glPointSize(size)
            bgl.glDepthRange(0.0, 0.997)
            bgl.glBegin(bgl.GL_POINTS)
            for coord in points: bgl.glVertex3f(*coord)
            bgl.glEnd()
            bgl.glPointSize(1.0)
            

        ### EPVerts ###
        for epvert in self.edgepatches.epverts:
            if epvert.is_inner(): continue
            
            if epvert == self.act_epvert:
                color = (color_active[0], color_active[1], color_active[2], 0.50)
            else:
                color = (color_inactive[0], color_inactive[1], color_inactive[2], 0.50)
            
            draw3d_points([epvert.snap_pos], color, 8)
        
        for epedge in self.edgepatches.epedges:
            if epedge == self.act_epedge:
                color = (color_active[0], color_active[1], color_active[2], 0.50)
            else:
                color = (color_inactive[0], color_inactive[1], color_inactive[2], 0.50)
            draw3d_polyline(epedge.curve_verts, color, 5, 'GL_LINE_STIPPLE')
        
        if self.act_epvert:
            epv0 = self.act_epvert
            color = (color_active[0], color_active[1], color_active[2], 0.50)
            if epv0.is_inner():
                epe = epv0.get_epedges()[0]
                epv1 = epe.get_outer_epvert_at(epv0)
                draw3d_points([epv0.snap_pos], color, 8)
                draw3d_polyline([epv0.snap_pos,epv1.snap_pos], color, 5, 'GL_LINE_SMOOTH')
            else:
                for epe in epv0.get_epedges():
                    epv1 = epe.get_inner_epvert_at(epv0)
                    draw3d_points([epv1.snap_pos], color, 8)
                    draw3d_polyline([epv0.snap_pos,epv1.snap_pos], color, 5, 'GL_LINE_SMOOTH')
        
        if self.act_epedge:
            p0,p1,p2,p3 = self.act_epedge.epverts_pos()
            color = (color_active[0], color_active[1], color_active[2], 0.50)
            draw3d_points([p0,p1,p2,p3], color, 8)
            draw3d_polyline([p0,p1], color, 5, 'GL_LINE_SMOOTH')
            draw3d_polyline([p3,p2], color, 5, 'GL_LINE_SMOOTH')

        bgl.glLineWidth(1)
        bgl.glDepthRange(0.0, 1.0)
    

    def draw_2D(self, context):
        settings = common_utilities.get_settings()
        region,r3d = context.region,context.space_data.region_3d
        
        color_inactive = RetopoFlowPreferences.theme_colors_mesh[settings.theme]
        color_selection = RetopoFlowPreferences.theme_colors_selection[settings.theme]
        color_active = RetopoFlowPreferences.theme_colors_active[settings.theme]

        color_frozen = RetopoFlowPreferences.theme_colors_frozen[settings.theme]
        color_warning = RetopoFlowPreferences.theme_colors_warning[settings.theme]

        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        color_handle = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
        color_border = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
        color_fill = (color_inactive[0], color_inactive[1], color_inactive[2], 0.20)
        

        if self.fsm_mode == 'sketch':
            # Draw smoothing line (end of sketch to current mouse position)
            common_drawing_px.draw_polyline_from_points(context, [self.sketch_curpos, self.sketch[-1][0]], color_active, 1, "GL_LINE_SMOOTH")

            # Draw sketching stroke
            common_drawing_px.draw_polyline_from_points(context, [co[0] for co in self.sketch], color_selection, 2, "GL_LINE_STIPPLE")

            # Report pressure reading
            if settings.use_pressure:
                info = str(round(self.sketch_pressure,3))
                txt_width, txt_height = blf.dimensions(0, info)
                d = self.sketch_brush.pxl_rad
                blf.position(0, self.sketch_curpos[0] - txt_width/2, self.sketch_curpos[1] + d + txt_height, 0)
                blf.draw(0, info)


        bgl.glLineWidth(1)

        if not self.is_navigating:
            # draw the brush oriented to surface
            ray,hit = common_utilities.ray_cast_region2d(region, r3d, self.cur_pos, self.obj, settings)
            hit_p3d,hit_norm,hit_idx = hit
            if hit_idx != -1: # and not self.hover_ed:
                mx = self.obj.matrix_world
                mxnorm = mx.transposed().inverted().to_3x3()
                hit_p3d = mx * hit_p3d
                hit_norm = mxnorm * hit_norm
                if settings.use_pressure:
                    common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius_pressure, (1,1,1,.5))
                else:
                    common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius, (1,1,1,.5))
            if self.fsm_mode == 'sketch':
                ray,hit = common_utilities.ray_cast_region2d(region, r3d, self.sketch[0][0], self.obj, settings)
                hit_p3d,hit_norm,hit_idx = hit
                if hit_idx != -1:
                    mx = self.obj.matrix_world
                    mxnorm = mx.transposed().inverted().to_3x3()
                    hit_p3d = mx * hit_p3d
                    hit_norm = mxnorm * hit_norm
                    if settings.use_pressure:
                        common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius_pressure, (1,1,1,.5))
                    else:
                        common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius, (1,1,1,.5))


        if settings.show_help:
            self.help_box.draw()
    
