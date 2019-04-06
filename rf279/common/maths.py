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

from math import sqrt, acos, cos, sin
from typing import List

import bgl
from mathutils import Matrix, Vector, Quaternion
from bmesh.types import BMVert
from mathutils.geometry import intersect_line_plane, intersect_point_tri

from .decorators import stats_wrapper
from .profiler import profiler


'''
The types below wrap the mathutils.Vector class, distinguishing among the
different types of geometric entities that are typically represented using
a vanilla Vector.
'''


float_inf = float('inf')


class Entity2D:
    def is_2D(self):
        return True

    def is_3D(self):
        return False


class Entity3D:
    def is_2D(self):
        return False

    def is_3D(self):
        return True


class VecUtils(Vector):
    def normalize(self):
        super().normalize()
        return self

    def as_vector(self):
        return Vector(self)

    def from_vector(self, v):
        self.x, self.y, self.z = v

    def perpendicular_direction(self):
        q0 = Quaternion(Vector((42, 1.618034, 2.71828)), 1.5707963)
        q1 = Quaternion(Vector((1.41421, 2, 1.73205)), -1.5707963)
        v = q1 * q0 * self
        return Direction(self.cross(v))

    def cross(self, other):
        t = type(other)
        if t is Vector:
            return Vec(super().cross(other))
        if t is Vec or t is Direction or t is Normal:
            return Vec(super().cross(Vector(other)))
        assert False, 'unhandled type of other: %s (%s)' % (str(other), str(t))


class Vec2D(Vector, Entity2D):
    @stats_wrapper
    def __init__(self, *args, **kwargs):
        Vector.__init__(*args, **kwargs)

    def __str__(self):
        return '<Vec2D (%0.4f, %0.4f)>' % (self.x, self.y)

    def __repr__(self):
        return self.__str__()

    def as_vector(self):
        return Vector(self)

    def from_vector(self, v):
        self.x, self.y = v

    def project(self, other):
        ''' returns the projection of self onto other '''
        olen2 = other.length_squared
        if olen2 <= 0.00000001: return Vec2D((0,0))
        return (self.dot(other) / olen2) * other


class Vec(VecUtils, Entity3D):
    @stats_wrapper
    def __init__(self, *args, **kwargs):
        Vector.__init__(*args, **kwargs)

    def __str__(self):
        return '<Vec (%0.4f, %0.4f, %0.4f)>' % (self.x, self.y, self.z)

    def __repr__(self):
        return self.__str__()

    def project(self, other):
        ''' returns the projection of self onto other '''
        olen2 = other.length_squared
        if olen2 <= 0.00000001: return Vec3D((0,0,0))
        return (self.dot(other) / olen2) * other


class Point2D(Vector, Entity2D):
    @stats_wrapper
    def __init__(self, *args, **kwargs):
        Vector.__init__(*args, **kwargs)

    def __str__(self):
        return '<Point2D (%0.4f, %0.4f)>' % (self.x, self.y)

    def __repr__(self):
        return self.__str__()

    def __iter__(self):
        return iter([self.x, self.y])

    def __add__(self, other):
        t = type(other)
        if t is Direction2D:
            return Point2D((self.x + other.x, self.y + other.y))
        if t is Vector or t is Vec2D:
            return Point2D((self.x + other.x, self.y + other.y))
        assert False, "unhandled type of other: %s (%s)" % (str(other), str(t))

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        t = type(other)
        if t is Vector or t is Vec2D:
            return Point2D((self.x - other.x, self.y - other.y))
        elif t is Point2D:
            return Vec2D((self.x - other.x, self.y - other.y))
        assert False, "unhandled type of other: %s (%s)" % (str(other), str(t))

    def distance_squared_to(self, other) -> float:
        return (self.x - other.x)**2 + (self.y - other.y)**2

    def distance_to(self, other) -> float:
        return sqrt((self.x - other.x)**2 + (self.y - other.y)**2)

    def as_vector(self):
        return Vector(self)

    def from_vector(self, v):
        self.x, self.y = v

    @staticmethod
    def average(points):
        x, y, c = 0, 0, 0
        for p in points:
            x += p.x
            y += p.y
            c += 1
        if c == 0:
            return Point2D((0, 0))
        return Point2D((x / c, y / c))

    @staticmethod
    def weighted_average(weight_points):
        x, y, c = 0, 0, 0
        for w, p in weight_points:
            x += p.x * w
            y += p.y * w
            c += w
        if c == 0:
            return Point2D((0, 0))
        return Point2D((x / c, y / c))


class Point(Vector, Entity3D):
    @stats_wrapper
    def __init__(self, *args, **kwargs):
        Vector.__init__(*args, **kwargs)

    def __str__(self):
        return '<Point (%0.4f, %0.4f, %0.4f)>' % (self.x, self.y, self.z)

    def __repr__(self):
        return self.__str__()

    def __add__(self, other):
        t = type(other)
        if t is Direction or t is Normal:
            return Point((
                self.x + other.x,
                self.y + other.y,
                self.z + other.z
            ))
        if t is Vector or t is Vec:
            return Point((
                self.x + other.x,
                self.y + other.y,
                self.z + other.z
            ))
        assert False, "unhandled type of other: %s (%s)" % (str(other), str(t))

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        t = type(other)
        if t is Vector or t is Vec:
            return Point((
                self.x - other.x,
                self.y - other.y,
                self.z - other.z
            ))
        elif t is Point:
            return Vec((
                self.x - other.x,
                self.y - other.y,
                self.z - other.z
            ))
        assert False, "unhandled type of other: %s (%s)" % (str(other), str(t))

    def as_vector(self):
        return Vector(self)

    def from_vector(self, v):
        self.x, self.y, self.z = v

    @staticmethod
    def average(points):
        x, y, z, c = 0, 0, 0, 0
        for p in points:
            x += p.x
            y += p.y
            z += p.z
            c += 1
        if c == 0:
            return Point((0, 0, 0))
        return Point((x / c, y / c, z / c))

    @staticmethod
    def weighted_average(weight_points):
        x, y, z, c = 0, 0, 0, 0
        for w, p in weight_points:
            x += p.x * w
            y += p.y * w
            z += p.z * w
            c += w
        if c == 0:
            return Point((0, 0, 0))
        return Point((x / c, y / c, z / c))

