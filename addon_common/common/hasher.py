'''
Copyright (C) 2023 CG Cookie
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

from __future__ import annotations
import time
from struct import pack
import hashlib
from collections.abc import Iterable

import bpy
from bmesh.types import BMesh
from mathutils import Vector, Matrix

from .maths import (
    Point, Direction, Normal, Frame,
    Point2D, Vec2D, Direction2D,
    Ray, XForm, BBox, Plane,
    Color
)


known_hash_types = {
    str, type(None), dict
}

class Hasher:
    _hasher : hashlib._Hash
    _digest : str | None

    def __init__(self, *args: ...):
        self._hasher = hashlib.md5()
        self._digest = None
        self.add(*args)

    def __iadd__(self, other : ...):
        self.add(other)
        return self

    def __str__(self) -> str:
        return f'<Hasher {self.get_hash()}>'

    def __hash__(self) -> int:
        return hash(self.get_hash())

    def add(self, *args : ...):
        self._digest = None
        for arg in args:
            match arg:
                case Vector():
                    self._hasher.update(bytes(f'Vector {len(arg)}', 'utf8'))
                    self.add(*arg)
                case Matrix():
                    l0 = len(arg)
                    l1 = len(arg[0])
                    self._hasher.update(bytes(f'Matrix {l0} {l1}', 'utf8'))
                    self.add_list([v for r in arg for v in r])
                case Color():
                        self._hasher.update(bytes(f'Color', 'utf8'))
                        self.add_list([arg.r, arg.g, arg.b, arg.a])
                case list():
                    self._hasher.update(bytes(f'list {len(arg)}', 'utf8'))
                    self.add_list(arg)
                case tuple():
                    self._hasher.update(bytes(f'tuple {len(arg)}', 'utf8'))
                    self.add_list(arg)
                case set():
                    self._hasher.update(bytes(f'set {len(arg)}', 'utf8'))
                    self.add_list(arg)
                case int():
                    self._hasher.update(pack('i', arg))
                case float():
                    self._hasher.update(pack('f', arg))
                case bool():
                    self._hasher.update(pack('b', arg))
                case str() | None | dict():
                    self._hasher.update(bytes(str(arg), 'utf8'))
                case _:
                    # unknown type.  still works, but might want to know about it
                    # to handle special cases
                    # print(f'Hasher.add: {arg} {t}')
                    self._hasher.update(bytes(str(arg), 'utf8'))

    def add_list(self, args : Iterable[...]):
        for arg in args:
            self.add(arg)

    def get_hash(self) -> str:
        if self._digest is None:
            self._digest = self._hasher.hexdigest()
        return self._digest

    def __eq__(self, other):
        if type(other) is not Hasher: return False
        return self.get_hash() == other.get_hash()
    def __ne__(self, other):
        return not (self == other)

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


def hash_object(obj:bpy.types.Object):
    if obj is None: return None
    assert type(obj) is bpy.types.Object, "Only call hash_object on mesh objects!"
    assert type(obj.data) is bpy.types.Mesh, "Only call hash_object on mesh objects!"
    # print(f'RetopoFlow: Hashing object {obj.name}...')
    t = time.time()
    # get object data to act as a hash
    me = obj.data
    counts = (len(me.vertices), len(me.edges), len(me.polygons), len(obj.modifiers))
    bbox = obj.bound_box
    bbox = (
        (min(c[0] for c in bbox), min(c[1] for c in bbox), min(c[2] for c in bbox)),
        (max(c[0] for c in bbox), max(c[1] for c in bbox), max(c[2] for c in bbox)),
    )
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
    # print(f'  hash: {hashed}')
    # print(f'  time: {time.time() - t}')
    return hashed

def hash_bmesh(bme:BMesh):
    if bme is None: return None
    assert type(bme) is BMesh, 'Only call hash_bmesh on BMesh objects!'

    # bme.verts.ensure_lookup_table()
    # bme.edges.ensure_lookup_table()
    # bme.faces.ensure_lookup_table()
    # return Hasher(
    #     [list(v.co) + list(v.normal) + [v.select] for v in bme.verts],
    #     [[v.index for v in e.verts] + [e.select] for e in bme.edges],
    #     [[v.index for v in f.verts] + [f.select] for f in bme.faces],
    #     )

    counts = (len(bme.verts), len(bme.edges), len(bme.faces))
    bbox   = BBox(from_bmverts=bme.verts)
    vsum   = tuple(sum((v.co for v in bme.verts), Vector((0,0,0))))
    hashed = (counts, tuple(bbox.min) if bbox.min else None, tuple(bbox.max) if bbox.max else None, vsum)
    return hashed
