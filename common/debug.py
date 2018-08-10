'''
Copyright (C) 2014 Plasmasolutions
software@plasmasolutions.de

Created by Thomas Beck
Donated to CGCookie and the world

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

'''
Note: not all of the following code was provided by Plasmasolutions
TODO: split into separate files?
'''

# System imports
import os
import sys
import inspect
import math
import time
import itertools
import linecache
import traceback
from datetime import datetime
from hashlib import md5

# Blender imports
import bmesh
import bpy
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d, region_2d_to_vector_3d,
    region_2d_to_location_3d, region_2d_to_origin_3d
)
from bpy.app.handlers import persistent
from mathutils import Vector, Matrix, Quaternion
from mathutils.geometry import (
    intersect_point_line, intersect_line_plane,
     intersect_line_line_2d, intersect_line_line,
    distance_point_to_plane,
)

from .globals import set_global, get_global
from .blender import show_blender_popup
from .hasher import Hasher


class Debugger:
    _error_level = 1
    _exception_count = 0

    def __init__(self):
        pass

    @staticmethod
    def set_error_level(l):
        Debugger._error_level = max(0, min(5, int(l)))

    @staticmethod
    def get_error_level():
        return Debugger._error_level

    @staticmethod
    def dprint(*objects, sep=' ', end='\n', file=sys.stdout, flush=True, l=2):
        if Debugger._error_level < l: return
        sobjects = sep.join(str(o) for o in objects)
        print(
            'DEBUG(%i): %s' % (l, sobjects),
            end=end, file=file, flush=flush
        )

    @staticmethod
    def dcallstack(l=2):
        ''' print out the calling stack, skipping the first (call to dcallstack) '''
        Debugger.dprint('Call Stack Dump:', l=l)
        for i, entry in enumerate(inspect.stack()):
            if i > 0:
                Debugger.dprint('  %s' % str(entry), l=l)

    # http://stackoverflow.com/questions/14519177/python-exception-handling-line-number
    @staticmethod
    def get_exception_info_and_hash():
        '''
        this function is a duplicate of the one above, but this will attempt
        to create a hash to make searching for duplicate bugs on github easier (?)
        '''

        exc_type, exc_obj, tb = sys.exc_info()
        pathabs, pathdir = os.path.abspath, os.path.dirname
        pathjoin, pathsplit = os.path.join, os.path.split
        base_path = pathabs(pathjoin(pathdir(__file__), '..'))

        hasher = Hasher()
        errormsg = ['EXCEPTION (%s): %s' % (exc_type, exc_obj)]
        hasher.add(errormsg[0])
        # errormsg += ['Base: %s' % base_path]

        etb = traceback.extract_tb(tb)
        pfilename = None
        for i,entry in enumerate(reversed(etb)):
            filename,lineno,funcname,line = entry
            if pfilename is None:
                # only hash in details of where the exception occurred
                hasher.add(os.path.split(filename)[1])
                # hasher.add(lineno)
                hasher.add(funcname)
                hasher.add(line.strip())
            if filename != pfilename:
                pfilename = filename
                if filename.startswith(base_path):
                    filename = '.../%s' % filename[len(base_path)+1:]
                errormsg += ['%s' % (filename, )]
            errormsg += ['%03d %04d:%s() %s' % (i, lineno, funcname, line.strip())]

        return ('\n'.join(errormsg), hasher.get_hash())

    @staticmethod
    def print_exception():
        Debugger._exception_count += 1
        errormsg, errorhash = Debugger.get_exception_info_and_hash()
        message = []
        message += ['Exception Info']
        message += ['- Time: %s' % datetime.today().isoformat(' ')]
        message += ['- Count: %d' % Debugger._exception_count]
        message += ['- Hash: %s' % str(errorhash)]
        message += ['- Info:']
        message += ['  - %s' % s for s in errormsg.splitlines()]
        message = '\n'.join(message)
        print('%s\n%s\n%s' % ('_' * 100, message, '^' * 100))
        logger = get_global('logger')
        if logger: logger.add(message)   # write error to log text object
        # if Debugger._exception_count < 10:
        #     show_blender_popup(
        #         message,
        #         title='Exception Info',
        #         icon='ERROR',
        #         wrap=240
        #     )
        return message

    # @staticmethod
    # def print_exception2():
    #     exc_type, exc_value, exc_traceback = sys.exc_info()
    #     print("*** print_tb:")
    #     traceback.print_tb(exc_traceback, limit=1, file=sys.stdout)
    #     print("*** print_exception:")
    #     traceback.print_exception(exc_type, exc_value, exc_traceback,
    #                               limit=2, file=sys.stdout)
    #     print("*** print_exc:")
    #     traceback.print_exc()
    #     print("*** format_exc, first and last line:")
    #     formatted_lines = traceback.format_exc().splitlines()
    #     print(formatted_lines[0])
    #     print(formatted_lines[-1])
    #     print("*** format_exception:")
    #     print(repr(traceback.format_exception(exc_type, exc_value,exc_traceback)))
    #     print("*** extract_tb:")
    #     print(repr(traceback.extract_tb(exc_traceback)))
    #     print("*** format_tb:")
    #     print(repr(traceback.format_tb(exc_traceback)))
    #     if exc_traceback:
    #         print("*** tb_lineno:", exc_traceback.tb_lineno)

debugger = Debugger()
dprint = debugger.dprint
set_global(debugger)



#######################################################################
# TODO: the following functions need to go somewhere more appropriate



def range_mod(m):
    for i in range(m): yield(i,(i+1)%m)

def iter_running_sum(lw):
    s = 0
    for w in lw:
        s += w
        yield (w,s)


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



def frange(start, end, stepsize):
    v = start
    if stepsize > 0:
        while v < end:
            yield v
            v += stepsize
    else:
        while v > end:
            yield v
            v += stepsize

def vector_compwise_mult(a,b):
    return Vector(ax*bx for ax,bx in zip(a,b))

def get_object_length_scale(o):
    sc = o.scale
    bbox = [vector_compwise_mult(sc,Vector(bpt)) for bpt in o.bound_box]
    l = (min(bbox)-max(bbox)).length
    return l

def simple_circle(x,y,r,res):
    '''
    args:
    x,y - center coordinate of cark
    r1 = radius of arc
    '''
    points = [Vector((0,0))]*res  #The arc + 2 arrow points

    for i in range(0,res):
        theta = i * 2 * math.pi / res
        x1 = math.cos(theta)
        y1 = math.sin(theta)

        points[i]=Vector((r * x1 + x, r * y1 + y))

    return(points)


def closest_t_and_distance_point_to_line_segment(p, p0, p1):
    v0p,v1p,v01 = p-p0, p-p1, p1-p0
    if v01.length == 0: return (0.0, v0p.length)
    if v01.dot(v0p) < 0: return (0.0, v0p.length)
    if v01.dot(v1p) > 0: return (1.0, v1p.length)
    v01n = v01.normalized()
    d_on_line = v01n.dot(v0p)
    p_on_line = p0 + v01n * d_on_line
    return (d_on_line/v01.length, (p-p_on_line).length)

def get_path_length(verts):
    '''
    sum up the length of a string of vertices
    '''
    l_tot = 0
    if len(verts) < 2:
        return 0

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

def zip_pairs(l):
    for p in zip(l, itertools.chain(l[1:],l[:1])):
        yield p

def closest_t_of_s(s_t_map, s):
    '''
    '''
    d0 = 0
    t = 1  #in case we don't find a d > s
    for i,d in enumerate(s_t_map):
        if d >= s:
            if i == 0:
                return 0
            t1 = s_t_map[d]
            t0 = s_t_map[d0]
            t = t0 + (t1-t0) * (s - d0)/(d-d0)
            return t
        else:
            d0 = d

    return t

def vector_angle_between(v0, v1, vcross):
    a = v0.angle(v1)
    d = v0.cross(v1).dot(vcross)
    return a if d<0 else 2*math.pi - a

def vector_angle_between_near_parallel(v0, v1, vcross):
    a = v0.angle(v1)
    d = v0.cross(v1).dot(vcross)
    return a if d>0 else 2*math.pi - a

def sort_objects_by_angles(vec_about, l_objs, l_vecs):
    if len(l_objs) <= 1:  return l_objs
    o0,v0 = l_objs[0],l_vecs[0]
    l_angles = [0] + [vector_angle_between(v0,v1,vec_about) for v1 in l_vecs[1:]]
    l_inds = sorted(range(len(l_objs)), key=lambda i: l_angles[i])
    return [l_objs[i] for i in l_inds]


#adapted from opendentalcad then to pie menus now here

def point_inside_loop2d(loop, point):
    '''
    args:
    loop: list of vertices representing loop
        type-tuple or type-Vector
    point: location of point to be tested
        type-tuple or type-Vector

    return:
        True if point is inside loop
    '''
    #test arguments type
    if any(not v for v in loop): return False

    ptype = str(type(point))
    ltype = str(type(loop[0]))
    nverts = len(loop)

    if 'Vector' not in ptype:
        point = Vector(point)

    if 'Vector' not in ltype:
        for i in range(0,nverts):
            loop[i] = Vector(loop[i])

    #find a point outside the loop and count intersections
    out = Vector(outside_loop_2d(loop))
    intersections = 0
    for i in range(0,nverts):
        a = Vector(loop[i-1])
        b = Vector(loop[i])
        if intersect_line_line_2d(point,out,a,b):
            intersections += 1

    inside = False
    if math.fmod(intersections,2):
        inside = True

    return inside

def outside_loop_2d(loop):
    '''
    args:
    loop: list of
       type-Vector or type-tuple
    returns:
       outside = a location outside bound of loop
       type-tuple
    '''

    xs = [v[0] for v in loop]
    ys = [v[1] for v in loop]

    maxx = max(xs)
    maxy = max(ys)
    bound = (1.1*maxx, 1.1*maxy)
    return bound

