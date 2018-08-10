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


def show_blender_popup(message, title="Message", icon="INFO", wrap=80):
    '''
    icons: NONE, QUESTION, ERROR, CANCEL,
           TRIA_RIGHT, TRIA_DOWN, TRIA_LEFT, TRIA_UP,
           ARROW_LEFTRIGHT, PLUS,
           DISCLOSURE_TRI_DOWN, DISCLOSURE_TRI_RIGHT,
           RADIOBUT_OFF, RADIOBUT_ON,
           MENU_PANEL, BLENDER, GRIP, DOT, COLLAPSEMENU, X,
           GO_LEFT, PLUG, UI, NODE, NODE_SEL,
           FULLSCREEN, SPLITSCREEN, RIGHTARROW_THIN, BORDERMOVE,
           VIEWZOOM, ZOOMIN, ZOOMOUT, ...
    see: https://git.blender.org/gitweb/gitweb.cgi/blender.git/blob/HEAD:/source/blender/editors/include/UI_icons.h
    '''  # noqa

    if not message: return
    lines = message.splitlines()
    if wrap > 0:
        nlines = []
        for line in lines:
            spc = len(line) - len(line.lstrip())
            while len(line) > wrap:
                i = line.rfind(' ',0,wrap)
                if i == -1:
                    nlines += [line[:wrap]]
                    line = line[wrap:]
                else:
                    nlines += [line[:i]]
                    line = line[i+1:]
                if line:
                    line = ' '*spc + line
            nlines += [line]
        lines = nlines
    def draw(self,context):
        for line in lines:
            self.layout.label(line)
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)
    return

def show_error_message(message, title="Error", wrap=80):
    show_blender_popup(message, title, "ERROR", wrap)

def show_blender_text(textblock_name, hide_header=True, goto_top=True):
    if textblock_name not in bpy.data.texts:
        # no textblock to show
        return

    txt = bpy.data.texts[textblock_name]
    if goto_top:
        txt.current_line_index = 0

    # duplicate the current area then change it to a text editor
    area_dupli = bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
    win = bpy.context.window_manager.windows[-1]
    area = win.screen.areas[-1]
    area.type = 'TEXT_EDITOR'

    # load the text file into the correct space
    for space in area.spaces:
        if space.type == 'TEXT_EDITOR':
            space.text = txt
            space.show_word_wrap = True
            space.top = 0
            if hide_header and area.regions[0].height != 1:
                # hide header
                bpy.ops.screen.header({'window':win, 'region':area.regions[2], 'area':area})

def bversion():
    bversion = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])
    return bversion
