'''
Copyright (C) 2014 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

# System imports
import os
import sys
import copy
import itertools
import math
import time
from mathutils import Vector, Quaternion, Matrix
from mathutils.geometry import intersect_point_line, intersect_line_plane

# Blender imports
import blf
import bmesh
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d, region_2d_to_origin_3d

# Common imports
from . import common_utilities
from .common_utilities import dprint



def blender_bezier_to_even_points(b_ob, dist):
    
    mx = b_ob.matrix_world
    paths = []
    for spline in b_ob.data.splines:
        total_verts = []
        pregv = None
        for bp0,bp1 in zip(spline.bezier_points[:-1],spline.bezier_points[1:]):
            p0 = pregv if pregv else mx * bp0.co
            p1 = mx * bp0.handle_right
            p2 = mx * bp1.handle_left
            p3 = mx * bp1.co
            
            points = cubic_bezier_points_dist(p0, p1, p2, p3, dist, first=True)
            total_verts.extend(points)
            
            L = common_utilities.get_path_length(total_verts)
            n = round(L/dist)
            new_verts = common_utilities.space_evenly_on_path(total_verts, [(0,1),(1,2)], n, 0)
        paths.append(new_verts)
        
    return(paths)
             
def quadratic_bezier_weights(t):
    t0,t1 = t,(1-t)
    b0 = t1*t1
    b1 = 2*t0*t1
    b2 = t0*t0
    return (b0,b1,b2)

def cubic_bezier_weights(t):
    t0,t1 = t,(1-t)
    b0 = t1*t1*t1
    b1 = 3*t0*t1*t1
    b2 = 3*t0*t0*t1
    b3 = t0*t0*t0
    return (b0,b1,b2,b3)

def quadratic_bezier_blend_t(v0, v1, v2, t):
    b0,b1,b2 = quadratic_bezier_weights(t)
    return v0*b0 + v1*b1 + v2*b2

def quadratic_bezier_blend_weights(v0, v1, v2, weights):
    b0,b1,b2 = weights
    return v0*b0 + v1*b1 + v2*b2

def cubic_bezier_blend_t(v0, v1, v2, v3, t):
    b0,b1,b2,b3 = cubic_bezier_weights(t)
    return v0*b0 + v1*b1 + v2*b2 + v3*b3

def cubic_bezier_blend_weights(v0, v1, v2, v3, weights):
    b0,b1,b2,b3 = weights
    return v0*b0 + v1*b1 + v2*b2 + v3*b3

#http://en.wikipedia.org/wiki/De_Casteljau's_algorithm
def cubic_bezier_decasteljau_subdivide(p0,p1,p2,p3):
    q0,q1,q2 = (p0+p1)/2, (p1+p2)/2, (p2+p3)/2
    r0,r1    = (q0+q1)/2, (q1+q2)/2
    s        = (r0+r1)/2
    return [(p0,q0,r0,s),(s,r1,q2,p3)]

def cubic_bezier_length(p0, p1, p2, p3, threshold=0.05):
    '''
    compute (approximate) length of cubic bezier spline
    if end points of spline are "close enough", approximate curve length as distance between end points
    otherwise, subdivide spline return the sum of their recursively-computed lengths
    '''
    l = (p3-p0).length
    if l < threshold: return l
    subd = cubic_bezier_decasteljau_subdivide(p0,p1,p2,p3)
    return sum(cubic_bezier_length(*seg) for seg in subd)

def cubic_bezier_derivative(p0, p1, p2, p3, t):
    q0,q1,q2 = 3*(p1-p0),3*(p2-p1),3*(p3-p2)
    return quadratic_bezier_blend_t(q0, q1, q2, t)

def cubic_bezier_points_dist(p0, p1, p2, p3, dist, first=True):
    '''
    tessellates bezier into pts that are approx dist apart
    '''
    pts = [p0] if first else []
    if (p3-p0).length < dist:
        pts += [p3]
    else:
        subd = cubic_bezier_decasteljau_subdivide(p0,p1,p2,p3)
        pts += [p for seg in subd for p in cubic_bezier_points_dist(seg[0],seg[1],seg[2],seg[3], dist, first=False)]
    return pts

def cubic_bezier_find_closest_t_approx(p0, p1, p2, p3, p, max_depth=8, steps=10):
    '''
    find t that approximately returns p
    returns (t,dist)
    '''
    
    t0,t1 = 0,1
    for depth in range(max_depth):
        ta = t0
        td = (t1-t0)/steps
        l_t = [ta+td*i for i in range(steps+1)]
        min_t,min_d = -1,0
        for t in l_t:
            bpt = cubic_bezier_blend_t(p0,p1,p2,p3,t)
            d   = (bpt-p).length
            if min_t == -1 or d < min_d:
                min_t,min_d = t,d
        t0,t1 = max(t0,min_t-td),min(t1,min_t+td)
    return (min_t,min_d)

def cubic_bezier_find_closest_t_approx_distance(p0,p1,p2,p3, dist, threshold=0.1):
    def find_t(p0,p1,p2,p3,d,t0,t1,threshold):
        if d <= 0: return (0,0)
        l03 = (p0-p3).length
        l0123 = (p0-p1).length + (p1-p2).length + (p2-p3).length
        if l03/l0123 > (1-threshold):
            # close enough to approx as line
            if l03 < d:
                return (l03, t1-t0)
            return (d, (t1-t0)*(d/l03))
        t05 = (t0+t1)/2
        subd = cubic_bezier_decasteljau_subdivide(p0,p1,p2,p3)
        dret0,tret0 = find_t(subd[0][0], subd[0][1], subd[0][2], subd[0][3], d, t0, t05, threshold)
        dret1,tret1 = find_t(subd[1][0], subd[1][1], subd[1][2], subd[1][3], d-dret0, t05, t1, threshold)
        return (dret1, tret0+tret1)
    dret,tret = find_t(p0,p1,p2,p3,dist,0,1,threshold)
    return tret
    
def cubic_bezier_t_of_s(p0,p1,p2,p3, steps = 100):
    '''
    returns a dictionary mapping of pathlen values to t values
    approximated at steps along the curve.  Dumber method than
    the decastelejue subdivision.
    '''
    s_t_map = {}
    s_t_map[0] = 0
    vi0 = p0
    cumul_length = 0      
    for i in range(1,steps+1):
        t = i/steps
        weights = cubic_bezier_weights(i/steps)
        vi1 = cubic_bezier_blend_weights(p0, p1, p2, p3, weights)    
        cumul_length += (vi1 - vi0).length
        s_t_map[cumul_length] = t
        vi0 = vi1
        
    return s_t_map

def cubic_bezier_t_of_s_dynamic(p0,p1,p2,p3, initial_step = 50):
    '''
    returns a dictionary mapping of arclen values to t values
    approximated at steps along the curve.  Dumber method than
    the decastelejue subdivision.
    '''
    s_t_map = {}
    s_t_map[0] = 0
    
    pi0 = p0
    cumul_length = 0
    
    iters = 0
    dt = 1/initial_step
    t = dt
    while t < 1  and iters < 1000:
        iters += 1
        
        weights = cubic_bezier_weights(t)
        pi1 = cubic_bezier_blend_weights(p0, p1, p2, p3, weights)
        dist_traveled = (pi1 - pi0).length
        if dist_traveled == 0.0:
            # prevent division by zero when
            # bezier has zero length
            return s_t_map
        cumul_length += dist_traveled
        
        v_num = dist_traveled / dt
        v_cls = cubic_bezier_derivative(p0, p1, p2, p3, t).length
        s_t_map[cumul_length] = t
        
        pi0 = pi1
        dt *= v_cls/v_num
        t += dt
        
        if iters == 1000:
            print('maxed iters')
    
    #take care of the last point
    weights = cubic_bezier_weights(1)
    pi1 = cubic_bezier_blend_weights(p0, p1, p2, p3, weights)    
    cumul_length += (pi1 - pi0).length
    s_t_map[cumul_length] = 1 
            
    dprint('initial dt %f, final dt %f' % (1/initial_step, dt), l=4)
    return s_t_map

def cubic_bezier_fit_value(l_v, l_t):
    def compute_error(v0,v1,v2,v3,l_v,l_t):
        return math.sqrt(sum((cubic_bezier_blend_t(v0,v1,v2,v3,t)-v)**2 for v,t in zip(l_v,l_t)))
    
    #########################################################
    # http://nbviewer.ipython.org/gist/anonymous/5688579
    
    # make the summation functions for A (16 of them)
    A_fns = [
        lambda l_t: sum([  2*t**0*(t-1)**6 for t in l_t]),
        lambda l_t: sum([ -6*t**1*(t-1)**5 for t in l_t]),
        lambda l_t: sum([  6*t**2*(t-1)**4 for t in l_t]),
        lambda l_t: sum([ -2*t**3*(t-1)**3 for t in l_t]),
        
        lambda l_t: sum([ -6*t**1*(t-1)**5 for t in l_t]),
        lambda l_t: sum([ 18*t**2*(t-1)**4 for t in l_t]),
        lambda l_t: sum([-18*t**3*(t-1)**3 for t in l_t]),
        lambda l_t: sum([  6*t**4*(t-1)**2 for t in l_t]),
        
        lambda l_t: sum([  6*t**2*(t-1)**4 for t in l_t]),
        lambda l_t: sum([-18*t**3*(t-1)**3 for t in l_t]),
        lambda l_t: sum([ 18*t**4*(t-1)**2 for t in l_t]),
        lambda l_t: sum([ -6*t**5*(t-1)**1 for t in l_t]),
        
        lambda l_t: sum([ -2*t**3*(t-1)**3 for t in l_t]),
        lambda l_t: sum([  6*t**4*(t-1)**2 for t in l_t]),
        lambda l_t: sum([ -6*t**5*(t-1)**1 for t in l_t]),
        lambda l_t: sum([  2*t**6*(t-1)**0 for t in l_t])
        ]
    
    # make the summation functions for b (4 of them)
    b_fns = [
        lambda l_t,l_v: sum([-2*v*t**0*(t-1)**3 for t,v in zip(l_t,l_v)]),
        lambda l_t,l_v: sum([ 6*v*t**1*(t-1)**2 for t,v in zip(l_t,l_v)]),
        lambda l_t,l_v: sum([-6*v*t**2*(t-1)**1 for t,v in zip(l_t,l_v)]),
        lambda l_t,l_v: sum([ 2*v*t**3*(t-1)**0 for t,v in zip(l_t,l_v)])
        ]
    
    # compute the data we will put into matrix A
    A_values = [fn(l_t) for fn in A_fns]
    # fill the A matrix with data
    A_matrix = Matrix(tuple(zip(*[iter(A_values)]*4)))
    try:
        A_inv    = A_matrix.inverted()
    except:
        return (float('inf'), l_v[0],l_v[0],l_v[0],l_v[0])
    
    # compute the data we will put into the b vector
    b_values = [fn(l_t, l_v) for fn in b_fns]
    # fill the b vector with data
    b_vector = Vector(b_values)
    
    # solve for the unknowns in vector x
    v0,v1,v2,v3 = A_inv * b_vector
    
    err = compute_error(v0,v1,v2,v3,l_v,l_t) / len(l_v)
    
    return (err,v0,v1,v2,v3)

def cubic_bezier_fit_points(l_co, error_scale, depth=0, t0=0, t3=1, allow_split=True, force_split=False):
    '''
    fits cubic bezier to given points
    returns list of tuples of (t0,t3,p0,p1,p2,p3)
    that best fits the given points l_co
    where t0 and t3 are the passed-in t0 and t3
    and p0,p1,p2,p3 are the control points of bezier
    '''
    assert l_co
    if len(l_co)<3:
        p0,p3 = l_co[0],l_co[-1]
        p12 = (p0+p3)/2
        return [(t0,t3,p0,p12,p12,p3)]
    l_d  = [0] + [(v0-v1).length for v0,v1 in zip(l_co[:-1],l_co[1:])]
    l_ad = [s for d,s in common_utilities.iter_running_sum(l_d)]
    dist = sum(l_d)
    if dist <= 0:
        print('cubic_bezier_fit_points: returning []')
        return [] #[(t0,t3,l_co[0],l_co[0],l_co[0],l_co[0])]
    l_t  = [ad/dist for ad in l_ad]
    
    ex,x0,x1,x2,x3 = cubic_bezier_fit_value([co[0] for co in l_co], l_t)
    ey,y0,y1,y2,y3 = cubic_bezier_fit_value([co[1] for co in l_co], l_t)
    ez,z0,z1,z2,z3 = cubic_bezier_fit_value([co[2] for co in l_co], l_t)
    tot_error = ex+ey+ez
    dprint('total error = %f (%f)' % (tot_error,error_scale), l=4)
    
    if not force_split:
        if tot_error < error_scale or depth == 4 or len(l_co)<=15 or not allow_split:
            p0,p1,p2,p3 = Vector((x0,y0,z0)),Vector((x1,y1,z1)),Vector((x2,y2,z2)),Vector((x3,y3,z3))
            return [(t0,t3,p0,p1,p2,p3)]
    
    # too much error in fit.  split sequence in two, and fit each sub-sequence
    
    # find a good split point
    ind_split = -1
    mindot = 1.0
    for ind in range(5,len(l_co)-5):
        if l_t[ind] < 0.4: continue
        if l_t[ind] > 0.6: break
        #if l_ad[ind] < 0.1: continue
        #if l_ad[ind] > dist-0.1: break
        
        v0 = l_co[ind-4]
        v1 = l_co[ind+0]
        v2 = l_co[ind+4]
        d0 = (v1-v0).normalized()
        d1 = (v2-v1).normalized()
        dot01 = d0.dot(d1)
        if ind_split==-1 or dot01 < mindot:
            ind_split = ind
            mindot = dot01
    
    if ind_split == -1:
        # did not find a good splitting point!
        p0,p1,p2,p3 = Vector((x0,y0,z0)),Vector((x1,y1,z1)),Vector((x2,y2,z2)),Vector((x3,y3,z3))
        return [(t0,t3,p0,p1,p2,p3)]
    
    l_co_left  = l_co[:ind_split]
    l_co_right = l_co[ind_split:]
    tsplit = ind_split / (len(l_co)-1)
    return cubic_bezier_fit_points(l_co_left, error_scale, depth=depth+1, t0=t0, t3=tsplit) + cubic_bezier_fit_points(l_co_right, error_scale, depth=depth+1, t0=tsplit, t3=t3)

def cubic_bezier_split(p0, p1, p2, p3, t_split, error_scale, tessellate=10):
    tm0 = t_split / tessellate
    tm1 = (1-t_split) / tessellate
    pts0 = [cubic_bezier_blend_t(p0,p1,p2,p3,tm0*i) for i in range(tessellate+1)]
    pts1 = [cubic_bezier_blend_t(p0,p1,p2,p3,t_split+tm1*i) for i in range(tessellate+1)]
    cb0 = cubic_bezier_fit_points(pts0, error_scale, allow_split=False)
    cb1 = cubic_bezier_fit_points(pts1, error_scale, allow_split=False)
    return [cb[0][2:] for cb in [cb0,cb1] if cb]

def cubic_bezier_surface_t(v00,v01,v02,v03, v10,v11,v12,v13, v20,v21,v22,v23, v30,v31,v32,v33, t02,t13):
    b00,b01,b02,b03 = cubic_bezier_weights(t02)
    b10,b11,b12,b13 = cubic_bezier_weights(t13)
    v0 = v00*b00*b10 + v01*b01*b10 + v02*b02*b10 + v03*b03*b10
    v1 = v10*b00*b11 + v11*b01*b11 + v12*b02*b11 + v13*b03*b11
    v2 = v20*b00*b12 + v21*b01*b12 + v22*b02*b12 + v23*b03*b12
    v3 = v30*b00*b13 + v31*b01*b13 + v32*b02*b13 + v33*b03*b13
    return v0+v1+v2+v3