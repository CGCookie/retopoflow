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
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from mathutils import Vector, Matrix
from .profiler import profiler
from .debug import dprint
from .maths import (
    Point, Direction, Normal, Frame,
    Point2D, Vec2D, Direction2D,
    Ray, XForm, BBox, Plane
)



def selection_mouse():
    select_type = bpy.context.user_preferences.inputs.select_mouse
    return ['%sMOUSE' % select_type, 'SHIFT+%sMOUSE' % select_type]

def get_settings():
    if not hasattr(get_settings, 'settings'):
        addons = bpy.context.user_preferences.addons
        folderpath = os.path.dirname(os.path.abspath(__file__))
        while folderpath:
            folderpath,foldername = os.path.split(folderpath)
            if foldername in {'lib','addons'}: continue
            if foldername in addons: break
        else:
            assert False, 'Could not find non-"lib" folder'
        if not addons[foldername].preferences: return None
        get_settings.settings = addons[foldername].preferences
    return get_settings.settings

def get_dpi():
    system_preferences = bpy.context.user_preferences.system
    factor = getattr(system_preferences, "pixel_size", 1)
    return int(system_preferences.dpi * factor)

def get_dpi_factor():
    return get_dpi() / 72

def blender_version():
    major,minor,rev = bpy.app.version
    # '%03d.%03d.%03d' % (major, minor, rev)
    return '%d.%02d' % (major,minor)


def iter_pairs(items, wrap, repeat=False):
    if not items: return
    while True:
        for i0,i1 in zip(items[:-1],items[1:]): yield i0,i1
        if wrap: yield items[-1],items[0]
        if not repeat: return

def rotate_cycle(cycle, offset):
    l = len(cycle)
    return [cycle[(l + ((i - offset) % l)) % l] for i in range(l)]

def hash_cycle(cycle):
    l = len(cycle)
    h = [hash(v) for v in cycle]
    m = min(h)
    mi = h.index(m)
    h = rotate_cycle(h, -mi)
    if h[1] > h[-1]:
       h.reverse()
       h = rotate_cycle(h, 1)
    return ' '.join(str(c) for c in h)

def max_index(vals, key=None):
    if not key: return max(enumerate(vals), key=lambda ival:ival[1])[0]
    return max(enumerate(vals), key=lambda ival:key(ival[1]))[0]

def min_index(vals, key=None):
    if not key: return min(enumerate(vals), key=lambda ival:ival[1])[0]
    return min(enumerate(vals), key=lambda ival:key(ival[1]))[0]


def shorten_floats(s):
    # reduces number of digits (for float) found in a string
    # useful for reducing noise of printing out a Vector, Buffer, Matrix, etc.
    s = re.sub(r'(?P<neg>-?)(?P<d0>\d)\.(?P<d1>\d)\d\d+e-02', r'\g<neg>0.0\g<d0>\g<d1>', s)
    s = re.sub(r'(?P<neg>-?)(?P<d0>\d)\.\d\d\d+e-03', r'\g<neg>0.00\g<d0>', s)
    s = re.sub(r'-?\d\.\d\d\d+e-0[4-9]', r'0.000', s)
    s = re.sub(r'-?\d\.\d\d\d+e-[1-9]\d', r'0.000', s)
    s = re.sub(r'(?P<digs>\d\.\d\d\d)\d+', r'\g<digs>', s)
    return s


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

def show_blender_message(message, title="Message", icon="INFO", wrap=80):
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




@profiler.profile
def hash_object(obj:bpy.types.Object):
    if obj is None: return None
    pr = profiler.start('computing hash on object')
    assert type(obj) is bpy.types.Object, "Only call hash_object on mesh objects!"
    assert type(obj.data) is bpy.types.Mesh, "Only call hash_object on mesh objects!"
    # get object data to act as a hash
    me = obj.data
    counts = (len(me.vertices), len(me.edges), len(me.polygons), len(obj.modifiers))
    if me.vertices:
        bbox   = (tuple(min(v.co for v in me.vertices)), tuple(max(v.co for v in me.vertices)))
    else:
        bbox = (None, None)
    vsum   = tuple(sum((v.co for v in me.vertices), Vector((0,0,0))))
    xform  = tuple(e for l in obj.matrix_world for e in l)
    mods = []
    for mod in obj.modifiers:
        if mod.type == 'SUBSURF':
            mods += [('SUBSURF', mod.levels)]
        elif mod.type == 'DECIMATE':
            mods += [('DECIMATE', mod.ratio)]
        else:
            mods += [(mod.type)]
    hashed = (counts, bbox, vsum, xform, hash(obj), str(mods))      # ob.name???
    pr.done()
    return hashed

@profiler.profile
def hash_bmesh(bme:BMesh):
    if bme is None: return None
    pr = profiler.start('computing hash on bmesh')
    assert type(bme) is BMesh, 'Only call hash_bmesh on BMesh objects!'
    counts = (len(bme.verts), len(bme.edges), len(bme.faces))
    bbox   = BBox(from_bmverts=bme.verts)
    vsum   = tuple(sum((v.co for v in bme.verts), Vector((0,0,0))))
    hashed = (counts, tuple(bbox.min) if bbox.min else None, tuple(bbox.max) if bbox.max else None, vsum)
    pr.done()
    return hashed

class UniqueCounter():
    __counter = 0
    @staticmethod
    def next():
        UniqueCounter.__counter += 1
        return UniqueCounter.__counter
