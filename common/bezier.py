import math

def compute_quadratic_weights(t):
    t0,t1 = t,(1-t)
    return (t1*t1, 2*t0*t1, t0*t0)

def compute_cubic_weights(t):
    t0,t1 = t,(1-t)
    return (t1*t1*t1,3*t0*t1*t1,3*t0*t0*t1,t0*t0*t0)


class CubicBezier:
    def __init__(self, p0, p1, p2, p3):
        self.p0,self.p1,self.p2,self.p3 = p0,p1,p2,p3
    
    def copy(self):
        ''' shallow copy '''
        return CubicBezier(self.p0, self.p1, self.p2, self.p3)
    
    def eval(self, t):
        p0,p1,p2,p3 = self.p0,self.p1,self.p2,self.p3
        b0,b1,b2,b3 = compute_cubic_weights(t)
        return p0*b0 + p1*b1 + p2*b2 + p3*b3
    
    def eval_derivative(self, t):
        p0,p1,p2,p3 = self.p0,self.p1,self.p2,self.p3
        q0,q1,q2 = 3*(p1-p0),3*(p2-p1),3*(p3-p2)
        b0,b1,b2 = compute_quadratic_weights(t)
        return q0*b0 + q1*b1 + q2*b2
    
    def subdivide(self, iters=1):
        if iters == 0: return [self]
        # de casteljau subdivide
        p0,p1,p2,p3 = self.p0,self.p1,self.p2,self.p3
        q0,q1,q2 = (p0+p1)/2, (p1+p2)/2, (p2+p3)/2
        r0,r1    = (q0+q1)/2, (q1+q2)/2
        s        = (r0+r1)/2
        cb0,cb1 = CubicBezier(p0,q0,r0,s),CubicBezier(s,r1,q2,p3)
        if iters == 1: return [cb0, cb1]
        return cb0.subdivide(iters=iters-1) + cb1.subdivide(iters=iters-1)
    
    def compute_linearity(self, fn_dist):
        '''
        Estimating measure of linearity as ratio of distances
        of curve mid-point and mid-point of end control points
        over half the distance between end control points
          p1 _
            / \
           |   \
        p0 *    \   * p3
                 \_/
                 p2
        '''
        p0,p1,p2,p3 = self.p0,self.p1,self.p2,self.p3
        q0,q1,q2 = (p0+p1)/2, (p1+p2)/2, (p2+p3)/2
        r0,r1    = (q0+q1)/2, (q1+q2)/2
        s        = (r0+r1)/2
        m        = (p0+p3)/2
        d03 = fn_dist(p0,p3)
        dsm = fn_dist(s,m)
        return 2 * dsm / d03
        
    def subdivide_linesegments(self, fn_dist, max_linearity=None):
        if self.compute_linearity(fn_dist) < (max_linearity or 0.1): return [self]
        # de casteljau subdivide:
        p0,p1,p2,p3 = self.p0,self.p1,self.p2,self.p3
        q0,q1,q2 = (p0+p1)/2, (p1+p2)/2, (p2+p3)/2
        r0,r1    = (q0+q1)/2, (q1+q2)/2
        s        = (r0+r1)/2
        cb0,cb1 = CubicBezier(p0,q0,r0,s),CubicBezier(s,r1,q2,p3)
        return cb0.subdivide_linesegments(max_linearity=max_linearity) + cb1.subdivide_linesegments(max_linearity=max_linearity)
    
    def length(self, fn_dist, max_linearity=None):
        l = self.subdivide_linesegments(max_linearity=max_linearity)
        return sum(fn_dist(cb.p0,cb.p3) for cb in l)


class CubicBezierSpline:
    
    @staticmethod
    def create_from_points(ps, fn_dist):
        '''
        Estimates best spline to fit given points
        '''
        return CubicBezierSpline()
    
    def __init__(self, cbs=None):
        if cbs is None: cbs = []
        if type(cbs) is CubicBezierSpline: cbs = [cb.copy() for cb in cbs.cbs]
        assert type(cbs) is list, "expected list"
        self.cbs = cbs
    
    def copy(self):
        return CubicBezierSpline(cbs=[cb.copy() for cb in self.cbs])
    
    def __add__(self, other):
        t = type(other)
        if t is CubicBezierSpline:
            return CubicBezierSpline(self.cbs + other.cbs)
        if t is CubicBezier:
            return CubicBezierSpline(self.cbs + [other])
        if t is list:
            return CubicBezierSpline(self.cbs + other)
        assert False, "unhandled type: %s (%s)" % (str(other),str(t))
    
    def __iadd__(self, other):
        t = type(other)
        if t is CubicBezierSpline:
            self.cbs += other.cbs
        elif t is CubicBezier:
            self.cbs += [other]
        elif t is list:
            self.cbs += other
        else:
            assert False, "unhandled type: %s (%s)" % (str(other),str(t))
    
    def __len__(self): return len(self.cbs)
    
    def eval(self, t):
        t = max(0.0, min(len(self), t))
        #assert t >= 0 and t <= len(self)
        idx = int(t)
        return self.cbs[min(len(self)-1,idx)].eval(t - idx)
    
    def length(self, fn_dist, max_linearity=None):
        return sum(cb.length(fn_dist, max_linearity=max_linearity) for cb in self.cbs)
    
    def subdivide_linesegments(self, fn_dist, max_linearity=None):
        return CubicBezierSpline(cbi
            for cb in self.cbs
            for cbi in cb.subdivide_linesegments(fn_dist, max_linearity=max_linearity)
            )


class GenVector(list):
    '''
    Generalized Vector, allows for some simple ordered items to be linearly combined
    which is useful for interpolating arbitrary points of Bezier Spline.
    '''
    def __mul__(self, scalar:float): #->GVector:
        for idx in range(len(self)):
            self[idx] *= scalar
        return self
    
    def __rmul__(self, scalar:float): #->GVector:
        return self.__mul__(scalar)
    
    def __add__(self, other:list): #->GVector:
        for idx in range(len(self)):
            self[idx] += other[idx]
        return self

if __name__ == '__main__':
    # run tests
    
    print('-'*50)
    l = GenVector([Vector((1,2,3)), 23])
    print(l)
    print(l * 2)
    print(4 * l)

    l2 = GenVector([Vector((0,0,1)), 10])
    print(l + l2)
    print(2 * l + l2 * 4)