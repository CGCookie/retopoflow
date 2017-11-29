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
from ..lib.common_utilities import dprint
from ..lib.classes.profiler.profiler import profiler
from mathutils import Vector, Matrix
from ..common.maths import Point, Direction, Normal, Frame
from ..common.maths import Point2D, Vec2D, Direction2D
from ..common.maths import Ray, XForm, BBox, Plane


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
