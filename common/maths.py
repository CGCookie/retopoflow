import sys
import bpy
from mathutils import Matrix, Vector
from bmesh.types import BMVert


'''
The types below wrap the mathutils.Vector class, distinguishing among the
different types of geometric entities that are typically represented using
a vanilla Vector.
'''


class Vec(Vector):
    def __str__(self):
        return '<Vec (%0.4f, %0.4f, %0.4f)>' % (self.x,self.y,self.z)
    def as_vector(self): return Vector(self)
    def from_vector(self, v): self.x,self.y,self.z = v


class Point(Vector):
    def __str__(self):
        return '<Point (%0.4f, %0.4f, %0.4f)>' % (self.x,self.y,self.z)
    def __add__(self, other):
        t = type(other)
        if t is Direction:
            return Point((self.x+other.x,self.y+other.y,self.z+other.z))
        if t is Vector or t is Vec:
            return Point((self.x+other.x,self.y+other.y,self.z+other.z))
        assert False, "unhandled type of other: %s (%s)" % (str(other), str(t))
    def __radd__(self, other):
        return self.__add__(other)
    def __sub__(self, other):
        t = type(other)
        if t is Vector or t is Vec:
            return Point((self.x-other.x,self.y-other.y,self.z-other.z))
        elif t is Point:
            return Vector((self.x-other.x, self.y-other.y, self.z-other.z))
        assert False, "unhandled type of other: %s (%s)" % (str(other), str(t))
    def as_vector(self): return Vector(self)
    def from_vector(self, v): self.x,self.y,self.z = v


class Direction(Vector):
    def __init__(self, t=None):
        if t is not None: self.from_vector(t)
    def __str__(self):
        return '<Direction (%0.4f, %0.4f, %0.4f)>' % (self.x,self.y,self.z)
    def __mul__(self, other):
        t = type(other)
        if t is float or t is int:
            return Vector((other * self.x, other * self.y, other * self.z))
        assert False, "unhandled type of other: %s (%s)" % (str(other), str(t))
    def __rmul__(self, other):
        return self.__mul__(other)
    def normalize(self):
        super().normalize()
        return self
    def as_vector(self): return Vector(self)
    def from_vector(self, v):
        self.x,self.y,self.z = v
        self.normalize()


class Normal(Vector):
    def __init__(self, t=None):
        if t is not None: self.from_vector(t)
    def __str__(self):
        return '<Normal (%0.4f, %0.4f, %0.4f)>' % (self.x,self.y,self.z)
    def __mul__(self, other):
        t = type(other)
        if t is float or t is int:
            return Vector((other * self.x, other * self.y, other * self.z))
        assert False, "unhandled type of other: %s (%s)" % (str(other), str(t))
    def __rmul__(self, other):
        return self.__mul__(other)
    def normalize(self):
        super().normalize()
        return self
    def as_vector(self): return Vector(self)
    def from_vector(self, v):
        self.x,self.y,self.z = v
        self.normalize()


class Ray:
    def __init__(self, o:Point, d:Direction, min_dist:float=0.0, max_dist:float=sys.float_info.max):
        o,d = Point(o),Direction(d)
        o0,o1 = o + min_dist * d, o + max_dist * d
        
        self.o = o0
        self.d = d
        self.max = (o1-o0).length
    
    def __str__(self):
        return '<Ray (%0.4f, %0.4f, %0.4f)->(%0.4f, %0.4f, %0.4f)>' % (self.o.x,self.o.y,self.o.z,self.d.x,self.d.y,self.d.z)
    
    def eval(self, t:float):
        return self.o + max(self.min, min(self.max, t)) * self.d
    
    @classmethod
    def from_screenspace(cls, pos:Vector):
        # convert pos in screenspace to ray
        pass


