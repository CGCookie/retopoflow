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

import bpy, blf, bgl
from . import common_drawing_px
           

class TextBox(object):
    
    def __init__(self,context,x,y,width,height,border, margin, message):
        
        self.x = x #middle of text box
        self.y = y #top of text box
        self.def_width = width
        self.def_height = height
        self.hang_indent = '-'
        
        self.width = width
        self.height = height
        self.border = border
        self.margin = margin
        self.spacer = 7  # pixels between text lines
        self.is_collapsed = False
        self.is_hovered = False
        self.collapsed_msg = "Click for Help"

        self.text_size = 12
        self.text_dpi = context.user_preferences.system.dpi
        blf.size(0, self.text_size, self.text_dpi)
        self.line_height = self.txt_height('A')
        self.raw_text = message
        self.text_lines = []
        self.format_and_wrap_text()
        
        #print('>>> dpi: %f' % self.text_dpi)
        self.window_dims = (context.window.width, context.window.height)
        
    def hover(self,mouse_x, mouse_y):
        regOverlap = bpy.context.user_preferences.system.use_region_overlap
        if regOverlap == True:
            tPan = self.discover_panel_width_and_location('TOOL_PROPS')
            nPan = self.discover_panel_width_and_location('UI')
            if tPan != 0 and nPan != 0:
                left = (self.x - self.width/2) - (nPan + tPan)
            elif tPan != 0:
                left = (self.x - self.width/2) - tPan
            elif nPan != 0:
                left = (self.x - self.width/2) - nPan
            else:
                left = self.x - self.width/2
        else:
            left = self.x - self.width/2
        right = left + self.width
        bottom = self.y - self.height
        top = self.y
        
        if mouse_x > left and mouse_x < right and mouse_y < top and mouse_y > bottom:
            self.is_hovered = True
            return True
        else:
            self.is_hovered = False
            return False
        
        
    def discover_panel_width_and_location(self, panelType):
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for reg in area.regions:
                    if reg.type == panelType:
                        if reg.width > 1:
                            if reg.x == 0:
                                return 0
                            else:
                                return reg.width
                        else:
                            return 0
                        
    def screen_boudaries(self):
        print('to be done later')

    def collapse(self):
        line_height = self.txt_height('A')
        self.is_collapsed = True
        self.width = self.txt_width(self.collapsed_msg) + 2 * self.border
        self.height = line_height + 2*self.border
        
    def uncollapse(self):
        self.is_collapsed = False
        self.width = self.def_width
        self.format_and_wrap_text()
        self.fit_box_height_to_text_lines()
        
    def snap_to_corner(self,context,corner = [1,1]):
        '''
        '''        
        self.x = self.margin + .5*self.width + corner[0]*(context.region.width - self.width - 2*self.margin)
        self.y = self.margin + self.height + corner[1]*(context.region.height - 2*self.margin - self.height)
             
    
    def txt_height(self, text):
        return blf.dimensions(0,text)[1]
    def txt_width(self, text):
        return blf.dimensions(0,text)[0]
    
    def fit_box_width_to_text_lines(self):
        '''
        shrink width of box to fit width of text
        '''
        max_width = max(self.txt_width(line) for line in self.text_lines)
        self.width = min(max_width + 2*self.border, self.width)
        
        
    def fit_box_height_to_text_lines(self):
        '''
        fit height of box to match text
        '''
        line_height = self.txt_height('A')
        line_count  = len(self.text_lines)
        self.height = line_count*(line_height + self.spacer) + 2*self.border
        
    
    def format_and_wrap_text(self):
        '''
        '''
        # remove \r characters (silly windows machines!)
        self.raw_text = self.raw_text.replace('\r','')
        
        #TODO text size settings?
        useful_width = self.width - 2 * self.border
        #print('>>> useful width = % 8.1f' % useful_width)
        
        # special case: no newlines and we fit already!
        if '\n' not in self.raw_text and self.txt_width(self.raw_text) < useful_width:
            self.text_lines = [self.raw_text]
            return
        
        def split_word(line):
            '''
            splits off first word, including any leading spaces
            '''
            if not line: return (None,None)
            sp = (line[0] == ' ')
            for i,c in enumerate(line):
                if c == ' ':
                    if not sp: return (line[:i], line[i:])
                    continue
                sp = False
            return (line,'')
        
        def wrap_line(line):
            '''
            takes a string, returns a list of strings, corresponding to wrapped
            text of the specified pixel width, given current BLF settings
            '''
            
            line = line.rstrip() # ignore right whitespace
            
            if self.txt_width(line) < useful_width:
                # no need to wrap!
                lines = [line]
                #for line in lines:
                #    print('>>> line width = % 8.1f: %s' % (self.txt_width(line), line))
                return lines
            
            lines = []
            working = ""
            while line:
                word,line = split_word(line)
                if self.txt_width(working + word) < useful_width:
                    working += word
                else:
                    # adding word is too wide!
                    # start new row
                    lines += [working]
                    working = '  ' + word.strip() # lead with exactly two spaces
            lines += [working]
            
            #for line in lines:
            #    print('>>> line width = % 8.1f: %s' % (self.txt_width(line), line))
            
            return lines
        
        self.text_lines = []
        for line in self.raw_text.split('\n'):
            self.text_lines += wrap_line(line)
        
        self.fit_box_height_to_text_lines()
        self.fit_box_width_to_text_lines()
    
    
    def draw(self):
        regOverlap = bpy.context.user_preferences.system.use_region_overlap
        
        if (bpy.context.window.width, bpy.context.window.height) != self.window_dims:
            self.snap_to_corner(bpy.context, corner = [1,1])
            self.window_dims = (bpy.context.window.width, bpy.context.window.height)
        bgcol = bpy.context.user_preferences.themes[0].user_interface.wcol_menu_item.inner
        bgR = bgcol[0]
        bgG = bgcol[1]
        bgB = bgcol[2]
        bgA = .5
        bg_color = (bgR, bgG, bgB, bgA)
        
        txtcol = bpy.context.user_preferences.themes[0].user_interface.wcol_menu_item.text
        txR = txtcol[0]
        txG = txtcol[1]
        txB = txtcol[2]
        txA = .9
        txt_color = (txR, txG, txB, txA)
        
        bordcol = bpy.context.user_preferences.themes[0].user_interface.wcol_menu_item.outline
        hover_color = bpy.context.user_preferences.themes[0].user_interface.wcol_menu_item.inner_sel
        bordR = bordcol[0]
        bordG = bordcol[1]
        bordB = bordcol[2]
        bordA = .8
        if self.is_hovered:
             border_color = (hover_color[0], hover_color[1], hover_color[2], bordA)
        else:
            border_color = (bordR, bordG, bordB, bordA)
        
        if regOverlap == True:
            tPan = self.discover_panel_width_and_location('TOOL_PROPS')
            nPan = self.discover_panel_width_and_location('UI')
            if tPan != 0 and nPan != 0:
                left = (self.x - self.width/2) - (nPan + tPan)
            elif tPan != 0:
                left = (self.x - self.width/2) - tPan
            elif nPan != 0:
                left = (self.x - self.width/2) - nPan
            else:
                left = self.x - self.width/2
        else:
            left = self.x - self.width/2
        right = left + self.width
        bottom = self.y - self.height
        top = self.y
        
        #draw the whole menu background
        line_height = self.txt_height('A')
        outline = common_drawing_px.round_box(left, bottom, left +self.width, bottom + self.height, (line_height + 2 * self.spacer)/6)
        common_drawing_px.draw_outline_or_region('GL_POLYGON', outline, bg_color)
        common_drawing_px.draw_outline_or_region('GL_LINE_LOOP', outline, border_color)
        
        dpi = bpy.context.user_preferences.system.dpi
        blf.size(0, self.text_size, dpi)
        
        if self.is_collapsed:
            txt_x = left + self.border
            txt_y = top - self.border - line_height
            blf.position(0,txt_x, txt_y, 0)
            bgl.glColor4f(*txt_color)
            blf.draw(0, self.collapsed_msg)
            return
        
        for i, line in enumerate(self.text_lines):
            
            txt_x = left + self.border
            txt_y = top - self.border - (i+1) * (line_height + self.spacer)
                
            blf.position(0,txt_x, txt_y, 0)
            bgl.glColor4f(*txt_color)
            blf.draw(0, line)
 