class Direction2D(Vector, Entity2D):
    @stats_wrapper
    def __init__(self, t=None):
        if t is not None:
            self.from_vector(t)

    def __str__(self):
        return '<Direction2D (%0.4f, %0.4f)>' % (self.x, self.y)

    def __repr__(self):
        return self.__str__()

    def __mul__(self, other):
        t = type(other)
        if t is float or t is int:
            return Vec2D((other * self.x, other * self.y))
        assert False, "unhandled type of other: %s (%s)" % (str(other), str(t))

    def __rmul__(self, other):
        return self.__mul__(other)

    def normalize(self):
        super().normalize()
        return self

    def as_vector(self):
        return Vector(self)

    def from_vector(self, v):
        self.x, self.y = v
        self.normalize()


class Direction(VecUtils, Entity3D):
    @stats_wrapper
    def __init__(self, t=None):
        if t is not None:
            self.from_vector(t)

    def __str__(self):
        return '<Direction (%0.4f, %0.4f, %0.4f)>' % (self.x, self.y, self.z)

    def __repr__(self):
        return self.__str__()

    def __mul__(self, other):
        t = type(other)
        if t is float or t is int:
            return Vector((other * self.x, other * self.y, other * self.z))
        assert False, "unhandled type of other: %s (%s)" % (str(other), str(t))

    def __rmul__(self, other):
        return self.__mul__(other)

    def reverse(self):
        self.x *= -1
        self.y *= -1
        self.z *= -1
        return self

    def angleBetween(self, other):
        return acos(mid(-1, 1, self.dot(other.normalized())))

    def from_vector(self, v):
        super().from_vector(v)
        self.normalize()


class Normal(VecUtils, Entity3D):
    @stats_wrapper
    def __init__(self, t=None):
        if t is not None:
            self.from_vector(t)

    def __str__(self):
        return '<Normal (%0.4f, %0.4f, %0.4f)>' % (self.x, self.y, self.z)

    def __repr__(self):
        return self.__str__()

    def __mul__(self, other):
        t = type(other)
        if t is float or t is int:
            return Vector((other * self.x, other * self.y, other * self.z))
        assert False, "unhandled type of other: %s (%s)" % (str(other), str(t))

    def __rmul__(self, other):
        return self.__mul__(other)

    def from_vector(self, v):
        super().from_vector(v)
        self.normalize()


class Ray(Entity3D):
    __slots__ = ['o', 'd', 'max']

    @staticmethod
    def from_segment(a: Point, b: Point):
        v = b - a
        dist = v.length
        return Ray(a, v / dist, max_dist=dist)

    @stats_wrapper
    def __init__(
        self,
        o: Point,
        d: Direction,
        min_dist: float=0.0,
        max_dist: float=float_inf
    ):
        # sys.float_info.max
        o, d = Point(o), Direction(d)
        self.o = o + min_dist * d
        self.d = d
        if max_dist == float_inf:
            self.max = max_dist
        else:
            om = o + max_dist * d
            self.max = (self.o - om).length

    def __str__(self):
        return '<Ray (%0.4f, %0.4f, %0.4f)->(%0.4f, %0.4f, %0.4f)>' % (
            self.o.x, self.o.y, self.o.z,
            self.d.x, self.d.y, self.d.z
        )

    def __repr__(self):
        return self.__str__()

    def eval(self, t: float):
        return self.o + max(0.0, min(self.max, t)) * self.d

    @classmethod
    def from_screenspace(cls, pos: Vector):
        # convert pos in screenspace to ray
        pass


