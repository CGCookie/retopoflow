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

import re
import random
from math import sqrt, acos, cos, sin, floor, ceil, isinf, sqrt, pi, isnan, isfinite
from typing import List
from itertools import chain
from concurrent.futures import ProcessPoolExecutor

import gpu
from mathutils import Matrix, Vector, Quaternion
from bmesh.types import BMVert
from mathutils.geometry import intersect_line_plane, intersect_point_tri

from .maths import zero_threshold, BBox2D, Point2D, clamp, Vec2D, Vec, mid

from .colors import colorname_to_color
from .decorators import stats_wrapper, blender_version_wrapper
from .profiler import profiler, time_it

from ..terminal import term_printer


class SimpleVert:
    def __init__(self, co):
        self.co = co
        self.normal = Vec((0, 0, 0))
        self.is_valid = True

class SimpleEdge:
    def __init__(self, verts):
        self.verts = verts
        self.p0 = verts[0].co
        self.p1 = verts[1].co
        self.v01 = self.p1 - self.p0
        self.l = self.v01.length
        self.d01 = self.v01 / max(self.l, zero_threshold)
        self.is_valid = True
    def closest(self, p):
        v0p = p - self.p0
        d = self.d01.dot(v0p)
        return self.p0 + self.d01 * mid(d, 0, self.l)

