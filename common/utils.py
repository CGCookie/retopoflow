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
from ..lib.common_utilities import dprint

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