class Plane(Entity3D):
    @classmethod
    def from_points(cls, p0: Point, p1: Point, p2: Point):
        o = Point((
            (p0.x + p1.x + p2.x) / 3,
            (p0.y + p1.y + p2.y) / 3,
            (p0.z + p1.z + p2.z) / 3
        ))
        n = Normal((p1 - p0).cross(p2 - p0)).normalize()
        return cls(o, n)

    def __init__(self, o: Point, n: Normal):
        self.o = o
        self.n = n

    def __str__(self):
        return '<Plane (%0.4f, %0.4f, %0.4f), (%0.4f, %0.4f, %0.4f)>' % (
            self.o.x, self.o.y, self.o.z,
            self.n.x, self.n.y, self.n.z
        )

    def __repr__(self):
        return self.__str__()

    def side(self, p: Point):
        d = (p - self.o).dot(self.n)
        if abs(d) < 0.000001:
            return 0
        return -1 if d < 0 else 1

    def distance_to(self, p: Point):
        return abs((p - self.o).dot(self.n))

    def signed_distance_to(self, p: Point):
        return (p - self.o).dot(self.n)

    def project(self, p: Point):
        return p + self.n * (self.o - p).dot(self.n)

    def polygon_intersects(self, points: List[Point]):
        return abs(sum(self.side(p) for p in points)) != len(points)

    @stats_wrapper
    def triangle_intersect(self, points: List[Point]):
        return abs(sum(self.side(p) for p in points)) != 3

    @profiler.profile
    def triangle_intersection(self, points: List[Point]):
        l = len(points)
        assert l == 3, 'triangle intersection on non triangle (%d)' % (l,)
        s0, s1, s2 = map(self.side, points)
        if abs(s0 + s1 + s2) == 3:
            return []    # all points on same side of plane
        p0, p1, p2 = map(Point, points)
        if s0 == 0 or s1 == 0 or s2 == 0:   # at least one point on plane
            # handle if all points in plane
            if s0 == 0 and s1 == 0 and s2 == 0:
                return [(p0, p1), (p1, p2), (p2, p0)]
            # handle if two points in plane
            if s0 == 0 and s1 == 0:
                return [(p0, p1)]
            if s1 == 0 and s2 == 0:
                return [(p1, p2)]
            if s2 == 0 and s0 == 0:
                return [(p2, p0)]
            # one point on plane, two on same side
            if s0 == 0 and s1 == s2:
                return [(p0, p0)]
            if s1 == 0 and s2 == s0:
                return [(p1, p1)]
            if s2 == 0 and s0 == s1:
                return [(p2, p2)]
        # two points on one side, one point on the other
        p01 = intersect_line_plane(p0, p1, self.o, self.n)
        p12 = intersect_line_plane(p1, p2, self.o, self.n)
        p20 = intersect_line_plane(p2, p0, self.o, self.n)
        if s0 == 0:
            return [(p0, p12)]
        if s1 == 0:
            return [(p1, p20)]
        if s2 == 0:
            return [(p2, p01)]
        if s0 != s1 and s0 != s2 and p01 and p20:
            return [(p01, p20)]
        if s1 != s0 and s1 != s2 and p01 and p12:
            return [(p01, p12)]
        if s2 != s0 and s2 != s1 and p12 and p20:
            return [(p12, p20)]
        print('%s %s %s' % (str(p0), str(p1), str(p2)))
        print('%s %s %s' % (str(s0), str(s1), str(s2)))
        print('%s %s %s' % (str(p01), str(p12), str(p20)))
        assert False

    def line_intersection(self, p0:Point, p1:Point):
        return intersect_line_plane(p0, p1, self.o, self.n)

    @stats_wrapper
    def edge_intersect(self, points: List[Point]):
        return abs(sum(self.side(p) for p in points)) != 2

    @profiler.profile
    def edge_intersection(self, points: List[Point]):
        s0, s1 = map(self.side, points)
        if abs(s0 + s1) == 2:
            return []   # points on same side
        p0, p1 = map(Point, points)
        if s0 == 0 and s1 == 0:
            return [(p0, p1)]
        if s0 == 0:
            return [(p0, p0)]
        if s1 == 0:
            return [(p1, p1)]
        p01 = Point(intersect_line_plane(p0, p1, self.o, self.n))
        return [(p01, p01)]

    def edge_crosses(self, points):
        p0, p1 = points
        return self.side(p0) != self.side(p1)

    def edge_coplanar(self, points):
        p0, p1 = points
        return self.side(p0) == 0 and self.side(p1) == 0


class Frame:
    @staticmethod
    def from_plane(plane: Plane, x: Direction=None, y: Direction=None):
        return Frame(plane.o, x=x, y=y, z=Direction(plane.n))

    @stats_wrapper
    def __init__(
        self,
        o: Point,
        x: Direction=None,
        y: Direction=None,
        z: Direction=None
    ):
        c = (1 if x else 0) + (1 if y else 0) + (1 if z else 0)
        assert c != 0, "Must specify at least one direction"
        if c == 1:
            if x:
                y = Direction((-x.x + 3.14, x.y + 42, x.z - 1.61))
                z = Direction(x.cross(y))
                y = Direction(z.cross(x))
            elif y:
                x = Direction((-y.x + 3.14, y.y + 42, y.z - 1.61))
                z = Direction(x.cross(y))
                x = Direction(y.cross(z))
            else:
                x = Direction((-z.x + 3.14, z.y + 42, z.z - 1.61))
                y = Direction(-x.cross(z))
                x = Direction(y.cross(z))
        elif c >= 2:
            if x and y:
                z = Direction(x.cross(y))
                y = Direction(z.cross(x))
                x = Direction(y.cross(z))
            elif x and z:
                y = Direction(z.cross(x))
                x = Direction(y.cross(z))
                z = Direction(x.cross(y))
            else:
                x = Direction(y.cross(z))
                y = Direction(z.cross(x))
                z = Direction(z)

        self.o = Point(o)
        self.x = x
        self.y = y
        self.z = z

        self.fn_l2w_typed = {
            Vec: self.l2w_vector,
            Point: self.l2w_point,
            Normal: self.l2w_normal,
            Vector: self.l2w_vector,
            Direction: self.l2w_direction,
            # Ray:        self.l2w_ray,
            # Plane:      self.l2w_plane,
            # BMVert:     self.l2w_bmvert,
        }
        self.fn_w2l_typed = {
            Vec: self.w2l_vector,
            Point: self.w2l_point,
            Normal: self.w2l_normal,
            Vector: self.w2l_vector,
            Direction: self.w2l_direction,
            # Ray:        self.w2l_ray,
            # Plane:      self.w2l_plane,
            # BMVert:     self.w2l_bmvert,
        }

    def __str__(self):
        s = '(%0.4f, %0.4f, %0.4f)'
        return '<Frame %s, %s, %s, %s>' % (
            s % (self.o.x, self.o.y, self.o.z),
            s % (self.x.x, self.x.y, self.x.z),
            s % (self.y.x, self.y.y, self.y.z),
            s % (self.z.x, self.z.y, self.z.z)
        )

    def _dot_fns(self):
        return self.x.dot, self.y.dot, self.z.dot

    def _dots(self, v):
        return (self.x.dot(v), self.y.dot(v), self.z.dot(v))

    def _mults(self, v):
        return self.x * v.x + self.y * v.y + self.z * v.z

    def l2w_typed(self, data):
        ''' dispatched conversion '''
        t = type(data)
        assert t in self.fn_l2w_typed, "unhandled type of data: %s (%s)" % (
            str(data), str(type(data))
        )
        return self.fn_l2w_typed[t](data)

    def w2l_typed(self, data):
        ''' dispatched conversion '''
        t = type(data)
        assert t in self.fn_w2l_typed, "unhandled type of data: %s (%s)" % (
            str(data), str(type(data))
        )
        return self.fn_w2l_typed[t](data)

    def w2l_point(self, p: Point) -> Point:
        return Point(self._dots(p - self.o))

    def l2w_point(self, p: Point) -> Point:
        return Point(self.o + self._mults(p))

    def w2l_vector(self, v: Vector) -> Vec:
        return Vec(self._dots(v))

    def l2w_vector(self, v: Vector) -> Vec:
        return Vec(self._mults(v))

    def w2l_direction(self, d: Direction) -> Direction:
        return Direction(self._dots(d)).normalize()

    def l2w_direction(self, d: Direction) -> Direction:
        return Direction(self._mults(d)).normalize()

    def w2l_normal(self, n: Normal) -> Normal:
        return Normal(self._dots(n)).normalize()

    def l2w_normal(self, n: Normal) -> Normal:
        return Normal(self._mults(n)).normalize()

    def w2l_frame(self, f):
        o = self.w2l_point(f.o)
        x = self.w2l_direction(f.x)
        y = self.w2l_direction(f.y)
        z = self.w2l_direction(f.z)
        return Frame(o=o, x=x, y=y, z=z)

    def l2w_frame(self, f):
        o = self.l2w_point(f.o)
        x = self.l2w_direction(f.x)
        y = self.l2w_direction(f.y)
        z = self.l2w_direction(f.z)
        return Frame(o=o, x=x, y=y, z=z)

    def rotate_about_z(self, radians: float):
        c, s = cos(radians), sin(radians)
        x, y = self.x, self.y
        self.x = x * c + y * s
        self.y = -x * s + y * c


