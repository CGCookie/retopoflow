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
from mathutils import Vector, Matrix, Quaternion
from mathutils.geometry import intersect_point_line, intersect_line_plane
from mathutils.geometry import distance_point_to_plane, intersect_line_line_2d, intersect_line_line


# Blender imports
import blf
import bmesh
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d



class AddonLocator(object):
    def __init__(self, f=None):
        self.fullInitPath = f if f else __file__
        self.FolderPath = os.path.dirname(self.fullInitPath)
        self.FolderName = os.path.basename(self.FolderPath)
    
    def AppendPath(self):
        sys.path.append(self.FolderPath)
        print("Addon path has been registered into system path for this session")

def bversion():
    bversion = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])
    return bversion

def selection_mouse():
    select_type = bpy.context.user_preferences.inputs.select_mouse
    return ['%sMOUSE' % select_type, 'SHIFT+%sMOUSE' % select_type]

def get_settings():
    addons = bpy.context.user_preferences.addons
    stack = inspect.stack()
    for entry in stack:
        folderpath = os.path.dirname(entry[1])
        foldername = os.path.basename(folderpath)
        if foldername in {'lib','addons'}: continue
        if foldername in addons: break
    else:
        assert False, 'could not find non-"lib" folder'
    settings = addons[foldername].preferences
    return settings

def get_source_object():
    settings = get_settings()

    if bpy.context.mode == 'OBJECT':
        if settings.source_object:
            source_object = bpy.data.objects[settings.source_object]
        else:
            source_object = bpy.context.active_object
    elif bpy.context.mode == 'EDIT_MESH':
            source_object = bpy.data.objects[settings.source_object]

    return source_object

def get_target_object():
    settings = get_settings()

    if settings.target_object:
        target_object = bpy.data.objects[settings.target_object]
    else:
        target_object = bpy.context.active_object

    return target_object

def dprint(s, l=2):
    settings = get_settings()
    if settings.debug >= l:
        print('DEBUG(%i): %s' % (l, s))

def dcallstack(l=2):
    ''' print out the calling stack, skipping the first (call to dcallstack) '''
    dprint('Call Stack Dump:', l=l)
    for i,entry in enumerate(inspect.stack()):
        if i>0: dprint('  %s' % str(entry), l=l)




def showErrorMessage(message, wrap=80):
    lines = []
    if wrap > 0:
        while len(message) > wrap:
            i = message.rfind(' ',0,wrap)
            if i == -1:
                lines += [message[:wrap]]
                message = message[wrap:]
            else:
                lines += [message[:i]]
                message = message[i+1:]
    if message:
        lines += [message]
    def draw(self,context):
        for line in lines:
            self.layout.label(line)
    bpy.context.window_manager.popup_menu(draw, title="Error Message", icon="ERROR")
    return

def callback_register(self, context):
        #if str(bpy.app.build_revision)[2:7].lower == "unkno" or eval(str(bpy.app.build_revision)[2:7]) >= 53207:
    self._handle = bpy.types.SpaceView3D.draw_handler_add(self.menu.draw, (self, context), 'WINDOW', 'POST_PIXEL')
        #else:
            #self._handle = context.region.callback_add(self.menu.draw, (self, context), 'POST_PIXEL')
        #return None
            
def callback_cleanup(self, context):
    #if str(bpy.app.build_revision)[2:7].lower() == "unkno" or eval(str(bpy.app.build_revision)[2:7]) >= 53207:
    bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
    #else:
        #context.region.callback_remove(self._handle)
    #return None



class Profiler(object):
    class ProfilerHelper(object):
        def __init__(self, pr, text):
            full_text = (pr.stack[-1].text+'^' if pr.stack else '') + text
            assert full_text not in pr.d_start, '"%s" found in profiler already?'%text
            self.pr = pr
            self.text = full_text
            self._is_done = False
            self.pr.d_start[self.text] = time.time()
            self.pr.stack += [self]
        def __del__(self):
            if not self._is_done:
                dprint('WARNING: calling ProfilerHelper.done!')
                self.done()
        def done(self):
            assert self.pr.stack[-1] == self
            assert not self._is_done
            self.pr.stack.pop()
            self._is_done = True
            st = self.pr.d_start[self.text]
            en = time.time()
            self.pr.d_times[self.text] = self.pr.d_times.get(self.text,0) + (en-st)
            self.pr.d_count[self.text] = self.pr.d_count.get(self.text,0) + 1
            del self.pr.d_start[self.text]
    
    def __init__(self):
        self.d_start = {}
        self.d_times = {}
        self.d_count = {}
        self.stack = []
    
    def start(self, text=None):
        if not text:
            st = inspect.stack()
            filename = os.path.split(st[1][1])[1]
            linenum  = st[1][2]
            fnname   = st[1][3]
            text = '%s (%s:%d)' % (fnname, filename, linenum)
        return self.ProfilerHelper(self, text)
    
    def __del__(self):
        #self.printout()
        pass
    
    def printout(self):
        dprint('Profiler:')
        for text in sorted(self.d_times):
            tottime = self.d_times[text]
            totcount = self.d_count[text]
            calls = text.split('^')
            if len(calls) == 1:
                t = text
            else:
                t = '    '*(len(calls)-2) + ' \\- ' + calls[-1]
            dprint('  %6.2f / %3d = %6.2f - %s' % (tottime, totcount, tottime/totcount, t))
        dprint('')

