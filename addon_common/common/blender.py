'''
Copyright (C) 2020 CG Cookie
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
from .decorators import blender_version_wrapper

@blender_version_wrapper("<=", "2.79")
def get_preferences(ctx=None):
    return (ctx if ctx else bpy.context).user_preferences
@blender_version_wrapper(">=", "2.80")
def get_preferences(ctx=None):
    return (ctx if ctx else bpy.context).preferences

#############################################################

class ModifierWrapper_Mirror:
    '''
    normalize the mirror modifier API across 2.79 and 2.80
    '''
    @staticmethod
    def create_new(obj):
        bpy.ops.object.modifier_add(type='MIRROR')
        mod = ModifierWrapper_Mirror(obj, obj.modifiers[-1])
        mod.set_defaults()
        return mod

    @staticmethod
    def get_from_object(obj):
        for mod in obj.modifiers:
            if mod.type != 'MIRROR': continue
            return ModifierWrapper_Mirror(obj, mod)
        return None

    def __init__(self, obj, modifier):
        self._reading = True
        self.obj = obj
        self.mod = modifier
        self.read()

    @property
    def x(self):
        return 'x' in self._symmetry
    @x.setter
    def x(self, v):
        if v: self._symmetry.add('x')
        else: self._symmetry.discard('x')
        self.write()

    @property
    def y(self):
        return 'y' in self._symmetry
    @y.setter
    def y(self, v):
        if v: self._symmetry.add('y')
        else: self._symmetry.discard('y')
        self.write()

    @property
    def z(self):
        return 'z' in self._symmetry
    @z.setter
    def z(self, v):
        if v: self._symmetry.add('z')
        else: self._symmetry.discard('z')
        self.write()

    @property
    def use_clip(self):
        return self.mod.use_clip
    @use_clip.setter
    def use_clip(self, v):
        self.mod.use_clip = v

    @property
    def xyz(self):
        return set(self._symmetry)

    @property
    def symmetry_threshold(self):
        return self._symmetry_threshold
    @symmetry_threshold.setter
    def symmetry_threshold(self, v):
        self._symmetry_threshold = max(0, float(v))
        self.write()


    def enable_axis(self, axis):
        self._symmetry.add(axis)
        self.write()
    def disable_axis(self, axis):
        self._symmetry.discard(axis)
        self.write()
    def disable_all(self):
        self._symmetry.clear()
        self.write()
    def is_enabled_axis(self, axis):
        return axis in self._symmetry

    def set_defaults(self):
        self.mod.merge_threshold = 0.001
        self.mod.show_expanded = False
        self.mod.show_on_cage = True
        self.mod.use_mirror_merge = True
        self.mod.show_viewport = True
        self.disable_all()

    @blender_version_wrapper('<', '2.80')
    def read(self):
        self._reading = True
        self._symmetry = set()
        if self.mod.use_x: self._symmetry.add('x')
        if self.mod.use_y: self._symmetry.add('y')
        if self.mod.use_z: self._symmetry.add('z')
        self._symmetry_threshold = self.mod.merge_threshold
        self.show_viewport = self.mod.show_viewport
        self._reading = False
    @blender_version_wrapper('>=', '2.80')
    def read(self):
        self._reading = True
        self._symmetry = set()
        if self.mod.use_axis[0]: self._symmetry.add('x')
        if self.mod.use_axis[1]: self._symmetry.add('y')
        if self.mod.use_axis[2]: self._symmetry.add('z')
        self._symmetry_threshold = self.mod.merge_threshold
        self.show_viewport = self.mod.show_viewport
        self._reading = False

    @blender_version_wrapper('<', '2.80')
    def write(self):
        if self._reading: return
        self.mod.use_x = self.x
        self.mod.use_y = self.y
        self.mod.use_z = self.z
        self.mod.merge_threshold = self._symmetry_threshold
        self.mod.show_viewport = self.show_viewport
    @blender_version_wrapper('>=', '2.80')
    def write(self):
        if self._reading: return
        self.mod.use_axis[0] = self.x
        self.mod.use_axis[1] = self.y
        self.mod.use_axis[2] = self.z
        self.mod.merge_threshold = self._symmetry_threshold
        self.mod.show_viewport = self.show_viewport




#############################################################

@blender_version_wrapper('<', '2.80')
def matrix_vector_mult(mat, vec): return mat * vec
@blender_version_wrapper('>=', '2.80')
def matrix_vector_mult(mat, vec): return mat @ vec

@blender_version_wrapper('<', '2.80')
def quat_vector_mult(quat, vec): return quat * vec
@blender_version_wrapper('>=', '2.80')
def quat_vector_mult(quat, vec): return quat @ vec

#############################################################
# TODO: generalize these functions to be add_object, etc.

@blender_version_wrapper('<=','2.79')
def set_object_layers(o): o.layers = list(bpy.context.scene.layers)
@blender_version_wrapper('>=','2.80')
def set_object_layers(o): print('unhandled: set_object_layers')

@blender_version_wrapper('<=','2.79')
def set_object_selection(o, sel): o.select = sel
@blender_version_wrapper('>=','2.80')
def set_object_selection(o, sel): o.select_set(sel)

@blender_version_wrapper('<=','2.79')
def link_object(o): bpy.context.scene.objects.link(o)
@blender_version_wrapper('>=','2.80')
def link_object(o): bpy.context.scene.collection.objects.link(o)

@blender_version_wrapper('<=','2.79')
def set_active_object(o): bpy.context.scene.objects.active = o
@blender_version_wrapper('>=','2.80')
def set_active_object(o): bpy.context.view_layer.objects.active = o

# use this, because bpy.context might not Screen context!
# see https://docs.blender.org/api/current/bpy.context.html
def get_active_object(): return bpy.context.view_layer.objects.active

@blender_version_wrapper('<=', '2.79')
def toggle_screen_header(ctx): bpy.ops.screen.header(ctx)
@blender_version_wrapper('>=', '2.80')
def toggle_screen_header(ctx):
    space = ctx['space_data'] if type(ctx) is dict else ctx.space_data
    space.show_region_header = not space.show_region_header

@blender_version_wrapper('<=', '2.79')
def toggle_screen_toolbar(ctx):
    bpy.ops.view3d.toolshelf(ctx)
@blender_version_wrapper('>=', '2.80')
def toggle_screen_toolbar(ctx):
    space = ctx['space_data'] if type(ctx) is dict else ctx.space_data
    space.show_region_toolbar = not space.show_region_toolbar

@blender_version_wrapper('<=', '2.79')
def toggle_screen_properties(ctx):
    bpy.ops.view3d.properties(ctx)
@blender_version_wrapper('>=', '2.80')
def toggle_screen_properties(ctx):
    space = ctx['space_data'] if type(ctx) is dict else ctx.space_data
    space.show_region_ui = not space.show_region_ui

@blender_version_wrapper('<=', '2.79')
def toggle_screen_lastop(ctx):
    # Blender 2.79 does not have a last operation region
    pass
@blender_version_wrapper('>=', '2.80')
def toggle_screen_lastop(ctx):
    space = ctx['space_data'] if type(ctx) is dict else ctx.space_data
    space.show_region_hud = not space.show_region_hud


tagged_redraw_all = False
tag_reasons = set()
def tag_redraw_all(reason, only_tag=True):
    global tagged_redraw_all, tag_reasons
    tagged_redraw_all = True
    tag_reasons.add(reason)
    if not only_tag: perform_redraw_all()
def perform_redraw_all(only_area=None):
    global tagged_redraw_all, tag_reasons
    if not tagged_redraw_all: return
    # print('Redrawing:', tag_reasons)
    tag_reasons.clear()
    tagged_redraw_all = False
    if only_area:
        only_area.tag_redraw()
    else:
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                for ar in win.screen.areas:
                    ar.tag_redraw()




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
        txt.select_end_line_index = 0

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
            space.show_syntax_highlight = False
            space.top = 0
            if hide_header and area.regions[0].height != 1:
                # hide header
                toggle_screen_header({'window':win, 'region':area.regions[2], 'area':area, 'space_data':space})

def bversion(short=True):
    major,minor,rev = bpy.app.version
    bver_long = '%03d.%03d.%03d' % (major,minor,rev)
    bver_short = '%d.%02d' % (major, minor)
    return bver_short if short else bver_long