class XForm:
    @staticmethod
    def get_mats(mx: Matrix):
        smat, d = str(mx), XForm.get_mats.__dict__
        if smat not in d:
            m = {
                'mx_p': None, 'imx_p': None,
                'mx_d': None, 'imx_d': None,
                'mx_n': None, 'imx_n': None
            }
            m['mx_p'] = Matrix(mx)
            m['mx_t'] = mx.transposed()
            m['imx_p'] = mx.inverted()
            m['mx_d'] = mx.to_3x3()
            m['imx_d'] = m['mx_d'].inverted()
            m['mx_n'] = m['imx_d'].transposed()
            m['imx_n'] = m['mx_d'].transposed()
            d[smat] = m
        return d[smat]

    @stats_wrapper
    def __init__(self, mx: Matrix=None):
        if mx is None:
            mx = Matrix()
        self.assign(mx)

    def assign(self, mx):
        if type(mx) is XForm:
            return self.assign(mx.mx_p)

        mats = XForm.get_mats(mx)
        self.mx_p, self.imx_p = mats['mx_p'], mats['imx_p']
        self.mx_d, self.imx_d = mats['mx_d'], mats['imx_d']
        self.mx_n, self.imx_n = mats['mx_n'], mats['imx_n']
        self.mx_t = mats['mx_t']

        self.fn_l2w_typed = {
            Ray: lambda x: self.l2w_ray(x),
            Vec: lambda x: self.l2w_vector(x),
            Plane: lambda x: self.l2w_plane(x),
            Point: lambda x: self.l2w_point(x),
            BMVert: lambda x: self.l2w_bmvert(x),
            Normal: lambda x: self.l2w_normal(x),
            Vector: lambda x: self.l2w_vector(x),
            Direction: lambda x: self.l2w_direction(x),
        }
        self.fn_w2l_typed = {
            Ray: lambda x: self.w2l_ray(x),
            Vec: lambda x: self.w2l_vector(x),
            Plane: lambda x: self.w2l_plane(x),
            Point: lambda x: self.w2l_point(x),
            BMVert: lambda x: self.w2l_bmvert(x),
            Normal: lambda x: self.w2l_normal(x),
            Vector: lambda x: self.w2l_vector(x),
            Direction: lambda x: self.w2l_direction(x),
        }
        return self

    def __str__(self):
        v = tuple(x for r in self.mx_p for x in r)
        return '<XForm (%0.4f, %0.4f, %0.4f, %0.4f)\n' \
               '       (%0.4f, %0.4f, %0.4f, %0.4f)\n' \
               '       (%0.4f, %0.4f, %0.4f, %0.4f)\n' \
               '       (%0.4f, %0.4f, %0.4f, %0.4f)>' % v

    def __repr__(self):
        return self.__str__()

    def __mul__(self, other):
        t = type(other)
        if t is XForm:
            return XForm(self.mx_p * other.mx_p)
        if t is Matrix:
            return XForm(self.mx_p * other)
        return self.l2w_typed(other)

    def __imul__(self, other):
        other_mx = other.mx_p if type(other) is XForm else other
        self.assign(self.mx_p * other_mx)

    def __truediv__(self, other):
        return self.w2l_typed(other)

    def __iter__(self):
        for v in self.mx_p:
            yield v

    def to_frame(self):
        o = Point(self.mx_p * Point((0, 0, 0)))
        x = Direction(self.mx_d * Direction((1, 0, 0)))
        y = Direction(self.mx_d * Direction((0, 1, 0)))
        z = Direction(self.mx_d * Direction((0, 0, 1)))
        return Frame(o=o, x=x, y=y, z=z)

    def l2w_typed(self, data):
        ''' dispatched conversion '''
        t = type(data)
        assert t in self.fn_l2w_typed, "unhandled type of data: %s (%s)" % (
            str(data), str(type(data))
        )
        return self.fn_l2w_typed[t](data)

    def w2l_typed(self, data):
        ''' dispatched conversion '''
        t = type(data)
        assert t in self.fn_w2l_typed, "unhandled type of data: %s (%s)" % (
            str(data), str(type(data))
        )
        return self.fn_w2l_typed[t](data)

    def l2w_point(self, p: Point) -> Point:
        return Point(self.mx_p * p)

    def w2l_point(self, p: Point) -> Point:
        return Point(self.imx_p * p)

    def l2w_direction(self, d: Direction) -> Direction:
        return Direction(self.mx_d * d)

    def w2l_direction(self, d: Direction) -> Direction:
        return Direction(self.imx_d * d)

    def l2w_normal(self, n: Normal) -> Normal:
        return Normal(self.mx_n * n)

    def w2l_normal(self, n: Normal) -> Normal:
        return Normal(self.imx_n * n)

    def l2w_vector(self, v: Vector) -> Vec:
        return Vec(self.mx_d * v)

    def w2l_vector(self, v: Vector) -> Vec:
        return Vec(self.imx_d * v)

    def l2w_ray(self, ray: Ray) -> Ray:
        o = self.l2w_point(ray.o)
        d = self.l2w_direction(ray.d)
        if ray.max == float('inf'):
            l1 = ray.max
        else:
            l1 = (o - self.l2w_point(ray.o + ray.max * ray.d)).length
        return Ray(o=o, d=d, max_dist=l1)

    def w2l_ray(self, ray: Ray) -> Ray:
        o = self.w2l_point(ray.o)
        d = self.w2l_direction(ray.d)
        if ray.max == float('inf'):
            l1 = ray.max
        else:
            l1 = (o - self.w2l_point(ray.o + ray.max * ray.d)).length
        return Ray(o=o, d=d, max_dist=l1)

    def l2w_plane(self, plane: Plane) -> Plane:
        return Plane(o=self.l2w_point(plane.o), n=self.l2w_normal(plane.n))

    def w2l_plane(self, plane: Plane) -> Plane:
        return Plane(o=self.w2l_point(plane.o), n=self.w2l_normal(plane.n))

    def l2w_bmvert(self, bmv: BMVert) -> Point:
        return Point(self.mx_p * bmv.co)

    def w2l_bmevrt(self, bmv: BMVert) -> Point:
        return Point(self.imx_p * bmv.co)

    @staticmethod
    def to_bglMatrix(mat):
        # return bgl.Buffer(
        #     bgl.GL_FLOAT, len(mat)**2, [v for r in mat for v in r]
        # )
        return bgl.Buffer(bgl.GL_FLOAT, [len(mat), len(mat)], mat)

    def to_bglMatrix_Model(self):
        return self.to_bglMatrix(self.mx_p)

    def to_bglMatrix_Inverse(self):
        return self.to_bglMatrix(self.imx_p)

    def to_bglMatrix_Normal(self):
        return self.to_bglMatrix(self.mx_n)