profiler = Profiler()


def range_mod(m):
    for i in range(m): yield(i,(i+1)%m)

def iter_running_sum(lw):
    s = 0
    for w in lw:
        s += w
        yield (w,s)


def ray_cast_region2d(region, rv3d, screen_coord, obj, settings):
    '''
    performs ray casting on object given region, rv3d, and coords wrt region.
    returns tuple of ray vector (from coords of region) and hit info
    '''
    mx = obj.matrix_world
    rgn = region
    imx = mx.inverted()
    
    r2d_origin = region_2d_to_origin_3d
    r2d_vector = region_2d_to_vector_3d
    
    o, d = r2d_origin(rgn, rv3d, screen_coord), r2d_vector(rgn, rv3d, screen_coord).normalized()
    back = 0 if rv3d.is_perspective else 1
    mult = 100 #* (1 if rv3d.is_perspective else -1)
    bver = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])
    if (bver < '002.072.000') and not rv3d.is_perspective: mult *= -1
    
    st, en = imx*(o-mult*back*d), imx*(o+mult*d)
    hit = obj.ray_cast(st,en)
    return (d, hit)

def ray_cast_region2d_bvh(region, rv3d, screen_coord, bvh, mx, settings):
    '''
    performs ray casting on object given region, rv3d, and coords wrt region.
    returns tuple of ray vector (from coords of region) and hit info
    '''

    rgn = region
    imx = mx.inverted()
    
    r2d_origin = region_2d_to_origin_3d
    r2d_vector = region_2d_to_vector_3d
    
    o, d = r2d_origin(rgn, rv3d, screen_coord), r2d_vector(rgn, rv3d, screen_coord).normalized()
    back = 0 if rv3d.is_perspective else 1
    mult = 100 #* (1 if rv3d.is_perspective else -1)
    bver = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])
    if (bver < '002.072.000') and not rv3d.is_perspective: mult *= -1
    
    st, en = imx*(o-mult*back*d), imx*(o+mult*d)
    hit = bvh.ray_cast(st,(en-st))
    return (d, hit[0:3])

def ray_cast_path(context, ob, screen_coords):
    rgn  = context.region
    rv3d = context.space_data.region_3d
    mx   = ob.matrix_world
    imx  = mx.inverted()
    
    r2d_origin = region_2d_to_origin_3d
    r2d_vector = region_2d_to_vector_3d
    
    rays = [(r2d_origin(rgn, rv3d, co),r2d_vector(rgn, rv3d, co).normalized()) for co in screen_coords]
    
    if rv3d.is_perspective:
        rays = [(ray_o, get_ray_origin(ray_o, -ray_v, ob)) for ray_o,ray_v in rays]
    else:
        rays = [(get_ray_origin(ray_o, ray_v, ob),get_ray_origin(ray_o, -ray_v, ob)) for ray_o,ray_v in rays]
    
    hits = [ob.ray_cast(imx * ray_o, imx * ray_v) for ray_o,ray_v in rays]
    world_coords = [mx*co for co,no,face in hits if face != -1]
    return world_coords

def ray_cast_path_bvh(context, bvh, mx, screen_coords):
    
    rgn  = context.region
    rv3d = context.space_data.region_3d
    imx  = mx.inverted()
    r2d_origin = region_2d_to_origin_3d
    r2d_vector = region_2d_to_vector_3d
    
    rays = [(r2d_origin(rgn, rv3d, co),r2d_vector(rgn, rv3d, co).normalized()) for co in screen_coords]
    back = 0 if rv3d.is_perspective else 1
    mult = 100 #* (1 if rv3d.is_perspective else -1)
    bver = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])
    if (bver < '002.072.000') and not rv3d.is_perspective: mult *= -1
    
    sten = [(imx*(o-back*mult*d), imx*(o+mult*d)) for o,d in rays]
    hits = [bvh.ray_cast(st,(en-st)) for st,en in sten]
    world_coords = [mx*hit[0] for hit in hits if hit[2] != None]
    
    return world_coords

