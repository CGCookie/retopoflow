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

from . import common_utilities
from . import common_drawing


class TextBox(object):
    
    def __init__(self,context,x,y,width,height,border,message):
        
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.border = border
        self.spacer = 5
        
        self.text_size = 12
        self.text_dpi = 72
        blf.size(0, self.text_size, self.text_dpi)
        self.line_height = blf.dimensions(0, 'A')[1]
        self.raw_text = message
        self.text_lines = []
        self.format_and_wrap_text()
    
    def screen_boudaries(self):
        print('to be done later')
    
    def snap_to_coner(self,context,corner = [1,1]):
        '''
        '''
        
         
    def fit_box_height_to_text_lines(self):
        '''
        will make box width match longest line
        '''
        self.height = len(self.text_lines)*(self.line_height+self.spacer)+2*self.border
        
    def format_and_wrap_text(self):
        '''
        '''
        self.text_lines = []
        #TODO text size settings?
        useful_width = self.width - 2 * self.border
        spc_size = blf.dimensions(0,' ')
        spc_width = spc_size[0]
        
        dim_raw = blf.dimensions(0,self.raw_text)
        if dim_raw[0] < useful_width:
            #TODO fill in the relevant data
            return
        
        #clean up line seps, double spaces
        self.raw_text = self.raw_text.replace('\r','')
        #self.raw_text.replace('  ',' ')
        
        def crop_word(word, width):
            '''
            word will be cropped to less than width
            '''
            ltr_indx = 0
            wrd_width = 0
            while ltr_indx < len(word) and wrd_width < width:
                wrd_width += blf.dimensions(0,word[ltr_indx])[0]
                ltr_indx += 1
                
            return word[0:ltr_indx - 1]  #TODO, check indexing for slice op
        
        def wrap_line(txt_line,width):
            '''
            takes a string, returns a list of strings, corresponding to wrapped
            text of the specified pixel width, given current BLF settings
            '''
            if blf.dimensions(0,txt_line)[0] < useful_width:
                #TODO fil
                return [txt_line]
            
            txt = txt_line  #TODO Clean this
            words = txt.split(' ')
            new_lines = []
            current_line = []
            cur_line_len = 0
            for i,wrd in enumerate(words):
                
                word_width = blf.dimensions(0, wrd)[0]
                if word_width >= useful_width:
                    crp_wrd = crop_word(wrd, useful_width)
                        
                    if len(current_line):
                        new_lines.append(' '.join(current_line))
                    new_lines.append(crp_wrd)
                    current_line = []
                    cur_line_len = 0
                    continue
                
                if cur_line_len + word_width <= useful_width:
                    current_line.append(wrd)
                    cur_line_len += word_width
                    if i < len(words)-1:
                        cur_line_len += spc_size[0]
                else:
                    new_lines.append(' '.join(current_line))
                    current_line = [wrd]
                    cur_line_len = word_width
                    if i < len(words)-1:
                        cur_line_len += spc_size[0]

                if i == len(words) - 1 and len(current_line):
                    new_lines.append(' '.join(current_line))
                                     
            return new_lines          
        
        lines = self.raw_text.split('\n')
        for ln in lines:
            self.text_lines.extend(wrap_line(ln, useful_width))
        

        self.fit_box_height_to_text_lines()
        return
    
    def draw(self):
        txt_color = (.9,.9,.9,1)
        txt_color_no_poll = (.5, .5, .5, 1)
        
        bg_color = (.1, .1, .1, .5)
        search_color = (.2, .2, .2, 1)
        border_color = (.05, .05, .05, 1)
        highlight_color = (0,.3, 1, .8)
        
        left = self.x - self.width/2
        right = left + self.width
        bottom = self.y - self.height
        top = self.y
        
        left_text = left + self.border
        bottom_text = bottom + self.border
        
        #draw the whole menu bacground
        outline = common_drawing.round_box(left, bottom, left +self.width, bottom + self.height, (self.line_height + 2 * self.spacer)/6)
        common_drawing.draw_outline_or_region('GL_POLYGON', outline, bg_color)
        common_drawing.draw_outline_or_region('GL_LINE_LOOP', outline, border_color)
        
        blf.size(0, self.text_size, self.text_dpi)
        
        for i, line in enumerate(self.text_lines):
            
            txt_x = left_text + self.spacer
            txt_y = top - self.border - (i+1) * (self.line_height + self.spacer)
                
            blf.position(0,txt_x, txt_y, 0)
            bgl.glColor4f(*txt_color)
            blf.draw(0, line)
            
            
class SketchBrush(object):
    def __init__(self,context,settings, x,y,pixel_radius, ob, n_samples = 15):
        
        self.settings = settings  #should be input from user prefs
        
        self.ob = ob
        self.pxl_rad = pixel_radius
        self.world_width = None
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
        self.mouse_circle = common_utilities.simple_circle(self.x, self.y, self.pxl_rad, 20)
        self.mouse_circle.append(self.mouse_circle[0])
        self.sample_points = common_utilities.simple_circle(self.x, self.y, self.pxl_rad, self.n_sampl)
        
    def get_brush_world_size(self,context):
        region = context.region  
        rv3d = context.space_data.region_3d
        center = (self.x,self.y)
        wrld_mx = self.ob.matrix_world
        
        vec, center_ray = common_utilities.ray_cast_region2d(region, rv3d, center, self.ob, self.settings)
        vec.normalize()
        widths = []
        self.world_sample_points = []
        
        if center_ray[2] != -1:
            w = common_utilities.ray_cast_world_size(region, rv3d, center, self.pxl_rad, self.ob, self.settings)
            self.world_width = w if w and w < float('inf') else self.ob.dimensions.length
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
        self.preview_circle = common_utilities.simple_circle(self.x, self.y, self.new_rad, 20)
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
            common_drawing.draw_polyline_from_points(context, self.mouse_circle, color, linewidth, "GL_LINE_SMOOTH")
        
        #draw the sample points which are raycast
        if self.world_sample_points != []:
            #TODO color and size
            #common_drawing.draw_3d_points(context, self.world_sample_points, (1,1,1,1), 3)
            pass
    
        #draw the preview circle if changing brush size
        if self.preview_circle != []:
            common_drawing.draw_polyline_from_points(context, self.preview_circle, color_size, linewidth, "GL_LINE_SMOOTH")
            