class BBox:
    @stats_wrapper
    def __init__(self, from_bmverts=None, from_coords=None):
        if not (from_bmverts or from_coords):
            nan = float('nan')
            self.min = None
            self.max = None
            self.mx, self.my, self.mz = nan, nan, nan
            self.Mx, self.My, self.Mz = nan, nan, nan
            return
        if from_bmverts:
            from_coords = [bmv.co for bmv in from_bmverts]
        else:
            from_coords = list(from_coords)
        mx, my, mz = from_coords[0]
        Mx, My, Mz = mx, my, mz
        for x, y, z in from_coords:
            mx, my, mz = min(mx, x), min(my, y), min(mz, z)
            Mx, My, Mz = max(Mx, x), max(My, y), max(Mz, z)
        self.min = Point((mx, my, mz))
        self.max = Point((Mx, My, Mz))
        self.mx, self.my, self.mz = mx, my, mz
        self.Mx, self.My, self.Mz = Mx, My, Mz
        self.min_dim = min(
            self.Mx - self.mx,
            self.My - self.my,
            self.Mz - self.mz
        )
        self.max_dim = max(
            self.Mx - self.mx,
            self.My - self.my,
            self.Mz - self.mz
        )

    @staticmethod
    def merge(boxes):
        return BBox(from_coords=[Point(p) for b in boxes for p in [
            (b.mx, b.my, b.mz),
            (b.Mx, b.My, b.Mz)
        ]])

    def __str__(self):
        s = '(%0.4f, %0.4f, %0.4f)'
        return '<BBox %s, %s>' % (
            s % (self.mx, self.my, self.mz),
            s % (self.Mx, self.My, self.Mz),
        )

    def __repr__(self):
        return self.__str__()

    def Point_within(self, point: Point, margin=0):
        if not self.min or not self.max:
            return True
        return all(
            m - margin <= v and v <= M + margin
            for (v, m, M) in zip(point, self.min, self.max)
        )

    def get_min_dimension(self):
        return self.min_dim

    def get_max_dimension(self):
        return self.max_dim


