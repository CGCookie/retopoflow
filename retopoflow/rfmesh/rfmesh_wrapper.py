'''
Copyright (C) 2021 CG Cookie
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

import math

import bmesh
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from bmesh.utils import (
    edge_split, vert_splice, face_split,
    vert_collapse_edge, vert_dissolve, face_join
)
from bmesh.ops import dissolve_verts, dissolve_edges, dissolve_faces
from mathutils import Vector

from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.debug import dprint
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import (
    triangle2D_det, triangle2D_area,
    segment2D_intersection,
    Vec2D, Point, Point2D, Vec, Direction, Normal,
)


'''
BMElemWrapper wraps BMverts, BMEdges, BMFaces to automagically handle
world-to-local and local-to-world transformations.

Must override any property that can be set (TODO: find more elegant
way to handle this!) and function that returns a BMVert, BMEdge, or
BMFace.  All functions and read-only properties are handled with
__getattr__().

user-writable properties:

    BMVert: co, normal
    BMEdge: seam, smooth
    BMFace: material_index, normal, smooth
    common: hide, index. select, tag

NOTE: RFVert, RFEdge, RFFace do NOT mark RFMesh as dirty!
'''


class BMElemWrapper:
    @staticmethod
    def wrap(rftarget):
        BMElemWrapper.rftarget = rftarget
        BMElemWrapper.xform = rftarget.xform
        BMElemWrapper.l2w_point = rftarget.xform.l2w_point
        BMElemWrapper.w2l_point = rftarget.xform.w2l_point
        BMElemWrapper.l2w_normal = rftarget.xform.l2w_normal
        BMElemWrapper.w2l_normal = rftarget.xform.w2l_normal
        BMElemWrapper.symmetry_real = rftarget.symmetry_real
        BMElemWrapper.mirror_mod = rftarget.mirror_mod

    @staticmethod
    def _unwrap(bmelem):
        if bmelem is None:
            return None
        if isinstance(bmelem, BMElemWrapper):
            return bmelem.bmelem
        return bmelem

    def __init__(self, bmelem):
        self.bmelem = bmelem

    def __repr__(self):
        return '<BMElemWrapper: %s>' % repr(self.bmelem)

    def __hash__(self):
        return hash(self.bmelem)

    def __eq__(self, other):
        if other is None:
            return False
        if isinstance(other, BMElemWrapper):
            return self.bmelem == other.bmelem
        return self.bmelem == other

    def __ne__(self, other):
        return not self.__eq__(other)

    @property
    def hide(self):
        return self.bmelem.hide

    @hide.setter
    def hide(self, v):
        self.bmelem.hide = v

    @property
    def index(self):
        return self.bmelem.index

    @index.setter
    def index(self, v):
        self.bmelem.index = v

    @property
    def select(self):
        return self.bmelem.select

    @select.setter
    def select(self, v):
        self.bmelem.select = v

    @property
    def tag(self):
        return self.bmelem.tag

    @tag.setter
    def tag(self, v):
        self.bmelem.tag = v

    def __getattr__(self, k):
        if k in self.__dict__:
            return getattr(self, k)
        return getattr(self.bmelem, k)


class RFVert(BMElemWrapper):
    def __repr__(self):
        return '<RFVert: %s>' % repr(self.bmelem)

    @staticmethod
    def get_link_edges(rfverts):
        return { RFEdge(bme) for bmv in rfverts for bme in bmv.bmelem.link_edges }

    @staticmethod
    def get_link_faces(rfverts):
        return { RFFace(bmf) for bmv in rfverts for bmf in bmv.bmelem.link_faces }

    @property
    def co(self):
        return self.l2w_point(self.bmelem.co)

    @co.setter
    def co(self, co):
        assert not any(math.isnan(v) for v in co), 'Setting RFVert.co to ' + str(co)
        co = self.symmetry_real(co, to_world=False)
        # # the following does not work well, because new verts have co=(0,0,0)
        # mm = BMElemWrapper.mirror_mod
        # if mm.use_clip:
        #     rft = BMElemWrapper.rftarget
        #     th = mm.symmetry_threshold * rft.unit_scaling_factor / 2.0
        #     ox,oy,oz = self.bmelem.co
        #     nx,ny,nz = (mm.x and abs(ox) <= th),(mm.y and abs(oy) <= th),(mm.z and abs(oz) <= th)
        #     if nx or ny or nz:
        #         co = rft.snap_to_symmetry(co, mm._symmetry, to_world=False, from_world=False)
        self.bmelem.co = co

    @property
    def normal(self):
        return self.l2w_normal(self.bmelem.normal)

    @normal.setter
    def normal(self, norm):
        self.bmelem.normal = self.w2l_normal(norm)

    @property
    def link_edges(self):
        return [RFEdge(bme) for bme in self.bmelem.link_edges]

    @property
    def link_faces(self):
        return [RFFace(bmf) for bmf in self.bmelem.link_faces]

    def is_on_symmetry_plane(self):
        mm = BMElemWrapper.mirror_mod
        th = mm.symmetry_threshold * BMElemWrapper.rftarget.unit_scaling_factor / 2.0
        x,y,z = self.bmelem.co
        if mm.x and abs(x) <= th: return True
        if mm.y and abs(y) <= th: return True
        if mm.z and abs(z) <= th: return True
        return False

    def is_on_boundary(self, symmetry_as_boundary=False):
        '''
        similar to is_boundary property, but optionally discard symmetry boundaries
        '''
        if not symmetry_as_boundary:
            if self.is_on_symmetry_plane(): return False
        return self.bmelem.is_boundary

    #############################################

    def share_edge(self, other):
        bmv0 = BMElemWrapper._unwrap(self)
        bmv1 = BMElemWrapper._unwrap(other)
        return any(bmv1 in bme.verts for bme in bmv0.link_edges)

    def shared_edge(self, other):
        bmv0 = BMElemWrapper._unwrap(self)
        bmv1 = BMElemWrapper._unwrap(other)
        bme = next((bme for bme in bmv0.link_edges if bmv1 in bme.verts), None)
        return RFEdge(bme) if bme else None

    def share_face(self, other):
        bmv0 = BMElemWrapper._unwrap(self)
        bmv1 = BMElemWrapper._unwrap(other)
        return any(bmv1 in bmf.verts for bmf in bmv0.link_faces)

    def shared_faces(self, other):
        bmv0 = BMElemWrapper._unwrap(self)
        bmv1 = BMElemWrapper._unwrap(other)
        return [RFFace(bmf) for bmf in bmv0.link_faces if bmv1 in bmf.verts]

    def merge(self, other):
        bmv0 = BMElemWrapper._unwrap(self)
        bmv1 = BMElemWrapper._unwrap(other)
        vert_splice(bmv1, bmv0)

    def dissolve(self):
        bmv = BMElemWrapper._unwrap(self)
        vert_dissolve(bmv)

    def compute_normal(self):
        ''' computes normal as average of normals of all linked faces '''
        return Normal(sum((f.compute_normal() for f in self.link_faces), Vec((0,0,0))))


class RFEdge(BMElemWrapper):
    def __repr__(self):
        return '<RFEdge: %s>' % repr(self.bmelem)

    @staticmethod
    def get_verts(rfedges):
        bmvs = { bmv for bme in rfedges for bmv in bme.bmelem.verts }
        return { RFVert(bmv) for bmv in bmvs }

    @property
    def seam(self):
        return self.bmelem.seam

    @seam.setter
    def seam(self, v):
        self.bmelem.seam = v

    @property
    def smooth(self):
        return self.bmelem.smooth

    @smooth.setter
    def smooth(self, v):
        self.bmelem.smooth = v

    def first_vert(self):
        return RFVert(self.bmelem.verts[0])

    def other_vert(self, bmv):
        bmv = self._unwrap(bmv)
        o = self.bmelem.other_vert(bmv)
        if o is None:
            return None
        return RFVert(o)

    def share_vert(self, bme):
        bme = self._unwrap(bme)
        return any(v in bme.verts for v in self.bmelem.verts)

    def shared_vert(self, bme):
        bme = self._unwrap(bme)
        verts = [v for v in self.bmelem.verts if v in bme.verts]
        if not verts:
            return None
        return RFVert(verts[0])

    def nonshared_vert(self, bme):
        bme = self._unwrap(bme)
        verts = [v for v in self.bmelem.verts if v not in bme.verts]
        if len(verts) != 1:
            return None
        return RFVert(verts[0])

    def share_face(self, bme):
        bme = self._unwrap(bme)
        return any(f in bme.link_faces for f in self.bmelem.link_faces)

    def shared_faces(self, bme):
        bme = self._unwrap(bme)
        return {
            RFFace(f)
            for f in (set(self.bmelem.link_faces) & set(bme.link_faces))
        }

    @property
    def verts(self):
        bmv0, bmv1 = self.bmelem.verts
        return (RFVert(bmv0), RFVert(bmv1))

    @property
    def link_faces(self):
        return [RFFace(bmf) for bmf in self.bmelem.link_faces]

    def get_left_right_link_faces(self):
        v0, v1 = self.bmelem.verts
        bmfl, bmfr = None, None
        if len(self.bmelem.link_faces) == 2:
            bmfl, bmfr = self.bmelem.link_faces
        elif len(self.bmelem.link_faces) == 1:
            bmfl = next(iter(self.bmelem.link_faces))
        else:
            return (None, None)

        for lv0, lv1 in iter_pairs(bmfl.verts, True):
            if lv0 == v0 and lv1 == v1:
                # correct orientation!
                break
        else:
            # swap left and right faces
            bmfl, bmfr = bmfr, bmfl

        if bmfl:
            bmfl = RFFace(bmfl)
        if bmfr:
            bmfr = RFFace(bmfr)
        return (bmfl, bmfr)

    #############################################

    def normal(self):
        n, c = Vector(), 0
        for bmf in self.bmelem.link_faces:
            n += bmf.normal
            c += 1
        return n / max(1, c)

    def calc_length(self):
        v0, v1 = self.bmelem.verts
        return (self.l2w_point(v0.co) - self.l2w_point(v1.co)).length

    @property
    def length(self):
        return self.calc_length()

    def calc_center(self):
        v0, v1 = self.bmelem.verts
        return self.l2w_point((v0.co + v1.co) / 2)

    def vector(self, from_vert=None, to_vert=None):
        v0, v1 = self.verts
        if from_vert:
            if v1 == from_vert: v0, v1 = v1, v0
            assert v0 == from_vert
        elif to_vert:
            if v0 == to_vert: v0, v1 = v1, v0
            assert v1 == to_vert
        return v1.co - v0.co

    def vector2D(self, Point_to_Point2D, from_vert=None, to_vert=None):
        v0, v1 = self.verts
        if from_vert:
            if v1 == from_vert: v0, v1 = v1, v0
            assert v0 == from_vert
        elif to_vert:
            if v0 == to_vert: v0, v1 = v1, v0
            assert v1 == to_vert
        return Point_to_Point2D(v1.co) - Point_to_Point2D(v0.co)

    def direction(self, from_vert=None, to_vert=None):
        return Direction(self.vector(from_vert=from_vert, to_vert=to_vert))

    def perpendicular(self):
        d = self.vector()
        n = self.normal()
        return Direction(d.cross(n))

    @staticmethod
    def get_direction(bme):
        v0, v1 = bme.verts
        return Direction(v1.co - v0.co)

    #############################################

    def get_next_edge_in_strip(self, rfvert):
        '''
        given self=A and bmv=B, return C

        O-----O-----O...     O-----O-----O...
        |     |     |        |     |     |
        O--A--B--C--O...     O--A--B--C--O...
        |     |     |        |     |\
        O-----O-----O...     O-----O O...
                                    \|
                                     O...
               crawl dir: ======>

        left : "normal" case, where B is part of 4 touching quads
        right: here, find the edge with the direction most similarly
               pointing in same direction
        '''
        bmv = self._unwrap(rfvert)
        assert bmv in self.bmelem.verts, "Vert not part of Edge"

        link_faces = list(self.bmelem.link_faces)
        link_edges = [bme for bme in bmv.link_edges if bme != self.bmelem]

        # for details, see: https://github.com/CGCookie/retopoflow/issues/554#issuecomment-408185805

        if len(link_faces) == 0:
            if len(link_edges) != 1: return None
            bme = link_edges[0]
            if len(bme.link_faces) != 0: return None
            return RFEdge(bme)

        if len(link_faces) == 1:
            bmf0 = link_faces[0]
            lbme = [bme for bme in link_edges if len(bme.link_faces) == 1]
            lbme = [bme for bme in lbme if bmf0 not in bme.link_faces]
            lbme = [bme for bme in lbme if any(bme0 == bme1 for bme0 in bmf0.edges for bmf1 in bme.link_faces for bme1 in bmf1.edges)]
            if len(lbme) != 1: return None
            return RFEdge(lbme[0])

        if len(link_faces) == 2 and len(bmv.link_faces) == 4 and len(bmv.link_edges) == 4:
            # bmv is part of 4 touching quads and all quads are touching
            # (left figure above)
            # find bme that does not share a face with self
            for bme in rfvert.link_edges:
                if len(bme.link_faces) != 2: continue
                if not (set(bme.link_faces) & set(link_faces)):
                    return bme
            return None

        return None

    #############################################

    def split(self, vert=None, fac=0.5):
        bme = BMElemWrapper._unwrap(self)
        bmv = BMElemWrapper._unwrap(vert) or bme.verts[0]
        bme_new, bmv_new = edge_split(bme, bmv, fac)
        return RFEdge(bme_new), RFVert(bmv_new)

    def collapse(self):
        bme = BMElemWrapper._unwrap(self)
        bmv0, bmv1 = bme.verts
        del_faces = [f for f in bme.link_faces if len(f.verts) == 3]
        for bmf in del_faces:
            self.rftarget.bme.faces.remove(bmf)
        bmesh.ops.collapse(self.rftarget.bme, edges=[bme], uvs=True)
        return bmv0 if bmv0.is_valid else bmv1


class RFFace(BMElemWrapper):
    def __repr__(self):
        return '<RFFace: %s>' % repr(self.bmelem)

    @staticmethod
    def get_verts(rffaces):
        bmvs = { bmv for bmf in rffaces for bmv in bmf.bmelem.verts }
        return { RFVert(bmv) for bmv in bmvs }

    @property
    def material_index(self):
        return self.bmelem.material_index

    @material_index.setter
    def material_index(self, v):
        self.bmelem.material_index = v

    @property
    def normal(self):
        return self.l2w_normal(self.bmelem.normal)

    @normal.setter
    def normal(self, v):
        self.bmelem.normal = self.w2l_normal(v)

    @property
    def smooth(self):
        return self.bmelem.smooth

    @smooth.setter
    def smooth(self, v):
        self.bmelem.smooth = v

    @property
    def edges(self):
        return [RFEdge(bme) for bme in self.bmelem.edges]

    def share_edge(self, other):
        bmes = set(self._unwrap(other).edges)
        return any(e in bmes for e in self.bmelem.edges)

    def shared_edge(self, other):
        edges = set(self.bmelem.edges)
        for bme in other.bmelem.edges:
            if bme in edges:
                return RFEdge(bme)
        return None

    def opposite_edge(self, e):
        if len(self.bmelem.edges) != 4:
            return None
        e = self._unwrap(e)
        for i, bme in enumerate(self.bmelem.edges):
            if bme == e:
                return RFEdge(self.bmelem.edges[(i + 2) % 4])
        return None

    def neighbor_edges(self, e):
        e = self._unwrap(e)
        l = len(self.bmelem.edges)
        for i, bme in enumerate(self.bmelem.edges):
            if bme == e:
                return (
                    RFEdge(self.bmelem.edges[(i - 1) % l]),
                    RFEdge(self.bmelem.edges[(i + 1) % l])
                )
        return None

    @property
    def verts(self):
        return [RFVert(bmv) for bmv in self.bmelem.verts]

    def get_vert_co(self):
        return [self.l2w_point(bmv.co) for bmv in self.bmelem.verts]

    def get_vert_normal(self):
        return [self.l2w_normal(bmv.normal) for bmv in self.bmelem.verts]

    def is_quad(self):
        return len(self.bmelem.verts) == 4

    def is_triangle(self):
        return len(self.bmelem.verts) == 3

    def center(self):
        return Point.average(self.l2w_point(bmv.co) for bmv in self.bmelem.verts)
        cos = [Vec(self.l2w_point(bmv.co)) for bmv in self.bmelem.verts]
        return Point(sum(cos, Vec((0, 0, 0))) / len(cos))

    #############################################

    def compute_normal(self):
        ''' computes normal based on verts '''
        # TODO: should use loop rather than verts?
        an = Vec((0,0,0))
        vs = list(self.bmelem.verts)
        bmv1,bmv2 = vs[-2],vs[-1]
        v1 = bmv2.co - bmv1.co
        for i in range(len(vs)):
            bmv0,bmv1,bmv2 = bmv1,bmv2,vs[i]
            v0,v1 = -v1,bmv2.co-bmv1.co
            an = an + Normal(v1.cross(v0))
        return self.l2w_normal(Normal(an))

    def is_flipped(self):
        fn = self.w2l_normal(self.compute_normal())
        vs = list(self.bmelem.verts)
        return any(v.normal.dot(fn) <= 0 for v in vs)

    def overlap2D(self, other, Point_to_Point2D):
        return self.overlap2D_center(other, Point_to_Point2D)

    def overlap2D_center(self, other, Point_to_Point2D):
        verts0 = list(map(Point_to_Point2D, [v.co for v in self.bmelem.verts]))
        verts1 = list(
            map(Point_to_Point2D, [v.co for v in self._unwrap(other).verts]))
        center0 = sum(map(Vec2D, verts0), Vec2D((0, 0))) / len(verts0)
        center1 = sum(map(Vec2D, verts1), Vec2D((0, 0))) / len(verts1)
        radius0 = sum((v - center0).length for v in verts0) / len(verts0)
        radius1 = sum((v - center1).length for v in verts1) / len(verts1)
        ratio = 1 - (center0 - center1).length / (radius0 + radius1)
        return max(0, ratio)

    def overlap2D_Sutherland_Hodgman(self, other, Point_to_Point2D):
        '''
        computes area in image space of overlap between self and other
        this is done by clipping other to self by iterating through all of
        edges in self and clipping to the "inside" half-space.
        Sutherland-Hodgman Algorithm:
          https://en.wikipedia.org/wiki/Sutherland%E2%80%93Hodgman_algorithm
        '''

        # NOTE: assumes self and other are convex! (not a terrible assumption)

        verts0 = list(map(Point_to_Point2D, [v.co for v in self.bmelem.verts]))
        verts1 = list(
            map(Point_to_Point2D, [v.co for v in self._unwrap(other).verts]))

        for v00, v01 in zip(verts0, verts0[1:] + verts0[:1]):
            # other polygon (verts1) by line v00-v01
            len1 = len(verts1)
            sides = [triangle2D_det(v00, v01, v1) <= 0 for v1 in verts1]
            intersections = [
                segment2D_intersection(v00, v01, v10, v11)
                for v10, v11 in zip(verts1, verts1[1:] + verts1[:1])
            ]
            nverts1 = []
            for i0 in range(len1):
                i1 = (i0 + 1) % len1
                v10, v11 = verts1[i0], verts1[i1]
                s10, s11 = sides[i0], sides[i1]

                if s10 and s11:
                    # both outside. might intersect
                    if intersections[i0]:
                        nverts1 += [intersections[i0]]
                elif not s11:
                    if s10:
                        # v10 is outside, v11 is inside
                        if intersections[i0]:
                            nverts1 += [intersections[i0]]
                    nverts1 += [v11]
            verts1 = nverts1

        if len(verts1) < 3:
            return 0
        v0 = verts1[0]
        return sum(
            triangle2D_area(v0, v1, v2)
            for v1, v2 in zip(verts1[1:-1], verts1[2:])
        )

    def merge(self, other):
        # find vert of other that is closest to self's v0
        verts0, verts1 = list(self.bmelem.verts), list(other.bmelem.verts)
        l = len(verts0)
        assert l == len(verts1), 'RFFaces must have same vert count'
        self.rftarget.bme.faces.remove(self._unwrap(other))
        offset = min(range(l), key=lambda i: (
            verts1[i].co - verts0[0].co).length)
        # assuming verts are in same rotational order (should be)
        for i0 in range(l):
            i1 = (i0 + offset) % l
            bme = next((
                bme
                for bme in verts0[i0].link_edges
                if verts1[i1] in bme.verts
            ), None)
            if bme:
                # issue #372
                # TODO: handle better
                dprint('bme: ' + str(bme))
                pass
            else:
                vert_splice(verts1[i1], verts0[i0])
        # for v in verts0:
        #    self.rftarget.clean_duplicate_bmedges(v)

    #############################################

    def split(self, vert_a, vert_b, coords=[]):
        bmf = BMElemWrapper._unwrap(self)
        bmva = BMElemWrapper._unwrap(vert_a)
        bmvb = BMElemWrapper._unwrap(vert_b)
        coords = [BMElemWrapper.w2l_point(c) for c in coords]
        bmf_new, bml_new = face_split(bmf, bmva, bmvb, coords=coords)
        return RFFace(bmf_new)


class RFEdgeSequence:
    def __init__(self, sequence):
        if not sequence:
            self.verts = []
            self.edges = []
            self.loop = False
            return

        seq = list(BMElemWrapper._unwrap(elem) for elem in sequence)

        if type(seq[0]) is BMVert:
            self.verts = seq
            self.loop = (
                len(seq) > 1 and
                len(set(seq[0].link_edges) & set(seq[-1].link_edges)) != 0
            )
            self.edges = [next(iter(set(v0.link_edges) & set(v1.link_edges)))
                          for v0, v1 in iter_pairs(seq, self.loop)]
        elif type(seq[0]) is BMEdge:
            self.edges = seq
            self.loop = len(seq) > 2 and len(
                set(seq[0].verts) & set(seq[-1].verts)) != 0
            if len(seq) == 1 and not self.loop:
                self.verts = seq[0].verts
            else:
                self.verts = [next(iter(set(e0.verts) & set(e1.verts)))
                              for e0, e1 in iter_pairs(seq, self.loop)]
        else:
            assert False, 'unhandled type: %s' % str(type(seq[0]))

    def __repr__(self):
        e = min(map(repr, self.edges)) if self.edges else None
        return '<RFEdgeSequence: %d,%s,%s>' % (
            len(self.verts), str(self.loop), str(e)
        )

    def __len__(self):
        return len(self.edges)

    def get_verts(self):
        return [RFVert(bmv) for bmv in self.verts]

    def get_edges(self):
        return [RFEdge(bme) for bme in self.edges]

    def is_loop(self):
        return self.loop

    def iter_vert_pairs(self):
        return iter_pairs(self.get_verts(), self.loop)

    def iter_edge_pairs(self):
        return iter_pairs(self.get_edges(), self.loop)
