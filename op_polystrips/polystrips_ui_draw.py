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
from ..cache import mesh_cache

class Polystrips_UI_Draw():
    
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
            for gv in self.polystrips.gverts:
                gv.update_visibility(r3d)
                
            for gv in self.polystrips.extension_geometry:
                gv.update_visibility(r3d)
                
            for ge in self.polystrips.gedges:
                ge.update_visibility(r3d)
            for gp in self.polystrips.gpatches:
                gp.update_visibility(r3d)
            if self.act_gedge:
                for gv in [self.act_gedge.gvert1, self.act_gedge.gvert2]:
                    gv.update_visibility(r3d)
            if self.act_gvert:
                for gv in self.act_gvert.get_inner_gverts():
                    gv.update_visibility(r3d)

            if len(self.snap_eds):
                print('snap eds are used! but probably not')
                mx = self.mx
                self.snap_eds_vis = [False not in common_utilities.ray_cast_visible_bvh([mx * ed.verts[0].co, mx * ed.verts[1].co], mesh_cache['bvh'], self.mx, r3d) for ed in self.snap_eds]

            self.post_update = False
            self.last_matrix = new_matrix

        self.draw_2D(context)

    def draw_gedge_direction(self, context, gedge, color):
        p0,p1,p2,p3 = gedge.gvert0.snap_pos,  gedge.gvert1.snap_pos,  gedge.gvert2.snap_pos,  gedge.gvert3.snap_pos
        n0,n1,n2,n3 = gedge.gvert0.snap_norm, gedge.gvert1.snap_norm, gedge.gvert2.snap_norm, gedge.gvert3.snap_norm
        pm = cubic_bezier_blend_t(p0,p1,p2,p3,0.5)
        px = cubic_bezier_derivative(p0,p1,p2,p3,0.5).normalized()
        pn = (n0+n3).normalized()
        py = pn.cross(px).normalized()
        rs = (gedge.gvert0.radius+gedge.gvert3.radius) * 0.35
        rl = rs * 0.75
        p3d = [pm-px*rs,pm+px*rs,pm+px*(rs-rl)+py*rl,pm+px*rs,pm+px*(rs-rl)-py*rl]
        common_drawing_px.draw_polyline_from_3dpoints(context, p3d, color, 5, "GL_LINE_SMOOTH")


    def draw_gedge_text(self, gedge,context, text):
        l = len(gedge.cache_igverts)
        if l > 4:
            n_quads = math.floor(l/2) + 1
            mid_vert_ind = math.floor(l/2)
            mid_vert = gedge.cache_igverts[mid_vert_ind]
            position_3d = mid_vert.position + 1.5 * mid_vert.tangent_y * mid_vert.radius
        else:
            position_3d = (gedge.gvert0.position + gedge.gvert3.position)/2
        
        position_2d = location_3d_to_region_2d(context.region, context.space_data.region_3d,position_3d)
        txt_width, txt_height = blf.dimensions(0, text)
        blf.position(0, position_2d[0]-(txt_width/2), position_2d[1]-(txt_height/2), 0)
        blf.draw(0, text)

    def draw_gedge_info(self, gedge,context):
        '''
        helper draw module to display info about the Gedge
        '''
        l = len(gedge.cache_igverts)
        if l > 4:
            n_quads = math.floor(l/2) + 1
        else:
            n_quads = 3
        self.draw_gedge_text(gedge, context, str(n_quads))

    def draw_3d(self, context):
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
        color_fill   = (color_inactive[0], color_inactive[1], color_inactive[2], 0.20)
        color_mirror = (color_frozen[0], color_frozen[1], color_frozen[2], 0.20)
        
        bgl.glDepthRange(0.0, 0.999)
        
        def draw3d_polyline(context, points, color, thickness, LINE_TYPE):
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glLineStipple(4, 0x5555)  #play with this later
                bgl.glEnable(bgl.GL_LINE_STIPPLE)  
            bgl.glEnable(bgl.GL_BLEND)
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
        def draw3d_closed_polylines(context, lpoints, color, thickness, LINE_TYPE):
            lpoints = list(lpoints)
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glLineStipple(4, 0x5555)  #play with this later
                bgl.glEnable(bgl.GL_LINE_STIPPLE)  
            bgl.glEnable(bgl.GL_BLEND)
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
        def draw3d_quad(context, points, color):
            bgl.glEnable(bgl.GL_BLEND)
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
        def draw3d_quads(context, lpoints, color, color_mirror):
            lpoints = list(lpoints)
            bgl.glEnable(bgl.GL_BLEND)
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
        def draw3d_points(context, points, color, size):
            bgl.glColor4f(*color)
            bgl.glPointSize(size)
            bgl.glDepthRange(0.0, 0.997)
            bgl.glBegin(bgl.GL_POINTS)
            for coord in points: bgl.glVertex3f(*coord)
            bgl.glEnd()
            bgl.glPointSize(1.0)
            

        ### Patches ###
        for gpatch in self.polystrips.gpatches:
            if gpatch == self.act_gpatch:
                color_border = (color_active[0], color_active[1], color_active[2], 0.50)
                color_fill = (color_active[0], color_active[1], color_active[2], 0.20)
            else:
                color_border = (color_inactive[0], color_inactive[1], color_inactive[2], 0.50)
                color_fill = (color_inactive[0], color_inactive[1], color_inactive[2], 0.10)
            if gpatch.is_frozen():
                color_border = (color_frozen[0], color_frozen[1], color_frozen[2], 1.00)
                color_fill   = (color_frozen[0], color_frozen[1], color_frozen[2], 0.20)
            if gpatch.count_error:
                color_border = (color_warning[0], color_warning[1], color_warning[2], 0.50)
                color_fill   = (color_warning[0], color_warning[1], color_warning[2], 0.10)
            
            draw3d_quads(context, gpatch.iter_segments(), color_fill, color_mirror)
            draw3d_closed_polylines(context, gpatch.iter_segments(), color_border, 1, "GL_LINE_STIPPLE")
            draw3d_points(context, [p for p,v,k in gpatch.pts if v], color_border, 3)
            

        ### Edges ###
        for gedge in self.polystrips.gedges:
            # Color active strip
            if gedge == self.act_gedge:
                color_border = (color_active[0], color_active[1], color_active[2], 1.00)
                color_fill = (color_active[0], color_active[1], color_active[2], 0.20)
            # Color selected strips
            elif gedge in self.sel_gedges:
                color_border = (color_selection[0], color_selection[1], color_selection[2], 0.75)
                color_fill = (color_selection[0], color_selection[1], color_selection[2], 0.20)
            # Color unselected strips
            else:
                color_border = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
                color_fill = (color_inactive[0], color_inactive[1], color_inactive[2], 0.20)
            
            if gedge.is_frozen():
                color_border = (color_frozen[0], color_frozen[1], color_frozen[2], 1.00)
                color_fill   = (color_frozen[0], color_frozen[1], color_frozen[2], 0.20)
            
            draw3d_quads(context, gedge.iter_segments(), color_fill, color_mirror)
            draw3d_closed_polylines(context, gedge.iter_segments(), color_border, 1, "GL_LINE_STIPPLE")

            if settings.debug >= 2:
                # draw bezier
                p0,p1,p2,p3 = gedge.gvert0.snap_pos, gedge.gvert1.snap_pos, gedge.gvert2.snap_pos, gedge.gvert3.snap_pos
                p3d = [cubic_bezier_blend_t(p0,p1,p2,p3,t/16.0) for t in range(17)]
                draw3d_polyline(context, p3d, (1,1,1,0.5),1, "GL_LINE_STIPPLE")

        ### Verts ###
        for gv in self.polystrips.gverts:
            #if not gv.is_visible(): continue
            p0,p1,p2,p3 = gv.get_corners()

            if gv.is_unconnected() and not gv.from_mesh: continue

            is_active = False
            is_active |= gv == self.act_gvert
            is_active |= self.act_gedge!=None and (self.act_gedge.gvert0 == gv or self.act_gedge.gvert1 == gv)
            is_active |= self.act_gedge!=None and (self.act_gedge.gvert2 == gv or self.act_gedge.gvert3 == gv)

            # Theme colors for selected and unselected gverts
            if is_active:
                color_border = (color_active[0], color_active[1], color_active[2], 0.75)
                color_fill   = (color_active[0], color_active[1], color_active[2], 0.20)
            else:
                color_border = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
                color_fill   = (color_inactive[0], color_inactive[1], color_inactive[2], 0.20)
            # # Take care of gverts in selected edges
            if gv in self.sel_gverts:
                color_border = (color_selection[0], color_selection[1], color_selection[2], 0.75)
                color_fill   = (color_selection[0], color_selection[1], color_selection[2], 0.20)
            if gv.is_frozen():
                color_border = (color_frozen[0], color_frozen[1], color_frozen[2], 1.00)
                color_fill   = (color_frozen[0], color_frozen[1], color_frozen[2], 0.20)

            p3d = [p0,p1,p2,p3,p0]
            draw3d_quads(context, [[p0,p1,p2,p3]], color_fill, color_mirror)
            draw3d_polyline(context, p3d, color_border, 1, "GL_LINE_STIPPLE")

        # Draw inner gvert handles (dots) on each gedge
        p3d = [gvert.position for gvert in self.polystrips.gverts if not gvert.is_unconnected() and gvert.is_visible()]
        # color_handle = (color_active[0], color_active[1], color_active[2], 1.00)
        draw3d_points(context, p3d, color_handle, 4)

        ### Vert Handles ###
        if self.act_gvert:
            color_handle = (color_active[0], color_active[1], color_active[2], 1.00)
            gv = self.act_gvert
            p0 = gv.position
            draw3d_points(context, [p0], color_handle, 8)
            
            if gv.is_inner():
                # Draw inner handle when selected
                p1 = gv.gedge_inner.get_outer_gvert_at(gv).position
                draw3d_polyline(context, [p0,p1], color_handle, 2, "GL_LINE_SMOOTH")
            else:
                # Draw both handles when gvert is selected
                p3d = [ge.get_inner_gvert_at(gv).position for ge in gv.get_gedges_notnone() if not ge.is_zippered()]
                draw3d_points(context, p3d, color_handle, 8)
                # Draw connecting line between handles
                for p1 in p3d:
                    draw3d_polyline(context, [p0,p1], color_handle, 2, "GL_LINE_SMOOTH")

        # Draw gvert handles on active gedge
        if self.act_gedge:
            color_handle = (color_active[0], color_active[1], color_active[2], 1.00)
            ge = self.act_gedge
            if self.act_gedge.is_zippered():
                p3d = [ge.gvert0.position, ge.gvert3.position]
                draw3d_points(context, p3d, color, 8)
            
            else:
                p3d = [gv.position for gv in ge.gverts()]
                draw3d_points(context, p3d, color_handle, 8)
                draw3d_polyline(context, [p3d[0], p3d[1]], color_handle, 2, "GL_LINE_SMOOTH")
                draw3d_polyline(context, [p3d[2], p3d[3]], color_handle, 2, "GL_LINE_SMOOTH")

            if settings.show_segment_count:
                self.draw_gedge_info(self.act_gedge, context)
                
        if self.hov_gvert:  #TODO, hover color
            color_border = (color_selection[0], color_selection[1], color_selection[2], 1.00)
            color_fill   = (color_selection[0], color_selection[1], color_selection[2], 0.20)
            
            gv = self.hov_gvert
            p0,p1,p2,p3 = gv.get_corners()
            p3d = [p0,p1,p2,p3,p0]
            draw3d_quad(context, [p0,p1,p2,p3], color_fill)
            draw3d_polyline(context, p3d, color_border, 1, "GL_LINE_STIPPLE")
            

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

        if self.fsm_mode in {'scale tool','rotate tool'}:
            # Draw a scale/rotate line from tool origin to current mouse position
            common_drawing_px.draw_polyline_from_points(context, [self.action_center, self.mode_pos], (0, 0, 0, 0.5), 1, "GL_LINE_STIPPLE")

        bgl.glLineWidth(1)

        if self.fsm_mode == 'brush scale tool':
            # scaling brush size
            self.sketch_brush.draw(context, color=(1, 1, 1, .5), linewidth=1, color_size=(1, 1, 1, 1))
        elif self.fsm_mode not in {'grab tool','scale tool','rotate tool'} and not self.is_navigating:
            # draw the brush oriented to surface
            ray,hit = common_utilities.ray_cast_region2d_bvh(region, r3d, self.cur_pos, mesh_cache['bvh'], self.mx, settings)
            hit_p3d,hit_norm,hit_idx = hit
            if hit_idx != None: # and not self.hover_ed:
                mx = self.mx
                mxnorm = mx.transposed().inverted().to_3x3()
                hit_p3d = mx * hit_p3d
                hit_norm = mxnorm * hit_norm
                if settings.use_pressure:
                    common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius_pressure, (1,1,1,.5))
                else:
                    common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius, (1,1,1,.5))
            if self.fsm_mode == 'sketch':
                ray,hit = common_utilities.ray_cast_region2d_bvh(region, r3d, self.sketch[0][0], mesh_cache['bvh'],self.mx, settings)
                hit_p3d,hit_norm,hit_idx = hit
                if hit_idx != None:
                    mx = self.mx
                    mxnorm = mx.transposed().inverted().to_3x3()
                    hit_p3d = mx * hit_p3d
                    hit_norm = mxnorm * hit_norm
                    if settings.use_pressure:
                        common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius_pressure, (1,1,1,.5))
                    else:
                        common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius, (1,1,1,.5))

        if self.hover_ed and False:  #EXTEND  to display hoverable edges
            color = (color_selection[0], color_selection[1], color_selection[2], 1.00)
            common_drawing_px.draw_bmedge(context, self.hover_ed, self.dest_obj.matrix_world, 2, color)


        if settings.show_help:
            self.help_box.draw()
    