class Accel2D:
    bin_cols = 20
    bin_rows = 20

    class SimpleVert:
        def __init__(self, co):
            self.co = co
            self.is_valid = True

    class SimpleEdge:
        def __init__(self, verts):
            self.verts = verts
            self.p0 = verts[0].co
            self.p1 = verts[1].co
            self.v01 = self.p1 - self.p0
            self.l = self.v01.length
            self.d01 = self.v01 / max(self.l, 0.00000001)
            self.is_valid = True
        def closest(self, p):
            v0p = p - self.p0
            d = self.d01.dot(v0p)
            return self.p0 + self.d01 * mid(d, 0, self.l)

    @staticmethod
    def simple_verts(verts, Point_to_Point2D):
        verts = [Accel2D.SimpleVert(v) for v in verts]
        return Accel2D(verts, [], [], Point_to_Point2D)

    @staticmethod
    def simple_edges(edges, Point_to_Point2D):
        edges = [Accel2D.SimpleEdge((Accel2D.SimpleVert(v0), Accel2D.SimpleVert(v1))) for (v0, v1) in edges]
        verts = [v for e in edges for v in e.verts]
        return Accel2D(verts, edges, [], Point_to_Point2D)

    @profiler.profile
    def __init__(self, verts, edges, faces, Point_to_Point2D):
        self.verts = list(verts) if verts else []
        self.edges = list(edges) if edges else []
        self.faces = list(faces) if faces else []
        self.Point_to_Point2D = Point_to_Point2D
        self.vert_type = type(self.verts[0]) if self.verts else None
        self.edge_type = type(self.edges[0]) if self.edges else None
        self.face_type = type(self.faces[0]) if self.faces else None
        self.bins = {}

        self.v2Ds = [Point_to_Point2D(v.co) for v in verts]
        self.map_v_v2D = {v: v2d for (v, v2d) in zip(verts, self.v2Ds)}
        if self.v2Ds:
            self.min = Point2D((
                min(x - 0.001 for (x, _) in self.v2Ds),
                min(y - 0.001 for (_, y) in self.v2Ds)
            ))
            self.max = Point2D((
                max(x + 0.001 for (x, _) in self.v2Ds),
                max(y + 0.001 for (_, y) in self.v2Ds)
            ))
        else:
            self.min = Point2D((0, 0))
            self.max = Point2D((1, 1))
        self.size = self.max - self.min

        pr = profiler.start('inserting verts')
        for (v, v2d) in zip(verts, self.v2Ds):
            i, j = self.compute_ij(v2d)
            self._put(i, j, v)
        pr.done()

        pr = profiler.start('inserting edges')
        for e in edges:
            v0, v1 = self.map_v_v2D[e.verts[0]], self.map_v_v2D[e.verts[1]]
            ij0, ij1 = self.compute_ij(v0), self.compute_ij(v1)
            mini, minj = min(ij0[0], ij1[0]), min(ij0[1], ij1[1])
            maxi, maxj = max(ij0[0], ij1[0]), max(ij0[1], ij1[1])
            for i in range(mini, maxi + 1):
                for j in range(minj, maxj + 1):
                    self._put(i, j, e)
            # v0,v1 = e.verts
            # self._put_edge(e, self.map_v_v2D[v0], self.map_v_v2D[v1])
        pr.done()

        pr = profiler.start('inserting faces')
        for f in faces:
            v2ds = [self.map_v_v2D[v] for v in f.verts]
            if not v2ds:
                continue
            ijs = list(map(self.compute_ij, v2ds))
            mini, minj = min(i for (i, j) in ijs), min(j for (i, j) in ijs)
            maxi, maxj = max(i for (i, j) in ijs), max(j for (i, j) in ijs)
            for i in range(mini, maxi + 1):
                for j in range(minj, maxj + 1):
                    self._put(i, j, f)
            # v0 = v2ds[0]
            # for v1,v2 in zip(v2ds[1:-1],v2ds[2:]):
            #    self._put_face(f, v0, v1, v2)
        pr.done()

    @profiler.profile
    def compute_ij(self, v2d):
        n = v2d - self.min
        i = int(self.bin_cols * n.x / self.size.x)
        j = int(self.bin_rows * n.y / self.size.y)
        i = max(0, min(self.bin_cols - 1, i))
        j = max(0, min(self.bin_rows - 1, j))
        return (i, j)

    def _put(self, i, j, o):
        t = (i, j)
        if t not in self.bins: self.bins[t] = set()
        self.bins[t].add(o)

    def _get(self, i, j):
        t = (i, j)
        return self.bins.get(t, set())

    @profiler.profile
    def clean_invalid(self):
        self.bins = {
            t: {o for o in objs if o.is_valid}
            for (t, objs) in self.bins.items()
        }

    def _put_edge(self, e, v0, v1, depth=0):
        i0, j0 = self.compute_ij(v0)
        i1, j1 = self.compute_ij(v1)
        if i0 == i1 and j0 == j1:
            self._put(i0, j0, e)
        elif i0 == i1:
            i = i0
            for j in range(min(j0, j1), max(j0, j1) + 1):
                self._put(i, j, e)
        elif j0 == j1:
            j = j0
            for i in range(min(i0, i1), max(i0, i1) + 1):
                self._put(i, j, e)
        elif depth == 6:
            self._put(i0, j0, e)
            self._put(i1, j1, e)
        else:
            vm = v0 + (v1 - v0) / 2
            self._put_edge(e, v0, vm, depth=depth + 1)
            self._put_edge(e, vm, v1, depth=depth + 1)

    def _put_face(self, f, v0, v1, v2, depth=0):
        i0, j0 = self.compute_ij(v0)
        i1, j1 = self.compute_ij(v1)
        i2, j2 = self.compute_ij(v2)
        if i0 == i1 and i0 == i2 and j0 == j1 and j0 == j2:
            self._put(i0, j0, f)
        elif i0 == i1 and j0 == j1:
            self._put_edge(f, v0, v2, depth=depth)
        elif i0 == i2 and j0 == j2:
            self._put_edge(f, v0, v1, depth=depth)
        elif i1 == i2 and j1 == j2:
            self._put_edge(f, v1, v2, depth=depth)
        elif depth == 6:
            self._put(i0, j0, f)
            self._put(i1, j1, f)
            self._put(i2, j2, f)
        else:
            v01 = v0 + (v1 - v0) / 2
            v12 = v1 + (v2 - v1) / 2
            v20 = v2 + (v0 - v2) / 2
            self._put_face(f, v0, v01, v20, depth=depth + 1)
            self._put_face(f, v1, v12, v01, depth=depth + 1)
            self._put_face(f, v2, v20, v12, depth=depth + 1)

    @profiler.profile
    def get(self, v2d, within):
        delta = Vec2D((within, within))
        i0, j0 = self.compute_ij(v2d - delta)
        i1, j1 = self.compute_ij(v2d + delta)
        l = set()
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                l |= self._get(i, j)
        return {v for v in l if v.is_valid}

    @profiler.profile
    def get_verts(self, v2d, within):
        vert_type = self.vert_type
        return {g for g in self.get(v2d, within) if type(g) is vert_type}

    @profiler.profile
    def get_edges(self, v2d, within):
        edge_type = self.edge_type
        return {g for g in self.get(v2d, within) if type(g) is edge_type}

    @profiler.profile
    def get_faces(self, v2d, within):
        face_type = self.face_type
        return {g for g in self.get(v2d, within) if type(g) is face_type}

    def nearest_vert(self, v2d):
        Point_to_Point2D = self.Point_to_Point2D
        vert_type = self.vert_type
        x,y = v2d
        i, j = self.compute_ij(v2d)
        working = {(i,j)}
        touched = set()
        bv,bd = None,0
        while working:
            binij = working.pop()
            if binij in touched: continue
            touched.add(binij)
            i,j = binij
            if i < 0 or j < 0 or i >= self.bin_cols or j >= self.bin_rows: continue
            mx,my = self.min + Vec2D((self.size.x * i / self.bin_cols, self.size.y * j / self.bin_rows))
            Mx,My = self.min + Vec2D((self.size.x * (i+1) / self.bin_cols, self.size.y * (j+1) / self.bin_rows))
            closest = Point2D((mid(x, mx, Mx), mid(y, my, My)))
            d = (v2d - closest).length
            if bv and d > bd:
                # we have seen a vert that is closer than anything in this bin
                continue
            for v in self._get(i, j):
                if type(v) is not vert_type: continue
                d = (Point_to_Point2D(v.co) - v2d).length
                if bv and d > bd: continue
                bv,bd = v,d
            working |= {(i-1,j-1), (i,j-1), (i+1,j-1), (i-1,j), (i+1,j), (i-1,j+1), (i,j+1), (i+1,j+1)}
        return Point_to_Point2D(bv.co)

    @profiler.profile
    def nearest_face(self, v2d):
        ########################################
        # XXXX: ONLY FINDING FACE UNDER V2D!!! #
        ########################################

        @profiler.profile
        def intersect_face(bmf):
            pts = [Point_to_Point2D(bmv.co) for bmv in bmf.verts]
            pts = [pt for pt in pts if pt]
            pt0 = pts[0]
            for pt1, pt2 in zip(pts[1:-1], pts[2:]):
                if intersect_point_tri(v2d, pt0, pt1, pt2):
                    return True
            return False

        Point_to_Point2D = self.Point_to_Point2D
        face_type = self.face_type
        i, j = self.compute_ij(v2d)
        faces = [bmf for bmf in self._get(i, j) if type(bmf) is face_type]
        for bmf in faces:
            if not bmf.is_valid:
                continue
            if intersect_face(bmf):
                return bmf
        return None