class XForm:
    @staticmethod
    def get_mats(mx:Matrix):
        smat,d = str(mx),XForm.get_mats.__dict__
        if smat not in d:
            m = {
                'mx_p': None, 'imx_p': None,
                'mx_d': None, 'imx_d': None,
                'mx_n': None, 'imx_n': None
            }
            m['mx_p']  = mx
            m['imx_p'] = mx.inverted()
            m['mx_d']  = mx.to_3x3()
            m['imx_d'] = m['mx_d'].inverted()
            m['mx_n']  = m['imx_d'].transposed()
            m['imx_n'] = m['mx_d'].transposed()
            d[smat] = m
        return d[smat]
    
    def __init__(self, mx:Matrix=None):
        if mx is None: mx = Matrix()
        self.assign(mx)
    
    def assign(self, mx):
        if type(mx) is XForm: return self.assign(mx.mx_p)
        
        mats = XForm.get_mats(mx)
        self.mx_p,self.imx_p = mats['mx_p'],mats['imx_p']
        self.mx_d,self.imx_d = mats['mx_d'],mats['imx_d']
        self.mx_n,self.imx_n = mats['mx_n'],mats['imx_n']
        
        self.fn_l2w_typed = {
            Point:      lambda x: self.l2w_point(x),
            Direction:  lambda x: self.l2w_direction(x),
            Normal:     lambda x: self.l2w_normal(x),
            Vec:        lambda x: self.l2w_vector(x),
            Vector:     lambda x: self.l2w_vector(x),
            Ray:        lambda x: self.l2w_ray(x),
            BMVert:     lambda x: self.l2w_bmvert(x),
        }
        self.fn_w2l_typed = {
            Point:      lambda x: self.w2l_point(x),
            Direction:  lambda x: self.w2l_direction(x),
            Normal:     lambda x: self.w2l_normal(x),
            Vec:        lambda x: self.w2l_vector(x),
            Vector:     lambda x: self.w2l_vector(x),
            Ray:        lambda x: self.w2l_ray(x),
            BMVert:     lambda x: self.w2l_bmvert(x),
        }
        return self
    
    def __str__(self):
        v = tuple(x for r in self.mx_p for x in r)
        return '<XForm (%0.4f, %0.4f, %0.4f, %0.4f)\n' \
               '       (%0.4f, %0.4f, %0.4f, %0.4f)\n' \
               '       (%0.4f, %0.4f, %0.4f, %0.4f)\n' \
               '       (%0.4f, %0.4f, %0.4f, %0.4f)>' % v
    
    
    def __mul__(self, other):
        t = type(other)
        if t is XForm:  return XForm(self.mx_p * other.mx_p)
        if t is Matrix: return XForm(self.mx_p * other)
        return self.l2w_typed(other)
    
    def __imul__(self, other):
        self.assign(self.mx_p * (other.mx_p if type(other) is XForm else other))
    
    def __truediv__(self, other):
        return self.w2l_typed(other)
    
    
    def l2w_typed(self, data):
        ''' dispatched conversion '''
        t = type(data)
        assert t in self.fn_l2w_typed, "unhandled type of data: %s (%s)" % (str(data), str(type(data)))
        return self.fn_l2w_typed[t](data)
    def w2l_typed(self, data):
        ''' dispatched conversion '''
        t = type(data)
        assert t in self.fn_w2l_typed, "unhandled type of data: %s (%s)" % (str(data), str(type(data)))
        return self.fn_w2l_typed[t](data)
    
    def l2w_point(self, p:Point)->Point: return Point(self.mx_p * p)
    def w2l_point(self, p:Point)->Point: return Point(self.imx_p * p)
    
    def l2w_direction(self, d:Direction)->Direction: return Direction(self.mx_d * d)
    def w2l_direction(self, d:Direction)->Direction: return Direction(self.imx_d * d)
    
    def l2w_normal(self, n:Normal)->Normal: return Normal(self.mx_n * n)
    def w2l_normal(self, n:Normal)->Normal: return Normal(self.imx_n * n)
    
    def l2w_vector(self, v:Vector)->Vec: return Vec(self.mx_d * v)
    def w2l_vector(self, v:Vector)->Vec: return Vec(self.imx_d * v)
    
    def l2w_ray(self, ray:Ray)->Ray:
        o0 = self.l2w_point(ray.o)
        o1 = self.l2w_point(ray.o + ray.max * ray.d)
        d  = self.l2w_direction(ray.d)
        return Ray(o=o0, d=d, max_dist=(o1-o0).length)
    def w2l_ray(self, ray:Ray)->Ray:
        o0 = self.w2l_point(ray.o)
        o1 = self.w2l_point(ray.o + ray.max * ray.d)
        d  = self.w2l_direction(ray.d)
        return Ray(o=o0, d=d, max_dist=(o1-o0).length)
    
    def l2w_bmvert(self, bmv:BMVert)->Point: return Point(self.mx_p * bmv.co)
    def w2l_bmevrt(self, bmv:BMVert)->Point: return Point(self.imx_p * bmv.co)
    


if __name__ == '__main__':
    # run tests
    p0 = Point((1,2,3))
    p1 = Point((0,0,1))
    v0 = Vec((1,0,0))
    r = Ray(p0, v0)
    mxt = XForm(Matrix.Translation((1,2,3)))
    mxr = XForm(Matrix.Rotation(0.1, 4, Vector((0,0,1))))
    mxtr = mxt * mxr

    print('')

    print(p1 - p0)
    print(p0 + v0)
    print(p0*2) # should be able to do this??
    print(p0.copy())
    print(r)

    print("%s => %s" % (v0, mxt * v0))
    print("%s => %s" % (p0, mxt * p0))

    print("%s => %s" % (v0, mxr * v0))
    print("%s => %s" % (p0, mxr * p0))

    print('%s => %s => %s' % (r, mxtr * r, mxtr / (mxtr * r)))

    print(mxr)
    print(mxr.mx_p)