def ray_cast_stroke(context, ob, stroke):
    '''
    strokes have form [((x,y),p)] with a pressure or radius value
    
    returns list [Vector(x,y,z), p] leaving the pressure/radius value untouched
    does drop any values that do not successfully ray_cast
    '''
    rgn  = context.region
    rv3d = context.space_data.region_3d
    mx   = ob.matrix_world
    imx  = mx.inverted()
    
    r2d_origin = region_2d_to_origin_3d
    r2d_vector = region_2d_to_vector_3d
    
    rays = [(r2d_origin(rgn, rv3d, co),r2d_vector(rgn, rv3d, co).normalized()) for co,_ in stroke]
    
    back = 0 if rv3d.is_perspective else 1
    mult = 100 #* (1 if rv3d.is_perspective else -1)
    bver = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])
    if (bver < '002.072.000') and not rv3d.is_perspective: mult *= -1
    
    sten = [(imx*(o-mult*back*d), imx*(o+mult*d)) for o,d in rays]
    hits = [ob.ray_cast(st,st+(en-st)*1000) for st,en in sten]
    world_stroke = [(mx*hit[0],stroke[i][1])  for i,hit in enumerate(hits) if hit[2] != -1]
    
    return world_stroke

def ray_cast_stroke_bvh(context, bvh, mx, stroke):
    '''
    strokes have form [((x,y),p)] with a pressure or radius value
    
    returns list [Vector(x,y,z), p] leaving the pressure/radius value untouched
    drops any values that do not successfully ray_cast
    '''
    rgn  = context.region
    rv3d = context.space_data.region_3d
    imx  = mx.inverted()
    
    r2d_origin = region_2d_to_origin_3d
    r2d_vector = region_2d_to_vector_3d
    
    rays = [(r2d_origin(rgn, rv3d, co),r2d_vector(rgn, rv3d, co).normalized()) for co,_ in stroke]
    
    back = 0 if rv3d.is_perspective else 1
    mult = 100 #* (1 if rv3d.is_perspective else -1)
    bver = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])
    if (bver < '002.072.000') and not rv3d.is_perspective: mult *= -1
    
    sten = [(imx*(o-back*mult*d), imx*(o+mult*d)) for o,d in rays]
    hits = [bvh.ray_cast(st,(en-st)) for st,en in sten]
    world_stroke = [(mx*hit[0],stroke[i][1])  for i,hit in enumerate(hits) if hit[2] != None]
    
    return world_stroke


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
    
def ray_cast_visible(verts, ob, rv3d):
    '''
    returns list of Boolean values indicating whether the corresponding vert
    is visible (not occluded by object) in region associated with rv3d
    '''
    view_dir = (rv3d.view_rotation * Vector((0,0,1))).normalized()
    imx = ob.matrix_world.inverted()
    
    if rv3d.is_perspective:
        eyeloc = rv3d.view_location + rv3d.view_distance*view_dir
        #eyeloc = Vector(rv3d.view_matrix.inverted().col[3][:3]) #this is brilliant, thanks Gert
        eyeloc_local = imx*eyeloc
        source = [eyeloc_local for vert in verts]
        target = [imx*(vert+0.01*view_dir) for vert in verts]
    else:
        source = [imx*(vert+100*view_dir) for vert in verts]
        target = [imx*(vert+0.01*view_dir) for vert in verts]
    
    return [ob.ray_cast(s,t)[2]==-1 for s,t in zip(source,target)]

def ray_cast_visible_bvh(verts, bvh, mx, rv3d):
    '''
    returns list of Boolean values indicating whether the corresponding vert
    is visible (not occluded by object) in region associated with rv3d
    '''
    view_dir = (rv3d.view_rotation * Vector((0,0,1))).normalized()
    imx = mx.inverted()
    
    if rv3d.is_perspective:
        eyeloc = rv3d.view_location + rv3d.view_distance*view_dir
        #eyeloc = Vector(rv3d.view_matrix.inverted().col[3][:3]) #this is brilliant, thanks Gert
        eyeloc_local = imx*eyeloc
        source = [eyeloc_local for vert in verts]
        target = [imx*(vert+0.01*view_dir) for vert in verts]
    else:
        source = [imx*(vert+100*view_dir) for vert in verts]
        target = [imx*(vert+0.01*view_dir) for vert in verts]
    
    #notice, the math may appear backwards here.  But we want to cast toward the "eye"
    #and because bvh.ray_cast doesn't yet accept distance, 
    return [bvh.ray_cast(t,s-t)[2]== None for s,t in zip(source,target)]

