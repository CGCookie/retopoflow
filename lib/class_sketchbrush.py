'''
Copyright (C) 2014 CG Cookie
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

# Add the current __file__ path to the search path
import sys, os

import math
import copy
import time
import bpy, bmesh, blf, bgl
from bpy.props import EnumProperty, StringProperty,BoolProperty, IntProperty, FloatVectorProperty, FloatProperty
from bpy.types import Operator, AddonPreferences
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d
from mathutils import Vector
from mathutils.geometry import intersect_line_plane, intersect_point_line

from .common_utilities import simple_circle, ray_cast_region2d_bvh, ray_cast_world_size_bvh
from . import common_drawing_px


class SketchBrush(object):
    def __init__(self,context,settings, x,y,pixel_radius, bvh, mx, max_width, n_samples = 15):
        
        self.settings = settings  #should be input from user prefs
        
        self.mx = mx
        self.bvh = bvh
        self.pxl_rad = pixel_radius
        self.world_width = None
        self.max_width = max_width
        self.n_sampl = n_samples
        
        self.x = x
        self.y = y
        
        self.init_x = x
        self.init_y = y
        
        self.mouse_circle  = []
        self.preview_circle = []
        self.sample_points = []
        self.world_sample_points = []
        
        self.right_handed = True
        self.screen_hand_reverse = False
        

    def update_mouse_move_hover(self,context, mouse_x, mouse_y):
        #update the location
        self.x = mouse_x
        self.y = mouse_y
        
        #don't think i need this
        self.init_x = self.x
        self.init_y = self.y
        
    def make_circles(self):
        self.mouse_circle = simple_circle(self.x, self.y, self.pxl_rad, 20)
        self.mouse_circle.append(self.mouse_circle[0])
        self.sample_points = simple_circle(self.x, self.y, self.pxl_rad, self.n_sampl)
        
    def get_brush_world_size(self,context):
        region = context.region  
        rv3d = context.space_data.region_3d
        center = (self.x,self.y)        
        vec, center_ray = ray_cast_region2d_bvh(region, rv3d, center, self.bvh, self.mx, self.settings)
        vec.normalize()
        self.world_sample_points = []
        
        if center_ray[2] != None:
            w = ray_cast_world_size_bvh(region, rv3d, center, self.pxl_rad, self.bvh, self.mx, self.settings)
            self.world_width = w if w and w < float('inf') else self.max_width
            #print(w)
        else:
            #print('no hit')
            pass
           
    def brush_pix_size_init(self,context,x,y):
        
        if self.right_handed:
            new_x = self.x + self.pxl_rad
            if new_x > context.region.width:
                new_x = self.x - self.pxl_rad
                self.screen_hand_reverse = True
        else:
            new_x = self.x - self.pxl_rad
            if new_x < 0:
                new_x = self.x + self.pxl_rad
                self.screen_hand_reverse = True

        #NOTE.  Widget coordinates are in area space.
        #cursor warp takes coordinates in window space!
        #need to check that this works with t panel, n panel etc.
        context.window.cursor_warp(context.region.x + new_x, context.region.y + self.y)
        
        
    def brush_pix_size_interact(self,mouse_x,mouse_y, precise = False):
        #this handles right handedness and reflecting for screen
        side_factor = (-1 + 2 * self.right_handed) * (1 - 2 * self.screen_hand_reverse)
        
        #this will always be the corect sign wrt to change in radius
        rad_diff = side_factor * (mouse_x - (self.init_x + side_factor * self.pxl_rad))
        if precise:
            rad_diff *= .1
            
        if rad_diff < 0:
            rad_diff =  self.pxl_rad*(math.exp(rad_diff/self.pxl_rad) - 1)

        self.new_rad = self.pxl_rad + rad_diff    
        self.preview_circle = simple_circle(self.x, self.y, self.new_rad, 20)
        self.preview_circle.append(self.preview_circle[0])
        
        
    def brush_pix_size_confirm(self, context):
        if self.new_rad:
            self.pxl_rad = self.new_rad
            self.new_rad = None
            self.screen_hand_reverse = False
            self.preview_circle = []
            
            self.make_circles()
            self.get_brush_world_size(context)
            
            #put the mouse back
            context.window.cursor_warp(context.region.x + self.x, context.region.y + self.y)
            
    def brush_pix_size_cancel(self, context):
        self.preview_circle = []
        self.new_rad = None
        self.screen_hand_reverse = False
        context.window.cursor_warp(context.region.x + self.init_x, context.region.y + self.init_y)
    
    def brush_pix_size_pressure(self, mouse_x, mouse_y, pressure):
        'assume pressure from -1 to 1 with 0 being the midpoint'
        
        print('not implemented')
    
    def draw(self, context, color=(.7,.1,.8,.8), linewidth=2, color_size=(.8,.8,.8,.8)):
        #TODO color and size
        
        #draw the circle
        if self.mouse_circle != []:
            common_drawing_px.draw_polyline_from_points(context, self.mouse_circle, color, linewidth, "GL_LINE_SMOOTH")
        
        #draw the sample points which are raycast
        if self.world_sample_points != []:
            #TODO color and size
            #common_drawing_px.draw_3d_points(context, self.world_sample_points, (1,1,1,1), 3)
            pass
    
        #draw the preview circle if changing brush size
        if self.preview_circle != []:
            common_drawing_px.draw_polyline_from_points(context, self.preview_circle, color_size, linewidth, "GL_LINE_SMOOTH")