def invert_matrix(mat):
    smat,d = str(mat),invert_matrix.__dict__
    if smat not in d:
        if len(d) > 1000: d.clear()
        d[smat] = mat.inverted()
    return d[smat]

def matrix_normal(mat):
    smat,d = str(mat),matrix_normal.__dict__
    if smat not in d:
        if len(d) > 1000: d.clear()
        d[smat] = invert_matrix(mat).transposed().to_3x3()
    return d[smat]



def get_path_length(verts):
    '''
    sum up the length of a string of vertices
    '''
    if len(verts) < 2:
        return 0
    l_tot = 0
    for i in range(0,len(verts)-1):
        d = verts[i+1] - verts[i]
        l_tot += d.length
    return l_tot

def space_evenly_on_path(verts, edges, segments, shift = 0, debug = False):  #prev deved for Open Dental CAD
    '''
    Gives evenly spaced location along a string of verts
    Assumes that nverts > nsegments
    Assumes verts are ORDERED along path
    Assumes edges are ordered coherently
    Yes these are lazy assumptions, but the way I build my data
    guarantees these assumptions so deal with it.

    args:
        verts - list of vert locations type Mathutils.Vector
        eds - list of index pairs type tuple(integer) eg (3,5).
              should look like this though [(0,1),(1,2),(2,3),(3,4),(4,0)]
        segments - number of segments to divide path into
        shift - for cyclic verts chains, shifting the verts along
                the loop can provide better alignment with previous
                loops.  This should be -1 to 1 representing a percentage of segment length.
                Eg, a shift of .5 with 8 segments will shift the verts 1/16th of the loop length

    return
        new_verts - list of new Vert Locations type list[Mathutils.Vector]
    '''

    if len(verts) < 2:
        print('this is crazy, there are not enough verts to do anything!')
        return verts

    if segments >= len(verts):
        print('more segments requested than original verts')


    #determine if cyclic or not, first vert same as last vert
    if 0 in edges[-1]:
        cyclic = True

    else:
        cyclic = False
        #zero out the shift in case the vert chain insn't cyclic
        if shift != 0: #not PEP but it shows that we want shift = 0
            print('not shifting because this is not a cyclic vert chain')
            shift = 0

    #calc_length
    arch_len = 0
    cumulative_lengths = [0]#TODO, make this the right size and dont append
    for i in range(0,len(verts)-1):
        v0 = verts[i]
        v1 = verts[i+1]
        V = v1-v0
        arch_len += V.length
        cumulative_lengths.append(arch_len)

    if cyclic:
        v0 = verts[-1]
        v1 = verts[0]
        V = v1-v0
        arch_len += V.length
        cumulative_lengths.append(arch_len)
        #print(cumulative_lengths)

    #identify vert indicies of import
    #this will be the largest vert which lies at
    #no further than the desired fraction of the curve

    #initialze new vert array and seal the end points
    if cyclic:
        new_verts = [[None]]*(segments)
        #new_verts[0] = verts[0]

    else:
        new_verts = [[None]]*(segments + 1)
        new_verts[0] = verts[0]
        new_verts[-1] = verts[-1]


    n = 0 #index to save some looping through the cumulative lengths list
          #now we are leaving it 0 becase we may end up needing the beginning of the loop last
          #and if we are subdividing, we may hit the same cumulative lenght several times.
          #for now, use the slow and generic way, later developsomething smarter.
    for i in range(0,segments- 1 + cyclic * 1):
        desired_length_raw = (i + 1 + cyclic * -1)/segments * arch_len + shift * arch_len / segments
        #print('the length we desire for the %i segment is %f compared to the total length which is %f' % (i, desired_length_raw, arch_len))
        #like a mod function, but for non integers?
        if desired_length_raw > arch_len:
            desired_length = desired_length_raw - arch_len
        elif desired_length_raw < 0:
            desired_length = arch_len + desired_length_raw #this is the end, + a negative number
        else:
            desired_length = desired_length_raw

        #find the original vert with the largets legnth
        #not greater than the desired length
        #I used to set n = J after each iteration
        for j in range(n, len(verts)+1):

            if cumulative_lengths[j] > desired_length:
                #print('found a greater length at vert %i' % j)
                #this was supposed to save us some iterations so that
                #we don't have to start at the beginning each time....
                #if j >= 1:
                    #n = j - 1 #going one back allows us to space multiple verts on one edge
                #else:
                    #n = 0
                break

        extra = desired_length - cumulative_lengths[j-1]
        if j == len(verts):
            new_verts[i + 1 + cyclic * -1] = verts[j-1] + extra * (verts[0]-verts[j-1]).normalized()
        else:
            new_verts[i + 1 + cyclic * -1] = verts[j-1] + extra * (verts[j]-verts[j-1]).normalized()

    eds = []

    for i in range(0,len(new_verts)-1):
        eds.append((i,i+1))
    if cyclic:
        #close the loop
        eds.append((i+1,0))
    if debug:
        print(cumulative_lengths)
        print(arch_len)
        print(eds)

    return new_verts, eds