class Accel2D:
    margin = 0.001
    DEBUG = False

    # @staticmethod
    # def simple_verts(label, lco, Point_to_Point2Ds):
    #     verts = [ SimpleVert(co) for co in lco ]
    #     return Accel2D(label, verts, [], [], Point_to_Point2Ds)

    @staticmethod
    def simple_edges(label, edges, Point_to_Point2Ds):
        edges = [ SimpleEdge(( SimpleVert(co0), SimpleVert(co1) )) for (co0, co1) in edges ]
        verts = [ co for e in edges for co in e.verts ]
        return Accel2D(label, verts, edges, [], Point_to_Point2Ds)

    def _insert_edge(self, edge):
        pts_list = zip(*[ self.Point_to_Point2Ds(v.co, v.normal) for v in edge.verts ])
        for co0, co1 in pts_list:
            (i0, j0), (i1, j1) = self.compute_ij(co0), self.compute_ij(co1)
            mini, minj, maxi, maxj = min(i0, i1), min(j0, j1), max(i0, i1), max(j0, j1)
            for i in range(mini, maxi + 1):
                for j in range(minj, maxj + 1):
                    self._put((i, j), edge)

    @profiler.function
    def __init__(self, label, verts, edges, faces, Point_to_Point2Ds):
        self.verts = list(verts) if verts else []
        self.edges = list(edges) if edges else []
        self.faces = list(faces) if faces else []
        self.Point_to_Point2Ds = Point_to_Point2Ds

        vert_type, edge_type, face_type = ( type(elems[0] if elems else None) for elems in [self.verts, self.edges, self.faces] )
        self._is_vert = lambda elem: isinstance(elem, vert_type)
        self._is_edge = lambda elem: isinstance(elem, edge_type)
        self._is_face = lambda elem: isinstance(elem, face_type)
        self.bins = {}

        # collect all involved pts so we can find bbox
        with time_it('collect', enabled=Accel2D.DEBUG):
            bbox = BBox2D()
            with time_it('collect verts', enabled=Accel2D.DEBUG):
                bbox.insert_points(pt for v in verts for pt in Point_to_Point2Ds(v.co, v.normal))
            with time_it('collect edges and faces', enabled=Accel2D.DEBUG):
                bbox.insert_points(
                    pt
                    for ef in chain(edges, faces)
                    for ef_pts in zip(*[Point_to_Point2Ds(v.co, v.normal) for v in ef.verts])
                    for pt in ef_pts
                )
        if bbox.count == 0:
            bbox.insert(Point2D((0,0)))

        tot_points = len(self.verts) + 2 * len(self.edges) + sum(len(f.verts) for f in self.faces)

        self.min = Point2D((bbox.mx - self.margin, bbox.my - self.margin))
        self.max = Point2D((bbox.Mx + self.margin, bbox.My + self.margin))
        self.size = self.max - self.min  # includes margin
        self.sizex, self.sizey = self.size
        self.minx, self.miny = self.min
        self.bin_len = ceil(sqrt(tot_points) + 0.1)

        # Accel2D.debug variables
        tot_inserted = 0
        max_spread = (1, 1, 1)

        # inserting verts
        with time_it('insert verts', enabled=Accel2D.DEBUG):
            for v in verts:
                for pt in Point_to_Point2Ds(v.co, v.normal):
                    tot_inserted += 1
                    i, j = self.compute_ij(pt)
                    self._put((i, j), v)

        # inserting edges and faces
        with time_it('insert edges and faces', enabled=Accel2D.DEBUG):
            for e in edges:
                self._insert_edge(e)
            for ef in faces:
                ef_pts_list = zip(*[Point_to_Point2Ds(v.co, v.normal) for v in ef.verts])
                for ef_pts in ef_pts_list:
                    tot_inserted += 1
                    bbox2 = BBox2D((self.compute_ij(pt) for pt in ef_pts))
                    mini, minj, maxi, maxj = int(bbox2.mx), int(bbox2.my), int(bbox2.Mx), int(bbox2.My)
                    sizei, sizej = maxi - mini + 1, maxj - minj + 1
                    if (spread := sizei*sizej) > max_spread[0]: max_spread = (spread, sizei, sizej)
                    for i in range(mini, maxi + 1):
                        for j in range(minj, maxj + 1):
                            self._put((i, j), ef)

        if Accel2D.DEBUG:
            # debug reporting
            def get_index(s, v, m, M): return clamp(int(len(s) * (v - m) / max(1, M - m)), 0, len(s) - 1)
            fill_max = max((len(b) for b in self.bins.values()), default=0)
            fill_min = min((len(b) for b in self.bins.values()), default=0)
            distribution = [0] * min(100, self.bin_len * self.bin_len)
            for b in self.bins.values():
                distribution[get_index(distribution, len(b), fill_min, fill_max)] += 1
            filling_max = max(distribution)
            chars = '_▁▂▃▄▅▆▇█'  # https://en.wikipedia.org/wiki/Block_Elements
            def get_char(v): return chars[get_index(chars, v, 0, filling_max)] if v else ' '
            distribution = ''.join(get_char(v) for v in distribution)
            term_printer.boxed(
                f'Counts: v={len(self.verts)} e={len(self.edges)} f={len(self.faces)}',
                f'        total pts={tot_points}, bbox ins={bbox.count}, accel ins={tot_inserted}',
                f'Size: min={self.min}, max={self.max} size={self.size}',
                f'Bins: {self.bin_len}x{self.bin_len} non-zero={len(self.bins)}/{self.bin_len*self.bin_len} ({100*len(self.bins)/(self.bin_len*self.bin_len):0.0f}%)',
                f'Inserts: total={tot_inserted}, max spread={max_spread}',
                f'Fill: {fill_min} [{distribution}] {fill_max}',
                title=f'Accel2D: {label}', color='black', highlight='green',
            )

    @profiler.function
    def compute_ij(self, v2d):
        bl = self.bin_len
        return (
            clamp(int(bl * (v2d.x - self.minx) / self.sizex), 0, bl - 1),
            clamp(int(bl * (v2d.y - self.miny) / self.sizey), 0, bl - 1)
        )

    def _put(self, ij, o):
        # assert 0 <= ij[0] < self.bin_len and 0 <= ij[1] < self.bin_len, f'{ij} is outside {self.bin_len}x{self.bin_len}'
        if ij in self.bins: self.bins[ij].add(o)
        else:               self.bins[ij] = { o }

    def _get(self, ij):
        return self.bins[ij] if ij in self.bins else set()

    @profiler.function
    def clean_invalid(self):
        self.bins = {
            t: {o for o in objs if o.is_valid}
            for (t, objs) in self.bins.items()
        }

    @profiler.function
    def get(self, v2d, within, *, fn_filter=None):
        if v2d is None or not (isfinite(v2d.x) and isfinite(v2d.y)): return set()
        delta = Vec2D((within, within))
        p0, p1 = v2d - delta, v2d + delta
        i0, j0 = self.compute_ij(p0)
        i1, j1 = self.compute_ij(p1)
        ret = {
            elem
            for i in range(i0, i1+1)
            for j in range(j0, j1+1)
            for elem in self._get((i, j))
            if elem.is_valid and (fn_filter is None or fn_filter(elem))
        }
        return ret

    @profiler.function
    def get_verts(self, v2d, within):
        return self.get(v2d, within, fn_filter=self._is_vert)

    @profiler.function
    def get_edges(self, v2d, within):
        return self.get(v2d, within, fn_filter=self._is_edge)

    @profiler.function
    def get_faces(self, v2d, within):
        return self.get(v2d, within, fn_filter=self._is_face)