def get_ray_origin_target(region, rv3d, screen_coord, ob):
    ray_vector = region_2d_to_vector_3d(region, rv3d, screen_coord).normalized()
    ray_origin = region_2d_to_origin_3d(region, rv3d, screen_coord)
    if not rv3d.is_perspective:
        # need to back up the ray's origin, because ortho projection has front and back
        # projection planes at inf
        
        bver = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])
        # why does this need to be negated?
        # but not when ortho front/back view??
        if bver < '002.073.000' and abs(ray_vector.y)<1: ray_vector = -ray_vector
        
        r0 = get_ray_origin(ray_origin, ray_vector, ob)
        r1 = get_ray_origin(ray_origin, -ray_vector, ob)
        ray_origin = r0
        ray_target = r1
    else:
        ray_target = get_ray_origin(ray_origin, -ray_vector, ob)
    
    return (ray_origin, ray_target)

def ray_cast_world_size(region, rv3d, screen_coord, screen_size, ob, settings):
    mx  = ob.matrix_world
    imx = mx.inverted()
    
    ray_origin,ray_target = get_ray_origin_target(region, rv3d, screen_coord, ob)
    ray_direction         = (ray_target - ray_origin).normalized()
    
    ray_start_local  = imx * ray_origin
    ray_target_local = imx * ray_target
    pt_local,no,idx  = ob.ray_cast(ray_start_local, ray_target_local)
    if idx == -1: return float('inf')
    
    pt = mx * pt_local
    
    screen_coord_offset = (screen_coord[0]+screen_size, screen_coord[1])
    ray_origin_offset,ray_target_offset = get_ray_origin_target(region, rv3d, screen_coord_offset, ob)
    ray_direction_offset = (ray_target_offset - ray_origin_offset).normalized()
    
    d = get_ray_plane_intersection(ray_origin_offset, ray_direction_offset, pt, (rv3d.view_rotation*Vector((0,0,-1))).normalized() )
    pt_offset = ray_origin_offset + ray_direction_offset * d
    
    return (pt-pt_offset).length

def ray_cast_world_size_bvh(region, rv3d, screen_coord, screen_size, bvh, mx, settings):

    imx = mx.inverted()
    rgn = region
    r2d_origin = region_2d_to_origin_3d
    r2d_vector = region_2d_to_vector_3d
    
    o, d = r2d_origin(rgn, rv3d, screen_coord), r2d_vector(rgn, rv3d, screen_coord).normalized()
    back = 0 if rv3d.is_perspective else 1
    mult = 100 #* (1 if rv3d.is_perspective else -1)
    bver = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])
    if (bver < '002.072.000') and not rv3d.is_perspective: mult *= -1
    
    st, en = imx*(o-back*mult*d), imx*(o+mult*d)
    pt_local, no, idx, _ = bvh.ray_cast(st,(en-st))
    
    if idx == None: return float('inf')
    
    pt = mx * pt_local
    
    screen_coord_offset = (screen_coord[0]+screen_size, screen_coord[1])
    o_off, d_off = r2d_origin(rgn, rv3d, screen_coord_offset), r2d_vector(rgn, rv3d, screen_coord_offset).normalized()
    st, en = imx*(o-back*mult*d), imx*(o+mult*d)

    d = get_ray_plane_intersection(o_off, d_off, pt, (rv3d.view_rotation*Vector((0,0,-1))).normalized() )
    pt_offset = o_off + d_off * d
    return (pt-pt_offset).length

def get_ray_plane_intersection(ray_origin, ray_direction, plane_point, plane_normal):
    d = ray_direction.dot(plane_normal)
    if abs(ray_direction.dot(plane_normal)) <= 0.00000001: return float('inf')
    return (plane_point-ray_origin).dot(plane_normal) / d

def get_ray_origin(ray_origin, ray_direction, ob):
    mx = ob.matrix_world
    q  = ob.rotation_quaternion
    bbox = [Vector(v) for v in ob.bound_box]
    bm = Vector((min(v.x for v in bbox),min(v.y for v in bbox),min(v.z for v in bbox)))
    bM = Vector((max(v.x for v in bbox),max(v.y for v in bbox),max(v.z for v in bbox)))
    x,y,z = Vector((1,0,0)),Vector((0,1,0)),Vector((0,0,1))
    planes = []
    if abs(ray_direction.x)>0.0001: planes += [(bm,x), (bM,-x)]
    if abs(ray_direction.y)>0.0001: planes += [(bm,y), (bM,-y)]
    if abs(ray_direction.z)>0.0001: planes += [(bm,z), (bM,-z)]
    dists = [get_ray_plane_intersection(ray_origin,ray_direction,mx*p0,q*no) for p0,no in planes]
    dprint(dists, l=4)
    return ray_origin + ray_direction * min(dists)


def closest_t_and_distance_point_to_line_segment(p, p0, p1):
    v0p,v1p,v01 = p-p0, p-p1, p1-p0
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