def delta_angles(vec_about, l_vecs):
    '''
    will find the difference betwen each element and the next element in the list
    this is a foward difference.  Eg delta[n] = item[n+1] - item[n]

    deltas should add up to 2*pi
    '''

    v0 = l_vecs[0]
    l_angles = [0] + [vector_angle_between(v0,v1,vec_about) for v1 in l_vecs[1:]]

    L = len(l_angles)

    deltas = [l_angles[n + 1] - l_angles[n] for n in range(0, L-1)] + [2*math.pi - l_angles[-1]]
    return deltas


# https://rosettacode.org/wiki/Determine_if_two_triangles_overlap#C.2B.2B
def triangle2D_det(p0, p1, p2):
    return p0.x * (p1.y - p2.y) + p1.x * (p2.y - p0.y) + p2.x * (p0.y - p1.y)


def triangle2D_boundary_collision_check(p0, p1, p2, eps):
    return triangle2D_det(p0, p1, p2) < eps


def triangle2D_collision_check(p0, p1, p2, eps):
    return triangle2D_det(p0, p1, p2) <= eps


def triangle2D_overlap(triangle0, triangle1, eps=0.0):
    # XXX: needs testing!
    _chk = triangle2D_collision_check

    def chk(e0, e1, p0, p1, p2):
        c = _chk(e0, e1, p0, eps)
        c &= _chk(e0, e1, p1, eps)
        c &= _chk(e0, e1, p2, eps)
        return c

    def chk_edges(a0, a1, a2, b0, b1, b2):
        c = chk(a0, a1, b0, b1, b2)
        c |= chk(a1, a2, b0, b1, b2)
        c |= chk(a2, a0, b0, b1, b2)
        return c

    a0, a1, a2 = triangle0
    b0, b1, b2 = triangle1
    h0 = chk_edges(a0, a1, a2, b0, b1, b2)
    h1 = chk_edges(b0, b1, b2, a0, a1, a2)
    return not (h0 or h1)


def triangle2D_area(p0, p1, p2):
    a = Vector((p0.x, p0.y, 0.0))
    b = Vector((p1.x, p1.y, 0.0))
    c = Vector((p2.x, p2.y, 0.0))
    return (b - a).cross(c - a).length / 2


def segment2D_intersection(a0, a1, b0, b1):
    # get distance from b0 to a0---a1
    dir_a0a1 = a1 - a0
    dist_a0a1 = max(0.00000001, dir_a0a1.length)
    dir_a0a1 /= dist_a0a1
    vec_a0b0 = b0 - a0
    closest_b0_a0a1 = a0 + dir_a0a1 * dir_a0a1.dot(vec_a0b0)
    pdir_a0a1_b0 = b0 - closest_b0_a0a1
    dist_a0a1_b0 = pdir_a0a1_b0.length
    if dist_a0a1_b0 == 0:
        # b0 is on a0-a1 line
        return b0
    pdir_a0a1_b0 /= dist_a0a1_b0
    dir_b0b1 = b1 - b0
    dist_b0b1 = max(0.00000001, dir_b0b1.length)
    dir_b0b1 /= dist_b0b1
    dot = dir_b0b1.dot(pdir_a0a1_b0)
    if abs(dot) <= 0.0000001:
        # a0-a1 and b0-b1 are nearly parallel
        return None
    dist_intersection_b0b1 = dist_a0a1_b0 / dot
    if dist_intersection_b0b1 < 0 or dist_intersection_b0b1 > dist_b0b1:
        return None
    intersection = b0 + dir_b0b1 * dist_intersection_b0b1
    # dist_intersection_a0a1 = dir_a0a1.dot(intersection - a0)
    # if dist_intersection_a0a1 < 0 or dist_intersection_a0a1 > dist_a0a1:
    #     return None
    return intersection


def clamp(v, min_v, max_v):
    return max(min_v, min(max_v, v))


def mid(v0, v1, v2):
    if v0 > v1:
        v0, v1 = v1, v0
    if v1 > v2:
        v1, v2 = v2, v1
    if v0 > v1:
        v0, v1 = v1, v0
    return v1


if __name__ == '__main__':
    # run tests
    p0 = Point((1, 2, 3))
    p1 = Point((0, 0, 1))
    v0 = Vec((1, 0, 0))
    r = Ray(p0, v0)
    mxt = XForm(Matrix.Translation((1, 2, 3)))
    mxr = XForm(Matrix.Rotation(0.1, 4, Vector((0, 0, 1))))
    mxtr = mxt * mxr

    print('')

    print(p1 - p0)
    print(p0 + v0)
    print(p0 * 2)  # should be able to do this??
    print(p0.copy())
    print(r)

    print("%s => %s" % (v0, mxt * v0))
    print("%s => %s" % (p0, mxt * p0))

    print("%s => %s" % (v0, mxr * v0))
    print("%s => %s" % (p0, mxr * p0))

    print('%s => %s => %s' % (r, mxtr * r, mxtr / (mxtr * r)))

    print(mxr)
    print(mxr.mx_p)
