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
import sys
import math
import itertools
import time
import types
from itertools import chain
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
from ..lib.common_shader import shader_helper
from ..lib.common_utilities import iter_running_sum, dprint, get_object_length_scale, invert_matrix, matrix_normal
from ..lib.common_bezier import cubic_bezier_blend_t, cubic_bezier_derivative
from ..lib.common_drawing_view import draw3d_arrow
from ..lib.classes.profiler import profiler

from ..cache import mesh_cache

def vector_mirror_0(v): return v
def vector_mirror_x(v): return Vector((-v.x,v.y,v.z))

class Polystrips_UI_Draw():
    def initialize_draw(self):
        shaderVertSource = '''
        void main() {
            gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
            gl_FrontColor = gl_Color;
        }
        '''
        shaderFragSource = '''
        void main() {
            gl_FragColor = gl_Color;
        }
        '''
        self.shaderProg = shader_helper(shaderVertSource, shaderFragSource)
        
    
    def draw_postview(self, context):
        ''' Place post view drawing code in here '''
        try:
            bgl.glUseProgram(self.shaderProg)
            self.draw_3d(context)
        except:
            pass
        finally:
            bgl.glUseProgram(0)
    
    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
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
        if position_2d is None: return
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
    
    
    def draw_gpatch_info(self, gpatch, context):
        cp,cnt = Vector(),0
        for p,_,_ in gpatch.pts:
            cp += p
            cnt += 1
        cp /= max(1,cnt)
        for i_ges,ges in enumerate(gpatch.gedgeseries):
            l = ges.n_quads
            p,c = Vector(),0
            for gvert in ges.cache_igverts:
                p += gvert.snap_pos
                c += 1
            p /= c
            txt = '%d' % l # '%d %d' % (i_ges,l)
            p2d = location_3d_to_region_2d(context.region, context.space_data.region_3d, cp*0.2+p*0.8)
            if p2d is None: continue
            txt_width, txt_height = blf.dimensions(0, txt)
            blf.position(0, p2d[0]-(txt_width/2), p2d[1]-(txt_height/2), 0)
            blf.draw(0, txt)
            
    
    def draw_3d(self, context):
        settings = common_utilities.get_settings()
        region,r3d = context.region,context.space_data.region_3d
        view_dir = r3d.view_rotation * Vector((0,0,-1))
        view_loc = r3d.view_location - view_dir * r3d.view_distance
        if r3d.view_perspective == 'ORTHO': view_loc -= view_dir * 1000.0
        view_loc_x = vector_mirror_x(view_loc)
        
        color_inactive = settings.theme_colors_mesh[settings.theme]
        color_selection = settings.theme_colors_selection[settings.theme]
        color_active = settings.theme_colors_active[settings.theme]

        color_frozen = settings.theme_colors_frozen[settings.theme]
        color_warning = settings.theme_colors_warning[settings.theme]

        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        color_handle = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
        color_border = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
        color_fill   = (color_inactive[0], color_inactive[1], color_inactive[2], 0.20)
        color_mirror = (color_frozen[0], color_frozen[1], color_frozen[2], 0.20)
        
        #bgl.glDepthRange(0.0, 0.999)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glEnable(bgl.GL_DEPTH_TEST)
        
        def set_depthrange(near=0.0, far=1.0, points=None):
            if points and len(points) and view_loc:
                d2 = min((view_loc-p).length_squared for p in points)
                d = math.sqrt(d2)
                d2 /= 10.0
                near = near / d2
                far = 1.0 - ((1.0 - far) / d2)
            near = max(0.0, min(1.0, near))
            far = max(near, min(1.0, far))
            bgl.glDepthRange(near, far)
            #bgl.glDepthRange(0.0, 0.5)
        
        def draw3d_polyline(context, points, color, thickness, LINE_TYPE, mirror):
            points = [mirror(pt) for pt in points]
            if len(points) == 0: return
            # if type(points) is types.GeneratorType:
            #     points = list(points)
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glLineStipple(4, 0x5555)  #play with this later
                bgl.glEnable(bgl.GL_LINE_STIPPLE)  
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glColor4f(*color)
            bgl.glLineWidth(thickness)
            set_depthrange(0.0, 0.997, points)
            bgl.glBegin(bgl.GL_LINE_STRIP)
            for coord in points: bgl.glVertex3f(*coord)
            bgl.glEnd()
            bgl.glLineWidth(1)
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glDisable(bgl.GL_LINE_STIPPLE)
                bgl.glEnable(bgl.GL_BLEND)  # back to uninterrupted lines
        
        def draw3d_closed_polylines(context, lpoints, color, thickness, LINE_TYPE, mirror):
            #if type(lpoints) is types.GeneratorType:
            #    lpoints = list(lpoints)
            lpoints = [[mirror(pt) for pt in points] for points in lpoints]
            if len(lpoints) == 0: return
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glLineStipple(4, 0x5555)  #play with this later
                bgl.glEnable(bgl.GL_LINE_STIPPLE)  
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glLineWidth(thickness)
            bgl.glColor4f(*color)
            for points in lpoints:
                set_depthrange(0.0, 0.997, points)
                bgl.glBegin(bgl.GL_LINE_STRIP)
                for coord in chain(points,points[:1]):
                    bgl.glVertex3f(*coord)
                bgl.glEnd()
            # if settings.symmetry_plane == 'x':
            #     bgl.glColor4f(*color_mirror)
            #     for points in lpoints:
            #         bgl.glBegin(bgl.GL_LINE_STRIP)
            #         for coord in points:
            #             bgl.glVertex3f(-coord.x, coord.y, coord.z)
            #         bgl.glVertex3f(-points[0].x, points[0].y, points[0].z)
            #         bgl.glEnd()
                
            bgl.glLineWidth(1)
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glDisable(bgl.GL_LINE_STIPPLE)
                bgl.glEnable(bgl.GL_BLEND)  # back to uninterrupted lines  
        
        def draw3d_quad(context, points, color, mirror):
            #if type(points) is types.GeneratorType:
            #    points = list(points)
            points = [mirror(pt) for pt in points]
            if len(points) == 0: return
            bgl.glEnable(bgl.GL_BLEND)
            set_depthrange(0.0, 0.998, points)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glColor4f(*color)
            for coord in points: bgl.glVertex3f(*coord)
            # if settings.symmetry_plane == 'x':
            #     bgl.glColor4f(*color_mirror)
            #     for coord in points:
            #         bgl.glVertex3f(-coord.x,coord.y,coord.z)
            bgl.glEnd()
        
        def draw3d_quads(context, lpoints, color, mirror):
            #if type(lpoints) is types.GeneratorType:
            #    lpoints = list(lpoints)
            lpoints = [[mirror(pt) for pt in points] for points in lpoints]
            if len(lpoints) == 0: return
            bgl.glEnable(bgl.GL_BLEND)
            set_depthrange(0.0, 0.998, [p for pts in lpoints for p in pts])
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glColor4f(*color)
            for points in lpoints:
                for coord in points:
                    bgl.glVertex3f(*coord)
            # if settings.symmetry_plane == 'x':
            #     bgl.glColor4f(*color_mirror)
            #     for points in lpoints:
            #         for coord in points:
            #             bgl.glVertex3f(-coord.x,coord.y,coord.z)
            bgl.glEnd()
        
        def draw3d_points(context, points, color, size, mirror):
            #if type(points) is types.GeneratorType:
            #    points = list(points)
            points = [mirror(pt) for pt in points]
            if len(points) == 0: return
            bgl.glColor4f(*color)
            bgl.glPointSize(size)
            set_depthrange(0.0, 0.997, points)
            bgl.glBegin(bgl.GL_POINTS)
            for coord in points: bgl.glVertex3f(*coord)
            bgl.glEnd()
            bgl.glPointSize(1.0)
        
        def freeze_color(c):
            return (
                c[0] * 0.5 + color_frozen[0] * 0.5,
                c[1] * 0.5 + color_frozen[1] * 0.5,
                c[2] * 0.5 + color_frozen[2] * 0.5,
                c[3])


        ### Existing Geometry ###
        opts = {
            'poly color': (color_frozen[0], color_frozen[1], color_frozen[2], 0.20),
            'poly depth': (0, 0.999),
            'poly mirror color': (color_mirror[0], color_mirror[1], color_mirror[2], color_mirror[3]),
            'poly mirror depth': (0, 0.999),
            
            'line color': (color_frozen[0], color_frozen[1], color_frozen[2], 1.00),
            'line depth': (0, 0.997),
            'line mirror color': (color_mirror[0], color_mirror[1], color_mirror[2], color_mirror[3]),
            'line mirror depth': (0, 0.997),
            'line mirror stipple': True,
            
            'mirror x': self.settings.symmetry_plane == 'x',
        }
        self.tar_bmeshrender.draw(opts=opts)

        ### Patches ###
        for gpatch in self.polystrips.gpatches:
            if gpatch == self.act_gpatch:
                color_border = (color_active[0], color_active[1], color_active[2], 0.50)
                color_fill = (color_active[0], color_active[1], color_active[2], 0.20)
            else:
                color_border = (color_inactive[0], color_inactive[1], color_inactive[2], 0.50)
                color_fill = (color_inactive[0], color_inactive[1], color_inactive[2], 0.10)
            if gpatch.is_frozen() and gpatch == self.act_gpatch:
                color_border = (color_frozen[0], color_frozen[1], color_frozen[2], 1.00)
                color_fill   = (color_active[0], color_active[1], color_active[2], 0.20)
            elif gpatch.is_frozen():
                color_border = (color_frozen[0], color_frozen[1], color_frozen[2], 1.00)
                color_fill   = (color_frozen[0], color_frozen[1], color_frozen[2], 0.20)
            if gpatch.count_error and gpatch == self.act_gpatch:
                color_border = (color_warning[0], color_warning[1], color_warning[2], 0.50)
                color_fill   = (color_active[0], color_active[1], color_active[2], 0.20)
            elif gpatch.count_error:
                color_border = (color_warning[0], color_warning[1], color_warning[2], 0.50)
                color_fill   = (color_warning[0], color_warning[1], color_warning[2], 0.10)
            
            draw3d_quads(context, gpatch.iter_segments(view_loc), color_fill, vector_mirror_0)
            draw3d_closed_polylines(context, gpatch.iter_segments(view_loc), color_border, 1, "GL_LINE_STIPPLE", vector_mirror_0)
            draw3d_points(context, gpatch.iter_pts(view_loc), color_border, 3, vector_mirror_0)
            if settings.symmetry_plane == 'x':
                draw3d_quads(context, gpatch.iter_segments(view_loc_x), color_mirror, vector_mirror_x)
                draw3d_closed_polylines(context, gpatch.iter_segments(view_loc_x), color_mirror, 1, "GL_LINE_STIPPLE", vector_mirror_x)
                #draw3d_points(context, gpatch.iter_pts(view_loc_x), color_border, 3, vector_mirror_x)
            

        ### Edges ###
        for gedge in self.polystrips.gedges:
            # Color active strip
            if gedge == self.act_gedge:
                color_border = (color_active[0], color_active[1], color_active[2], 1.00)
                color_fill   = (color_active[0], color_active[1], color_active[2], 0.20)
            # Color selected strips
            elif gedge in self.sel_gedges:
                color_border = (color_selection[0], color_selection[1], color_selection[2], 0.75)
                color_fill   = (color_selection[0], color_selection[1], color_selection[2], 0.20)
            # Color unselected strips
            else:
                color_border = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
                color_fill   = (color_inactive[0], color_inactive[1], color_inactive[2], 0.20)
            
            if gedge.is_frozen() and gedge in self.sel_gedges:
                color_border = (color_frozen[0], color_frozen[1], color_frozen[2], 1.00)
                color_fill   = (color_active[0], color_active[1], color_active[2], 0.20)
            elif gedge.is_frozen():
                color_border = (color_frozen[0], color_frozen[1], color_frozen[2], 1.00)
                color_fill   = (color_frozen[0], color_frozen[1], color_frozen[2], 0.20)
            
            draw3d_quads(context, gedge.iter_segments(view_loc), color_fill, vector_mirror_0)
            draw3d_closed_polylines(context, gedge.iter_segments(view_loc), color_border, 1, "GL_LINE_STIPPLE", vector_mirror_0)
            if settings.symmetry_plane == 'x':
                draw3d_quads(context, gedge.iter_segments(view_loc_x), color_mirror, vector_mirror_x)
                draw3d_closed_polylines(context, gedge.iter_segments(view_loc_x), color_mirror, 1, "GL_LINE_STIPPLE", vector_mirror_x)

            if settings.debug >= 2:
                # draw bezier
                p0,p1,p2,p3 = gedge.get_snappositions() #gvert0.snap_pos, gedge.gvert1.snap_pos, gedge.gvert2.snap_pos, gedge.gvert3.snap_pos
                n0,n1,n2,n3 = gedge.get_snapnormals()
                r0,r1,r2,r3 = gedge.get_radii()
                p1 = p1 + (n1 * (r0 * max(0.0, (1.0 - n0.dot(n3)) + (1.0 - n0.dot(n1))) ))
                p2 = p2 + (n2 * (r3 * max(0.0, (1.0 - n0.dot(n3)) + (1.0 - n3.dot(n2))) ))
                p3d = [cubic_bezier_blend_t(p0,p1,p2,p3,t/16.0) for t in range(17)]
                draw3d_polyline(context, p3d, (1,1,1,0.5),1, "GL_LINE_STIPPLE", vector_mirror_0)
        
        if settings.debug >= 2:
            for gp in self.polystrips.gpatches:
                for rev,gedgeseries in zip(gp.rev, gp.gedgeseries):
                    for revge,ge in zip(gedgeseries.rev, gedgeseries.gedges):
                        color = (0.25,0.5,0.25,0.9) if not revge else (0.5,0.25,0.25,0.9)
                        draw3d_arrow(context, ge.gvert0.snap_pos, ge.gvert3.snap_pos, ge.gvert0.snap_norm, color, 2, '')
                    color = (0.5,1.0,0.5,0.5) if not rev else (1,0.5,0.5,0.5)
                    draw3d_arrow(context, gedgeseries.gvert0.snap_pos, gedgeseries.gvert3.snap_pos, gedgeseries.gvert0.snap_norm, color, 2, '')

        ### Verts ###
        for gv in self.polystrips.gverts:
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
            if gv.is_frozen() and is_active :
                color_border = (color_frozen[0], color_frozen[1], color_frozen[2], 1.00)
                color_fill   = (color_active[0], color_active[1], color_active[2], 0.20)
            elif gv.is_frozen():
                color_border = (color_frozen[0], color_frozen[1], color_frozen[2], 1.00)
                color_fill   = (color_frozen[0], color_frozen[1], color_frozen[2], 0.20)

            p3d = [p0,p1,p2,p3,p0]
            if gv.is_visible(r3d):
                draw3d_quads(context, [[p0,p1,p2,p3]], color_fill, vector_mirror_0)
                draw3d_polyline(context, p3d, color_border, 1, "GL_LINE_STIPPLE", vector_mirror_0)
            if settings.symmetry_plane == 'x' and gv.is_visible(r3d, mirror_x=True):
                draw3d_quads(context, [[p0,p1,p2,p3]], color_mirror, vector_mirror_x)
                draw3d_polyline(context, p3d, color_mirror, 1, "GL_LINE_STIPPLE", vector_mirror_x)
            
            if settings.debug >= 2:
                l = 0.1
                sp,sn,sx,sy = gv.snap_pos,gv.snap_norm,gv.snap_tanx,gv.snap_tany
                draw3d_polyline(context, [sp,sp+sn*l], (0,0,1,0.5), 1, "", vector_mirror_0)
                draw3d_polyline(context, [sp,sp+sx*l], (1,0,0,0.5), 1, "", vector_mirror_0)
                draw3d_polyline(context, [sp,sp+sy*l], (0,1,0,0.5), 1, "", vector_mirror_0)

        # Draw inner gvert handles (dots) on each gedge
        p3d = [gvert.position for gvert in self.polystrips.gverts if not gvert.is_unconnected() and gvert.is_visible(r3d)]
        # color_handle = (color_active[0], color_active[1], color_active[2], 1.00)
        draw3d_points(context, p3d, color_handle, 4, vector_mirror_0)

        ### Vert Handles ###
        if self.act_gvert:
            color_handle = (color_active[0], color_active[1], color_active[2], 1.00)
            gv = self.act_gvert
            p0 = gv.position
            draw3d_points(context, [p0], color_handle, 8, vector_mirror_0)
            
            if gv.is_inner():
                # Draw inner handle when selected
                p1 = gv.gedge_inner.get_outer_gvert_at(gv).position
                draw3d_polyline(context, [p0,p1], color_handle, 2, "GL_LINE_SMOOTH", vector_mirror_0)
            else:
                # Draw both handles when gvert is selected
                p3d = [ge.get_inner_gvert_at(gv).position for ge in gv.get_gedges_notnone() if not ge.is_zippered() and not ge.is_frozen()]
                draw3d_points(context, p3d, color_handle, 8, vector_mirror_0)
                # Draw connecting line between handles
                for p1 in p3d:
                    draw3d_polyline(context, [p0,p1], color_handle, 2, "GL_LINE_SMOOTH", vector_mirror_0)

        # Draw gvert handles on active gedge
        if self.act_gedge and not self.act_gedge.is_frozen():
            color_handle = (color_active[0], color_active[1], color_active[2], 1.00)
            ge = self.act_gedge
            if self.act_gedge.is_zippered():
                p3d = [ge.gvert0.position, ge.gvert3.position]
                draw3d_points(context, p3d, color_handle, 8, vector_mirror_0)
            else:
                p3d = [gv.position for gv in ge.gverts()]
                draw3d_points(context, p3d, color_handle, 8, vector_mirror_0)
                draw3d_polyline(context, [p3d[0], p3d[1]], color_handle, 2, "GL_LINE_SMOOTH", vector_mirror_0)
                draw3d_polyline(context, [p3d[2], p3d[3]], color_handle, 2, "GL_LINE_SMOOTH", vector_mirror_0)
                if False:
                    # draw each normal of each gvert
                    for p,n in zip(p3d,[gv.snap_norm for gv in ge.gverts()]):
                        draw3d_polyline(context, [p,p+n*0.1], color_handle, 1, "GL_LINE_SMOOTH", vector_mirror_0)
        
        if self.hov_gvert:  #TODO, hover color
            color_border = (color_selection[0], color_selection[1], color_selection[2], 1.00)
            color_fill   = (color_selection[0], color_selection[1], color_selection[2], 0.20)
            
            gv = self.hov_gvert
            p0,p1,p2,p3 = gv.get_corners()
            p3d = [p0,p1,p2,p3,p0]
            draw3d_quad(context, [p0,p1,p2,p3], color_fill, vector_mirror_0)
            draw3d_polyline(context, p3d, color_border, 1, "GL_LINE_STIPPLE", vector_mirror_0)
            

        bgl.glLineWidth(1)
        bgl.glDepthRange(0.0, 1.0)
    

    def draw_2D(self, context):
        settings = common_utilities.get_settings()
        region,r3d = context.region,context.space_data.region_3d
        mx = self.mx
        mxnorm = matrix_normal(mx)
        
        color_inactive = settings.theme_colors_mesh[settings.theme]
        color_selection = settings.theme_colors_selection[settings.theme]
        color_active = settings.theme_colors_active[settings.theme]

        color_frozen = settings.theme_colors_frozen[settings.theme]
        color_warning = settings.theme_colors_warning[settings.theme]

        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        color_handle = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
        color_border = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
        color_fill = (color_inactive[0], color_inactive[1], color_inactive[2], 0.20)
        

        if self.fsm_mode == 'sketch' and self.sketch:
            # Draw smoothing line (end of sketch to current mouse position)
            common_drawing_px.draw_polyline_from_points(context, [self.sketch_curpos, self.sketch[-1][0]], color_active, 1, "GL_LINE_SMOOTH")

            # Draw sketching stroke
            common_drawing_px.draw_polyline_from_points(context, [co[0] for co in self.sketch], color_selection, 2, "GL_LINE_STIPPLE")

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
                #hit_p3d = mx * hit_p3d
                #hit_norm = mxnorm * hit_norm
                common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius, (1,1,1,.5))

            if self.fsm_mode == 'sketch' and self.sketch:
                ray,hit = common_utilities.ray_cast_region2d_bvh(region, r3d, self.sketch[0][0], mesh_cache['bvh'],self.mx, settings)
                hit_p3d,hit_norm,hit_idx = hit
                if hit_idx != None:
                    #hit_p3d = mx * hit_p3d
                    #hit_norm = mxnorm * hit_norm
                    common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius, (1,1,1,.5))

        if self.hover_ed and False:  #EXTEND  to display hoverable edges
            color = (color_selection[0], color_selection[1], color_selection[2], 1.00)
            common_drawing_px.draw_bmedge(context, self.hover_ed, self.dest_obj.matrix_world, 2, color)

        if self.act_gedge:
            if settings.show_segment_count:
                bgl.glColor4f(*color_active)
                self.draw_gedge_info(self.act_gedge, context)
        
        if self.act_gpatch:
            if settings.show_segment_count:
                bgl.glColor4f(*color_active)
                self.draw_gpatch_info(self.act_gpatch, context)
        
        if True:
            txt = 'v:%d e:%d s:%d p:%d' % (len(self.polystrips.gverts), len(self.polystrips.gedges), len(self.polystrips.gedgeseries), len(self.polystrips.gpatches))
            txt_width, txt_height = blf.dimensions(0, txt)
            
            bgl.glEnable(bgl.GL_BLEND)
            
            bgl.glColor4f(0,0,0,0.8)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(0, 0)
            bgl.glVertex2f(10+txt_width, 0)
            bgl.glVertex2f(10+txt_width, 10+txt_height)
            bgl.glVertex2f(0, 10+txt_height)
            bgl.glEnd()
            
            bgl.glColor4f(1,1,1,1)
            blf.position(0, 5, 5, 0)
            blf.draw(0, txt)
        
