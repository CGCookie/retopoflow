'''
Copyright (C) 2013 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Patrick Moore

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
import math
import random
import time
from collections import deque
from itertools import chain,combinations
from mathutils import Vector, Matrix, Quaternion
from mathutils.geometry import intersect_line_plane, intersect_point_line, distance_point_to_plane, intersect_line_line_2d, intersect_line_line

# Blender imports
import bgl
import blf
import bmesh
import bpy
from bpy_extras import view3d_utils
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d, region_2d_to_origin_3d


def edge_loops_from_bmedges(bmesh, bm_edges):
    """
    Edge loops defined by edges

    Takes [mesh edge indices] or a list of edges and returns the edge loops

    return a list of vertex indices.
    [ [1, 6, 7, 2], ...]

    closed loops have matching start and end values.
    """
    line_polys = []
    edges = bm_edges.copy()

    while edges:
        current_edge = bmesh.edges[edges.pop()]
        vert_e, vert_st = current_edge.verts[:]
        vert_end, vert_start = vert_e.index, vert_st.index
        line_poly = [vert_start, vert_end]

        ok = True
        while ok:
            ok = False
            #for i, ed in enumerate(edges):
            i = len(edges)
            while i:
                i -= 1
                ed = bmesh.edges[edges[i]]
                v_1, v_2 = ed.verts
                v1, v2 = v_1.index, v_2.index
                if v1 == vert_end:
                    line_poly.append(v2)
                    vert_end = line_poly[-1]
                    ok = 1
                    del edges[i]
                    # break
                elif v2 == vert_end:
                    line_poly.append(v1)
                    vert_end = line_poly[-1]
                    ok = 1
                    del edges[i]
                    #break
                elif v1 == vert_start:
                    line_poly.insert(0, v2)
                    vert_start = line_poly[0]
                    ok = 1
                    del edges[i]
                    # break
                elif v2 == vert_start:
                    line_poly.insert(0, v1)
                    vert_start = line_poly[0]
                    ok = 1
                    del edges[i]
                    #break
        line_polys.append(line_poly)

    return line_polys

def perp_vector_point_line(pt1, pt2, ptn):
    '''
    Vector bwettn pointn and line between point1
    and point2
    args:
        pt1, and pt1 are Vectors representing line segment
    
    return Vector
    
    pt1 ------------------- pt
            ^
            |
            |
            |<-----this vector
            |
            ptn
    '''
    pt_on_line = intersect_point_line(ptn.to_3d(), pt1.to_3d(), pt2.to_3d())[0]
    alt_vect = pt_on_line - ptn
    
    return alt_vect

def altitude(point1, point2, pointn):
    edge1 = point2 - point1
    edge2 = pointn - point1
    if edge2.length == 0:
        altitude = 0
        return altitude
    if edge1.length == 0:
        altitude = edge2.length
        return altitude
    alpha = edge1.angle(edge2)
    altitude = math.sin(alpha) * edge2.length
    
    return altitude 
    
# iterate through verts
def iterate(points, newVerts, error,method = 0):
    '''
    args:
    points - list of vectors in order representing locations on a curve
    newVerts - list of indices? (mapping to arg: points) of aready identified "new" verts
    error - distance obove/below chord which makes vert considered a feature
    
    return:
    new -  list of vertex indicies (mappint to arg points) representing identified feature points
    or
    false - no new feature points identified...algorithm is finished.
    '''
    new = []
    for newIndex in range(len(newVerts)-1):
        bigVert = 0
        alti_store = 0
        for i, point in enumerate(points[newVerts[newIndex]+1:newVerts[newIndex+1]]):
            if method == 1:
                alti = perp_vector_point_line(points[newVerts[newIndex]], points[newVerts[newIndex+1]], point).length
            else:
                alti = altitude(points[newVerts[newIndex]], points[newVerts[newIndex+1]], point)
                
            if alti > alti_store:
                alti_store = alti
                if alti_store >= error:
                    bigVert = i+1+newVerts[newIndex]
        if bigVert:
            new.append(bigVert)
    if new == []:
        return False
    return new

#### get SplineVertIndices to keep
def simplify_RDP(splineVerts, error, method = 0):
    '''
    Reduces a curve or polyline based on altitude changes globally and w.r.t. neighbors
    args:
    splineVerts - list of vectors representing locations along the spline/line path
    error - altitude above global/neighbors which allows point to be considered a feature
    return:
    newVerts - a list of indicies of the simplified representation of the curve (in order, mapping to arg-splineVerts)
    '''

    start = time.time()
    
    # set first and last vert
    newVerts = [0, len(splineVerts)-1]

    # iterate through the points
    new = 1
    while new != False:
        new = iterate(splineVerts, newVerts, error, method = method)
        if new:
            newVerts += new
            newVerts.sort()
            
    print('finished simplification with method %i in %f seconds' % (method, time.time() - start))
    return newVerts


def relax(verts, factor = .75, in_place = True):
    '''
    verts is a list of Vectors
    first and last vert will not be changes
    
    this should modify the list in place
    however I have it returning verts?
    '''
    
    L = len(verts)
    if L < 4:
        print('not enough verts to relax')
        return verts
    
    
    deltas = [Vector((0,0,0))] * L
    
    for i in range(1,L-1):
        
        d = .5 * (verts[i-1] + verts[i+1]) - verts[i]
        deltas[i] = factor * d
    
    if in_place:
        for i in range(1,L-1):
            verts[i] += deltas[i]
        
        return True
    else:
        new_verts = verts.copy()
        for i in range(1,L-1):
            new_verts[i] += deltas[i]     
        
        return new_verts
           
def pi_slice(x,y,r1,r2,thta1,thta2,res,t_fan = False):
    '''
    args: 
    x,y - center coordinate
    r1, r2 inner and outer radius
    thta1: beginning of the slice  0 = to the right
    thta2:  end of the slice (ccw direction)
    '''
    points = [[0,0]]*(2*res + 2)  #the two arcs

    for i in range(0,res+1):
        diff = math.fmod(thta2-thta1 + 4*math.pi, 2*math.pi)
        x1 = math.cos(thta1 + i*diff/res) 
        y1 = math.sin(thta1 + i*diff/res)
    
        points[i]=[r1*x1 + x,r1*y1 + y]
        points[(2*res) - i+1] =[x1*r2 + x, y1*r2 + y]
        
    if t_fan: #need to shift order so GL_TRIANGLE_FAN can draw concavity
        new_0 = math.floor(1.5*(2*res+2))
        points = list_shift(points, new_0)
            
    return(points)


def arrow_primitive(x,y,ang,tail_l, head_l, head_w, tail_w):
    
    #primitive
    #notice the order so that the arrow can be filled
    #in by traingle fan or GL quad arrow[0:4] and arrow [4:]
    prim = [Vector((-tail_w,tail_l)),
            Vector((-tail_w, 0)), 
            Vector((tail_w, 0)), 
            Vector((tail_w, tail_l)),
            Vector((head_w,tail_l)),
            Vector((0,tail_l + head_l)),
            Vector((-head_w,tail_l))]
    
    #rotation
    rmatrix = Matrix.Rotation(ang,2)
    
    #translation
    T = Vector((x,y))
    
    arrow = [[None]] * 7
    for i, loc in enumerate(prim):
        arrow[i] = T + rmatrix * loc
        
    return arrow
       
def arc_arrow(x,y,r1,thta1,thta2,res, arrow_size, arrow_angle, ccw = True):
    '''
    args: 
    x,y - center coordinate of cark
    r1 = radius of arc
    thta1: beginning of the arc  0 = to the right
    thta2:  end of the arc (ccw direction)
    arrow_size = length of arrow point
    
    ccw = True draw the arrow
    '''
    points = [Vector((0,0))]*(res +1) #The arc + 2 arrow points

    for i in range(0,res+1):
        #able to accept negative values?
        diff = math.fmod(thta2-thta1 + 2*math.pi, 2*math.pi)
        x1 = math.cos(thta1 + i*diff/res) 
        y1 = math.sin(thta1 + i*diff/res)
    
        points[i]=Vector((r1*x1 + x,r1*y1 + y))

    if not ccw:
        points.reverse()
        
    end_tan = points[-2] - points[-1]
    end_tan.normalize()
    
    #perpendicular vector to tangent
    arrow_perp_1 = Vector((-end_tan[1],end_tan[0]))
    arrow_perp_2 = Vector((end_tan[1],-end_tan[0]))
    
    op_ov_adj = (math.tan(arrow_angle/2))**2
    arrow_side_1 = end_tan + op_ov_adj * arrow_perp_1
    arrow_side_2 = end_tan + op_ov_adj * arrow_perp_2
    
    arrow_side_1.normalize()
    arrow_side_2.normalize()
    
    points.append(points[-1] + arrow_size * arrow_side_1)
    points.append(points[-2] + arrow_size * arrow_side_2) 
           
    return(points)

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
   
def get_com(verts):
    '''
    args:
        verts- a list of vectors to be included in the calc
        mx- thw world matrix of the object, if empty assumes unity
        
    '''
    COM = Vector((0,0,0))
    l = len(verts)
    for v in verts:
        COM += v  
    COM =(COM/l)

    return COM

def approx_radius(verts, COM):
    '''
    avg distance
    '''
    l = len(verts)
    app_rad = 0
    for v in verts:
        R = COM - v
        app_rad += R.length
        
    app_rad = 1/l * app_rad
    
    return app_rad    

def verts_bbox(verts):
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

def diagonal_verts(verts):
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    
    diag = math.pow((dx**2 + dy**2 + dz**2),.5)
    
    return diag


def calculate_com_normal(locs):
    '''
    computes a center of mass (CoM) and a normal of provided roughly planar locs
    notes:
    - uses random sampling
    - does not assume a particular order of locs
    - may compute the negative of "true" normal
    '''
    com = sum((loc for loc in locs), Vector((0,0,0))) / len(locs)
    # get locations wrt to com
    llocs = [loc-com for loc in locs]
    ac = Vector((0,0,0))
    first = True
    for i in range(len(locs)):
        lp0,lp1 = random.sample(llocs,2)
        c = lp0.cross(lp1).normalized()
        if first:
            ac = c
            first = False
        else:
            if ac.dot(c) < 0:
                ac -= c
            else:
                ac += c
    return (com, ac.normalized())

#TODO: CREDIT
#TODO: LINK
def calculate_best_plane(locs):
    
    # calculating the center of masss
    com = Vector()
    for loc in locs:
        com += loc
    com /= len(locs)
    x, y, z = com
    
    
    # creating the covariance matrix
    mat = Matrix(((0.0, 0.0, 0.0),
                  (0.0, 0.0, 0.0),
                  (0.0, 0.0, 0.0),
                 ))
    
    for loc in locs:
        mat[0][0] += (loc[0]-x)**2
        mat[1][0] += (loc[0]-x)*(loc[1]-y)
        mat[2][0] += (loc[0]-x)*(loc[2]-z)
        mat[0][1] += (loc[1]-y)*(loc[0]-x)
        mat[1][1] += (loc[1]-y)**2
        mat[2][1] += (loc[1]-y)*(loc[2]-z)
        mat[0][2] += (loc[2]-z)*(loc[0]-x)
        mat[1][2] += (loc[2]-z)*(loc[1]-y)
        mat[2][2] += (loc[2]-z)**2
    
    # calculating the normal to the plane
    normal = False
    try:
        mat.invert()
    except:
        if sum(mat[0]) == 0.0:
            normal = Vector((1.0, 0.0, 0.0))
        elif sum(mat[1]) == 0.0:
            normal = Vector((0.0, 1.0, 0.0))
        elif sum(mat[2]) == 0.0:
            normal = Vector((0.0, 0.0, 1.0))
    if not normal:
        # warning! this is different from .normalize()
        itermax = 500
        iter = 0
        vec = Vector((1.0, 1.0, 1.0))
        vec2 = (mat * vec)/(mat * vec).length
        while vec != vec2 and iter<itermax:
            iter+=1
            vec = vec2
            vec2 = mat * vec
            if vec2.length != 0:
                vec2 /= vec2.length
        if vec2.length == 0:
            vec2 = Vector((1.0, 1.0, 1.0))
        normal = vec2
    
    return(com, normal)
    
def cross_section(bme, mx, point, normal, debug = True):
    '''
    Takes a mesh and associated world matrix of the object and returns a cross secion in local
    space.
    
    Args:
        mesh: Blender BMesh
        mx:   World matrix (type Mathutils.Matrix)
        point: any point on the cut plane in world coords (type Mathutils.Vector)
        normal:  plane normal direction (type Mathutisl.Vector)
    '''
    
    times = []
    times.append(time.time())
    #bme = bmesh.new()
    #bme.from_mesh(me)
    #bme.normal_update()
    
    #if debug:
        #n = len(times)
        #times.append(time.time())
        #print('succesfully created bmesh in %f sec' % (times[n]-times[n-1]))
    verts =[]
    eds = []
    
    #convert point and normal into local coords
    #in the mesh into world space.This saves 2*(Nverts -1) matrix multiplications
    imx = mx.inverted()
    pt = imx * point
    no = imx.to_3x3() * normal  #local normal
    
    edge_mapping = {}  #perhaps we should use bmesh becaus it stores the great cycles..answer yup
    
    for ed in bme.edges:
        
        A = ed.verts[0].co
        B = ed.verts[1].co
        V = B - A
        
        proj = V.project(no).length
        
        #perp to normal = parallel to plane
        #only calc 2nd projection if necessary
        if proj == 0:
            
            #make sure not coplanar
            p_to_A = A - pt
            a_proj = p_to_A.project(no).length
            
            if a_proj == 0:
               
                edge_mapping[len(verts)] = ed.link_faces
                verts.append(1/2 * (A +B)) #put a midpoing since both are coplanar

        else:
            
            #this handles the one point on plane case
            v = intersect_line_plane(A,B,pt,no)
           
            if v:
                check = intersect_point_line(v.to_3d(),A.to_3d(),B.to_3d())
                if check[1] >= 0 and check[1] <= 1:
                    
                                             
                    
                    #the vert coord index    =  the face indices it came from
                    edge_mapping[len(verts)] = [f.index for f in ed.link_faces]
                    verts.append(v)
    
    if debug:
        n = len(times)
        times.append(time.time())
        print('calced intersections %f sec' % (times[n]-times[n-1]))
       
    #iterate through smartly to create edge keys          
    for i in range(0,len(verts)):
        a_faces = set(edge_mapping[i])
        for m in range(i,len(verts)):
            if m != i:
                b_faces = set(edge_mapping[m])
                if a_faces & b_faces:
                    eds.append((i,m))
    
    if debug:
        n = len(times)
        times.append(time.time())
        #print('calced connectivity %f sec' % (times[n]-times[n-1]))
        
    if len(verts):
        #new_me = bpy.data.meshes.new('Cross Section')
        #new_me.from_pydata(verts,eds,[])
        
    
        #if debug:
            #n = len(times)
            #times.append(time.time())
            #print('Total Time: %f sec' % (times[-1]-times[0]))
            
        return (verts, eds)
    else:
        return None
    
def cross_edge(A,B,pt,no):
    '''
    wrapper of intersect_line_plane that limits intersection
    to within the line segment.
    
    args:
        A - Vector endpoint of line segment
        B - Vector enpoint of line segment
        pt - pt on plane to intersect
        no - normal of plane to intersect
        
    return:
        list [Intersection Type, Intersection Point, Intersection Point2]
        eg... ['CROSS',Vector((0,1,0)), None]
        eg... ['POINT',Vector((0,1,0)), None]
        eg....['COPLANAR', Vector((0,1,0)),Vector((0,2,0))]
        eg....[None,None,None]
    '''
 
    ret_val = [None]*3 #list [intersect type, pt 1, pt 2]
    V = B - A #vect representation of the edge
    proj = V.project(no).length
    
    #perp to normal = parallel to plane
    #worst case is a coplanar issue where the whole face is coplanar..we will get there
    if proj == 0:
        
        #test coplanar
        #don't test both points.  We have already tested once for paralellism
        #simply proving one out of two points is/isn't in the plane will
        #prove/disprove coplanar
        p_to_A = A - pt
        #truly, we could precalc all these projections to save time but use mem.
        #because in the multiple edges coplanar case, we wil be testing
        #their verts over and over again that share edges.  So for a mesh with
        #a lot of n poles, precalcing the vert projections may save time!  
        #Hint to future self, look at  Nfaces vs Nedges vs Nverts
        #may prove to be a good predictor of which method to use.
        a_proj = p_to_A.project(no).length
        
        if a_proj == 0:
            print('special case co planar edge')
            ret_val = ['COPLANAR',A,B]
            
    else:
        
        #this handles the one point on plane case
        v = intersect_line_plane(A,B,pt,no)
       
        if v:
            check = intersect_point_line(v.to_3d(),A.to_3d(),B.to_3d())
            if check[1] > 0 and check[1] < 1:  #this is the purest cross...no co-points
                #the vert coord index    =  the face indices it came from
                ret_val = ['CROSS',v,None]
                
            elif check[1] == 0 or check[1] == 1:
                print('special case coplanar point')
                #now add all edges that have that point into the already checked list
                #this takes care of poles
                ret_val = ['POINT',v,None]

    return ret_val

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

def bound_box(verts):
    '''
    takes a list of vectors of any dimension
    returns a list of (min,max) pairs
    '''
    if len(verts) < 4:
        return verts
    
    dim = len(verts[0])
    
    bounds = []
    for i in range(0,dim):
        components = [v[i] for v in verts]
        low = min(components)
        high = max(components)
        
        bounds.append((low,high))
        
    return bounds

def diagonal(bounds):
    '''
    returns the diagonal dimension of min/max
    pairs of bounds.  Will generalize to N dimensions
    however only really meaningful for 2 or 3 dim vectors
    '''
    diag = 0
    for min_max in bounds:
        l = min_max[1] - min_max[0]
        diag += l * l
        
    diag = diag ** .5
    
    return diag
    
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
    ptype = str(type(point))
    ltype = str(type(loop[0]))
    nverts = len(loop)
    
    if any(not v for v in loop): return False
           
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

def generic_axes_from_plane_normal(p_pt, no):
    '''
    will take a point on a plane and normal vector
    and return two orthogonal vectors which create
    a right handed coordinate system with z axist aligned
    to plane normal
    '''
    
    #get the equation of a plane ax + by + cz = D
    #Given point P, normal N ...any point R in plane satisfies
    # Nx * (Rx - Px) + Ny * (Ry - Py) + Nz * (Rz - Pz) = 0
    #now pick any xy, yz or xz and solve for the other point
    
    a = no[0]
    b = no[1]
    c = no[2]
    
    Px = p_pt[0]
    Py = p_pt[1]
    Pz = p_pt[2]
    
    D = a * Px + b * Py + c * Pz
    
    #generate a randomply perturbed R from the known p_pt
    R = p_pt + Vector((random.random(), random.random(), random.random()))
    
    #z = D/c - a/c * x - b/c * y
    if c != 0:
        Rz =  D/c - a/c * R[0] - b/c * R[1]
        R[2] = Rz
       
    #y = D/b - a/b * x - c/b * z 
    elif b!= 0:
        Ry = D/b - a/b * R[0] - c/b * R[2] 
        R[1] = Ry
    #x = D/a - b/a * y - c/a * z
    elif a != 0:
        Rx = D/a - b/a * R[1] - c/a * R[2]
        R[0] = Rz
    else:
        print('undefined plane you wanker!')
        return(False)
    
    #now R represents some other point in the plane
    #we will use this to define an arbitrary local
    #x' y' and z'
    X_prime = R - p_pt
    X_prime.normalize()
    
    Y_prime = no.cross(X_prime)
    Y_prime.normalize()
    
    return (X_prime, Y_prime)

def point_inside_loop_almost3D(pt, verts, no, p_pt = None, threshold = .01, debug = False, bbox = False):
    '''
    http://blenderartists.org/forum/showthread.php?259085-Brainstorming-for-Virtual-Buttons&highlight=point+inside+loop
    args:
       pt - 3d point to test of type Mathutils.Vector
       verts - 3d points representing the loop  
               TODO:  verts[0] == verts[-1] or implied?
               list with elements of type Mathutils.Vector
       no - plane normal
       plane_pt - a point on the plane.
                  if None, COM of verts will be used
       threshold - maximum distance to consider pt "coplanar"
                   default = .01
                   
       debug - Bool, default False.  Will print performance if True
                   
    return: Bool True if point is inside the loop
    '''
    if debug:
        start = time.time()
    #sanity checks
    if len(verts) < 3:
        print('loop must have 3 verts to be a loop and even then its sketchy')
        return False
    
    if no.length == 0:
        print('normal vector must be non zero')
        return False
    
    if not p_pt:
        p_pt = get_com(verts)
    
    if distance_point_to_plane(pt, p_pt, no) > threshold:
        return False
    
    (X_prime, Y_prime) = generic_axes_from_plane_normal(p_pt, no)
    
    verts_prime = []
    
    for v in verts:
        v_trans = v - p_pt
        vx = v_trans.dot(X_prime)
        vy = v_trans.dot(Y_prime)
        verts_prime.append(Vector((vx, vy)))
    
    bounds = bound_box(verts_prime)
    
    bound_loop = [Vector((bounds[0][0],bounds[1][0])),
                  Vector((bounds[0][1],bounds[1][0])),
                  Vector((bounds[0][1],bounds[1][1])),
                  Vector((bounds[0][0],bounds[1][1]))]                       
    #transform the test point into the new plane x,y space
    pt_trans = pt - p_pt
    pt_prime = Vector((pt_trans.dot(X_prime), pt_trans.dot(Y_prime)))
    
    if bbox:
        print('intersected the bbox')
        pt_in_loop = point_inside_loop2d(bound_loop, pt_prime)
    else:                  
        pt_in_loop = point_inside_loop2d(verts_prime, pt_prime)
    
    return pt_in_loop

def face_cycle(face, pt, no, prev_eds, verts):#, connection):
    '''
    args:
        face - Blender BMFace
        pt - Vector, point on plane
        no - Vector, normal of plane
        
        
        These arguments will be modified
        prev_eds - MUTABLE list of previous edges already tested in the bmesh
        verts - MUTABLE list of Vectors representing vertex coords
        connection - MUTABLE dictionary of vert indices and face connections
        
    return:
        element - either a BMVert or a BMFace depending on what it finds.
    '''
    if len(face.edges) > 4:
        ngon = True
        print('oh sh** an ngon')
    else:
        ngon = False
        
    for ed in face.edges:
        if ed.index not in prev_eds:
            prev_eds.append(ed.index)
            A = ed.verts[0].co
            B = ed.verts[1].co
            result = cross_edge(A, B, pt, no)
                
            if result[0] == 'CROSS':
                
                #connection[len(verts)] = [f.index for f in ed.link_faces]
                verts.append(result[1])
                next_faces = [newf for newf in ed.link_faces if newf.index != face.index]
                if len(next_faces):
                    return next_faces[0]
                else:
                    #guess we got to a non manifold edge
                    print('found end of mesh!')
                    return None
                
            elif result[0] == 'POINT':
                if result[1] == A:
                    co_point = ed.verts[0]
                else:
                    co_point = ed.verts[1]
                    
                #connection[len(verts)] = [f.index for f in co_point.link_faces]  #notice we take the face loop around the point!
                verts.append(result[1])  #store the "intersection"
                    
                return co_point
            
def vert_cycle(vert, pt, no, prev_eds, verts):#, connection):
    '''
    args:
        vert - Blender BMVert
        pt - Vector, point on plane
        no - Vector, normal of plane
        
        
        These arguments will be modified
        prev_eds - MUTABLE list of previous edges already tested in the bmesh
        verts - MUTABLE list of Vectors representing vertex coords
        connection - MUTABLE dictionary of vert indices and face connections
        
    return:
        element - either a BMVert or a BMFace depending on what it finds.
    '''                
    
    for f in vert.link_faces:
        for ed in f.edges:
            if ed.index not in prev_eds:
                prev_eds.append(ed.index)
                A = ed.verts[0].co
                B = ed.verts[1].co
                result = cross_edge(A, B, pt, no)
                
                if result[0] == 'CROSS':
                    #connection[len(verts)] = [f.index for f in ed.link_faces]
                    verts.append(result[1])
                    next_faces = [newf for newf in ed.link_faces if newf.index != f.index]
                    if len(next_faces):
                        #return face to try face cycle
                        return next_faces[0]
                    else:
                        #guess we got to a non manifold edge
                        print('found end of mesh!')
                        return None
                    
                elif result[0] == 'COPLANAR':
                    cop_face = 0
                    for face in ed.link_faces:
                        if face.normal.cross(no) == 0:
                            cop_face += 1
                            print('found a coplanar face')
    
                    if cop_face == 2:
                        #we have two coplanar faces with a coplanar edge
                        #this makes our cross section fail from a loop perspective
                        print("double coplanar face error, stopping here")
                        return None
                    
                    else:
                        #jump down line to the next vert
                        if ed.verts[0].index == vert.index:
                            element = ed.verts[1]
                            
                        else:
                            element = ed.verts[0]
                        
                        #add the new vert coord into the mix
                        #connection[len(verts)] = [f.index for f in element.link_faces]
                        verts.append(element.co)
                        
                        #return the vert to repeat the vert cycle
                        return element

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
 
def list_shift(seq, n):
    n = n % len(seq)
    return seq[n:] + seq[:n]

def concatenate(*lists):
    lengths = map(len,lists)
    newlen = sum(lengths)
    newlist = [None]*newlen
    start = 0
    end = 0
    for l,n in zip(lists,lengths):
        end+=n
        newlist[start:end] = l
        start+=n
    return newlist

def find_doubles(seq):
    seen = set()
    seen_add = seen.add
    # adds all elements it doesn't know yet to seen and all other to seen_twice
    seen_twice = set(x for x in seq if x in seen or seen_add(x))
    # turn the set into a list (as requested)
    return list(seen_twice)

def alignment_quality_perpendicular(verts_1, verts_2, eds_1, eds_2):
    '''
    Calculates a quality measure of the alignment of edge loops.
    Ideally we want any connectors between loops to be as perpendicular
    to the loop as possible. Assume the loops are aligned properly in
    direction around the loop.
    
    args:
        verts_1: list of Vectors
        verts_2: list of Vectors
        
        eds_1: connectivity of the first loop, really just to test loop or line
        eds_2: connectivity of 2nd loops, really just to test for loop or line

    '''

    if 0 in eds_1[-1]:
        cyclic = True
        print('cyclic vert chain')
    else:
        cyclic = False
        
    if len(verts_1) != len(verts_2):
        print(len(verts_1))
        print(len(verts_2))
        print('non uniform loops, stopping until your developer gets smarter')
        return
    
    
    #since the loops in our case are guaranteed planar
    #because they come from cross sections, we can find
    #the plane normal very easily
    V1_0 = verts_1[1] - verts_1[0]
    V1_1 = verts_1[2] - verts_1[1]
    
    V2_0 = verts_2[1] - verts_2[0]
    V2_1 = verts_2[2] - verts_2[1]
    
    no_1 = V1_0.cross(V1_1)
    no_1.normalize()
    no_2 = V2_0.cross(V2_1)
    no_2.normalize()
    
    if no_1.dot(no_2) < 0:
        no_2 = -1 * no_2
    
    #average the two directions    
    ideal_direction = no_1.lerp(no_1,.5)
    
def point_in_tri(P, A, B, C):
    '''
    
    '''
    #straight from http://www.blackpawn.com/texts/pointinpoly/
    # Compute vectors        
    v0 = C - A
    v1 = B - A
    v2 = P - A
    
    #Compute dot products
    dot00 = v0.dot(v0)
    dot01 = v0.dot(v1)
    dot02 = v0.dot(v2)
    dot11 = v1.dot(v1)
    dot12 = v1.dot(v2)
    
    #Compute barycentric coordinates
    invDenom = 1 / (dot00 * dot11 - dot01 * dot01)
    u = (dot11 * dot02 - dot01 * dot12) * invDenom
    v = (dot00 * dot12 - dot01 * dot02) * invDenom
    
    #Check if point is in triangle
    return (u >= 0) & (v >= 0) & (u + v < 1)

def com_mid_ray_test(new_cut, established_cut, obj, search_factor = .5):
    '''
    function used to test intial validity of a connection
    between two cuts.
    
    args:
        new_cut:  a ContourCutLine
        existing_cut: ContourCutLine
        obj: The retopo object
        search_factor:  percentage of object bbox diagonal to search
        aim:  False or angle that new cut COM must fall within compared
              to existing plane normal.  Eg...pi/4 would be a 45 degree
              aiming cone
    
    
    returns: Bool
    '''
    
    
    A = established_cut.plane_com  #the COM of the cut loop
    B = new_cut.plane_com #the COM of the other cut loop
    C = .5 * (A + B)  #the midpoint of the line between them
                    
                    
    #pick a vert roughly in the middle
    n = math.floor(len(established_cut.verts_simple)/2)
            
            
    ray = A - established_cut.verts_simple[n]
    
    #just in case the vert IS the center of mass :-(
    if ray.length < .0001 and n != 0:
        ray = A - established_cut.verts_simple[n-1]
            
    ray.normalize()
            
            
    #limit serach to some fraction of the object bbox diagonal
    #search_radius = 1/2 * search_factor * obj.dimensions.length
    search_radius = 100
    imx = obj.matrix_world.inverted()     
            
    hit = obj.ray_cast(imx * (C + search_radius * ray), imx * (C - search_radius * ray))
            
    return hit[0]
        
def com_line_cross_test(com1, com2, pt, no, factor = 2):
    '''
    test used to make sure a cut is reasoably between
    2 other cuts
    
    higher factor requires better aligned cuts
    '''
    
    v = intersect_line_plane(com1,com2,pt,no)
    if v:
        #if the distance between the intersection is less than
        #than 1/factor the distance between the current pair
        #than this pair is invalide because there is a loop
        #in between
        check = intersect_point_line(v.to_3d(),com1.to_3d(),com2.to_3d())
        invalid_length = (com2 - com1).length/factor  #length beyond which an intersection is invalid
        test_length = (v - pt).length
        
        #this makes sure the plane is between A and B
        #meaning the test plane is between the two COM's
        in_between = check[1] >= 0 and check[1] <= 1
        
        if in_between and test_length < invalid_length:
            return True
  
def discrete_curl(verts, z): #Adapted from Open Dental CAD by Patrick Moore
    '''
    calculates the curl relative to the direction given.
    It should be ~ +2pi or -2pi depending on whether the loop
    progresses clockwise or anticlockwise when viewed in the 
    z direction.  If the loop goes around twice it could be 4pi 6pi etc
    This is useful for making sure loops are indexed in the same direction.
    
    args:
       verts: a list of Vectors representing locations
       z: a vector representing the direction to compare the curl to
       
    '''
    if len(verts) < 3:
        print('not possible for this to be a loop!')
        return None
    
    curl = 0
    
    #just in case the vert chain has the last vert
    #duplicated.  We will need to not double the 
    #last one
    closed = False
    if verts[-1] == verts[0]:
        closed = True
        
    for n in range(0,len(verts) - 1*closed):

        a = int(math.fmod(n - 1, len(verts)))
        b = n
        c = int(math.fmod(n + 1, len(verts)))
        #Vec representation of the two edges
        V0 = (verts[b] - verts[a])
        V1 = (verts[c] - verts[b])
        
        #projection into the plane perpendicular to z
        #eg, the XY plane
        T0 = V0 - V0.project(z)
        T1 = V1 - V1.project(z)
        
        #cross product
        cross = T0.cross(T1)        
        sign = 1
        if cross.dot(z) < 0:
            sign = -1
        
        rot = T0.rotation_difference(T1)  
        ang = rot.angle
        curl = curl + ang*sign
    
    return curl

def rot_between_vecs(v1,v2, factor = 1):
    '''
    args:
    v1 - Vector Init
    v2 - Vector Final
    
    factor - will interpolate between them.  [0,1]
    
    returns the quaternion representing rotation between v1 to v2
    
    v2 = quat * v1
    
    notes: doesn't test for parallel vecs
    '''
    v1.normalize()
    v2.normalize()
    angle = factor * v1.angle(v2)
    axis = v1.cross(v2)
    axis.normalize()
    sin = math.sin(angle/2)
    cos = math.cos(angle/2)
    
    quat = Quaternion((cos, sin*axis[0], sin*axis[1], sin*axis[2]))
    
    return quat

def circ(point1, point2, point3):
    '''find the x,y and radius for the circle through the 3 points'''
    ax = point1[0]
    ay = point1[1]
    ax = point1[0]
    ay = point1[1]
    bx = point2[0]
    by = point2[1]
    cx = point3[0]
    cy = point3[1]
    
    if (ax*by-ax*cy-cx*by+cy*bx-bx*ay+cx*ay) != 0:
        x=.5*(-pow(ay, 2)*cy+pow(ay, 2)*by-ay*pow(bx, 2)\
        -ay*pow(by, 2)+ay*pow(cy, 2)+ay*pow(cx, 2)-\
        pow(cx, 2)*by+pow(ax, 2)*by+pow(bx, 2)*\
        cy-pow(ax, 2)*cy-pow(cy, 2)*by+cy*pow(by, 2))\
        /(ax*by-ax*cy-cx*by+cy*bx-bx*ay+cx*ay)
        y=-.5*(-pow(ax, 2)*cx+pow(ax, 2)*bx-ax*pow(by, 2)\
        -ax*pow(bx, 2)+ax*pow(cx, 2)+ax*pow(cy, 2)-\
        pow(cy, 2)*bx+pow(ay, 2)*bx+pow(by, 2)*cx\
        -pow(ay, 2)*cx-pow(cx, 2)*bx+cx*pow(bx, 2))\
        /(ax*by-ax*cy-cx*by+cy*bx-bx*ay+cx*ay)
    else:
        return False
    
    r=pow(pow(x-ax, 2)+pow(y-ay, 2), .5)
    
    return x, y, r

def findpoint(eq1, eq2, point1, point2):
    '''find the centroid of the overlapping part of two circles
    from their equations'''
    thetabeg = math.acos((point1[0]-eq1[0])/eq1[2])
    thetaend = math.acos((point2[0]-eq1[0])/eq1[2])
    mid1x = eq1[2]*math.cos((thetabeg+thetaend)/2)+eq1[0]
    thetaybeg = math.asin((point1[1]-eq1[1])/eq1[2])
    thetayend = math.asin((point2[1]-eq1[1])/eq1[2])
    mid1y = eq1[2]*math.sin((thetaybeg+thetayend)/2)+eq1[1]

    thetabeg2 = math.acos((point1[0]-eq2[0])/eq2[2])
    thetaend2 = math.acos((point2[0]-eq2[0])/eq2[2])
    mid2x = eq2[2]*math.cos((thetabeg2+thetaend2)/2)+eq2[0]
    thetaybeg2 = math.asin((point1[1]-eq2[1])/eq2[2])
    thetayend2 = math.asin((point2[1]-eq2[1])/eq2[2])
    mid2y = eq2[2]*math.sin((thetaybeg2+thetayend2)/2)+eq2[1]
    return [(mid2x+mid1x)/2, (mid2y+mid1y)/2]

def interp_curve(curve, iterations):
    ''' Ordered list of points, the first and last affect the shape
    of the curve but are not connected though drawn'''
    
    new_curve = curve.copy()
    
    for j in range(0, iterations):
        newpoints = []
        for i in range(0, len(new_curve)-3):
            eq = circ(new_curve[i], new_curve[i+1], new_curve[i+2])
            eq2 = circ(new_curve[i+1], new_curve[i+2], new_curve[i+3])
            if eq == False or eq2 == False:
                newpoints.append([(new_curve[i+1][0]+new_curve[i+2][0])/2, (new_curve[i+1][1]+new_curve[i+2][1])/2])
            else:    
                newpoints.append(findpoint(eq, eq2, new_curve[i+1], new_curve[i+2]))
        for point in newpoints:
            point[0] = int(round(point[0]))
            point[1] = int(round(point[1]))
        for m in range(0, len(newpoints)):
            new_curve.insert(2*m+2, newpoints[m])
                          
def nearest_point(test_vert, vert_list):
    '''
    find the closest point to a test vert from a
    list of vertices
    
    Brute force
    Not fast
    not smart
    
    return index in list
    '''    
    
    lens = [None]*len(vert_list)
    
    for i,v in enumerate(vert_list):
        R = test_vert - v
        lens[i] = R.length
        
    smallest = min(lens)
    n = lens.index(smallest)
    
    return n
    
def intersect_paths(path1, path2, cyclic1 = False, cyclic2 = False, threshold = .00001):
    '''
    intersects vert paths
    
    returns a list of intersections (verts)
    returns a list of vert index pairs that corresponds to the
    first vert of the edge in path1 and path 2 where the intersection
    occurs
    
    eg...if the 10th of path 1 intersectts with the 5th edge of path 2
    
    return [[intersection verst],[inds],[inds]]
    
    Special cases are not handled well.  Eg..dont instersect two
    clover leaf paths!

    '''
    
    intersections = []
    inds_1 = []
    inds_2 = []
    
    for i in range(0,len(path1) + 1*cyclic1 - 1):
        
        n = int(math.fmod(i+1, len(path1)))
        v1 = path1[n]
        v2 = path1[i]
        for j in range(0,len(path2) + 1*cyclic2 - 1):
            
            m = int(math.fmod(j+1, len(path2)))
            v3 = path2[m]
            v4 = path2[j]
            
            #closes point on path1 edge, closes_point on path 2 edge
            
            intersect = intersect_line_line(v1,v2,v3,v4)
            
            if intersect:
                #make sure the intersection is within the segment
                inter_1 = intersect[0]
                verif1 = intersect_point_line(inter_1.to_3d(), v1.to_3d(),v2.to_3d())
                
                inter_2 = intersect[1]
                verif2 = intersect_point_line(inter_1.to_3d(), v3.to_3d(),v4.to_3d())
            
                diff = inter_2 - inter_1
                if diff.length < threshold and verif1[1] > 0 and verif2[1] > 0 and verif1[1] < 1 and verif2[1] < 1:
                    intersections.append(.5 * (inter_1 + inter_2))
                    inds_1.append(i)
                    inds_2.append(j)
    
    if len(set(inds_1)) != len(inds_1):
        print('    ')
        print('HELP, HELP, HELP, HELP, HELP, HELP, HELP, HELP, HELP,')
        print('there are multiple of the same index in intersection 1')
        print(inds_1)
        print(inds_2)
        print(intersections)
        doubles = find_doubles(inds_1)
        ind = inds_1.index(doubles[0],1)
        
        inds_1.pop(ind)
        inds_2.pop(ind)
        intersections.pop(ind)
        
    if len(set(inds_2)) != len(inds_2):
        print('    ')
        print('HELP, HELP, HELP, HELP, HELP, HELP, HELP, HELP, HELP,')
        print('HELP, there are multipl of the same index in intersection 2')
        print(inds_2)
        print(inds_1)
        print(intersections)
        
        doubles = find_doubles(inds_2)
        ind = inds_2.index(doubles[0],1)
        
        inds_1.pop(ind)
        inds_2.pop(ind)
        intersections.pop(ind)
        
    return intersections, inds_1, inds_2
                        
def  fit_path_to_endpoints(path,v0,v1):
    '''
    will rescale/rotate/tranlsate a path to fit between v0 and v1
    v0 is starting poin corrseponding to path[0]
    v1 is endpoint
    ''' 
    new_path = path.copy()
    
    vi_0 = path[0]
    vi_1 = path[-1]
    
    net_initial = vi_1 - vi_0
    net_final = v1 - v0
        
    scale = net_final.length/net_initial.length
    rot = rot_between_vecs(net_initial,net_final)
    
    
    for i, v in enumerate(new_path):
        new_path[i] = rot * v - vi_0
    
    for i, v in enumerate(new_path):
        new_path[i] = scale * v
            
    trans  = v0 - new_path[0]
    
    for i, v in enumerate(new_path):
        new_path[i] += trans
        
    return new_path
    
def pole_detector(bme):

    pole_inds = []
    
    for vert in bme.verts:
        if len(vert.link_edges) in {3,5,6}:
            pole_inds.append(vert.index)
            
    return pole_inds
            
def mix_path(path1,path2,pct = .5):
    '''
    will produce a blended path between path1 and 2 by
    interpolating each point along the path.
    
    will interpolate based on index at the moment, not based on  pctg down the curve
    
    pct is weight for path 1.
    '''
    
    if len(path1) != len(path2):
        print('eror until smarter programmer')
        return path1
    
    new_path = [0]*len(path1)
    
    for i, v in enumerate(path1):
        new_path[i] = v + pct * (path2[i] - v)
        
    return new_path
               
def align_edge_loops(verts_1, verts_2, eds_1, eds_2):
    '''
    Modifies vert order and edge indices to  provide best
    bridge between edge_loop1 and edge_loop2
    
    args:
        verts_1: list of Vectors
        verts_2: list of Vectors
        
        eds_1: connectivity of the first loop, really just to test loop or line
        eds_2: connectivity of 2nd loops, really just to test for loop or line
        
    return:
        verts_2
    '''
    print('testing alignment')
    if 0 in eds_1[-1]:
        cyclic = True
        print('cyclic vert chain')
    else:
        cyclic = False
    
    if len(verts_1) != len(verts_2):
        print(len(verts_1))
        print(len(verts_2))
        print('non uniform loops, stopping until your developer gets smarter')
        return verts_2
    
    
    #turns out, sum of diagonals is > than semi perimeter
    #lets exploit this (only true if quad is pretty much flat)
    #if we have paths reversed...our indices will give us diagonals
    #instead of perimeter
    #D1_O = verts_2[0] - verts_1[0]
    #D2_O = verts_2[-1] - verts_1[-1]
    #D1_R = verts_2[0] - verts_1[-1]
    #D2_R = verts_2[-1] - verts_1[0]
            
    #original_length = D1_O.length + D2_O.length
    #reverse_length = D1_R.length + D2_R.length
    #if reverse_length < original_length:
        #verts_2.reverse()
        #print('reversing')
        
    if cyclic:
        #another test to verify loop direction is to take
        #something reminiscint of the curl
        #since the loops in our case are guaranteed planar
        #(they come from cross sections) we can find a direction
        #from which to take the curl pretty easily.  Apologies to
        #any real mathemeticians reading this becuase I just
        #bastardized all these math terms.
        V1_0 = verts_1[1] - verts_1[0]
        V1_1 = verts_1[2] - verts_1[1]
        
        V2_0 = verts_2[1] - verts_2[0]
        V2_1 = verts_2[2] - verts_2[1]
        
        no_1 = V1_0.cross(V1_1)
        no_1.normalize()
        no_2 = V2_0.cross(V2_1)
        no_2.normalize()
        
        #we have no idea which way we will get
        #so just pick the directions which are
        #pointed in the general same direction
        if no_1.dot(no_2) < 0:
            no_2 = -1 * no_2
        
        #average the two directions    
        ideal_direction = no_1.lerp(no_1,.5)
    
        curl_1 = discrete_curl(verts_1, ideal_direction)
        curl_2 = discrete_curl(verts_2, ideal_direction)
        
        if curl_1 * curl_2 < 0:
            print('reversing loop 2')
            print('curl1: %f and curl2: %f' % (curl_1,curl_2))
            verts_2.reverse()
    
    else:
        #if the segement is not cyclic
        #all we have to do is compare the endpoints
        Vtotal_1 = verts_1[-1] - verts_1[0]
        Vtotal_2 = verts_2[-1] - verts_2[0]

        if Vtotal_1.dot(Vtotal_2) < 0:
            print('reversing path 2')
            verts_2.reverse()
            
    #iterate all verts and "handshake problem" them
    #into a dictionary?  That's not very effecient!
    edge_len_dict = {}
    for i in range(0,len(verts_1)):
        for n in range(0,len(verts_2)):
            edge = (i,n)
            vect = verts_2[n] - verts_1[i]
            edge_len_dict[edge] = vect.length
    
    shift_lengths = []
    #shift_cross = []
    for shift in range(0,len(verts_2)):
        tmp_len = 0
        #tmp_cross = 0
        for i in range(0, len(verts_2)):
            shift_mod = int(math.fmod(i+shift, len(verts_2)))
            tmp_len += edge_len_dict[(i,shift_mod)]
        shift_lengths.append(tmp_len)
           
    final_shift = shift_lengths.index(min(shift_lengths))
    if final_shift != 0:
        print("shifting verst by %i" % final_shift)
        verts_2 = list_shift(verts_2, final_shift)
                  
    return verts_2
    
def cross_section_until_plane(bme, mx, point, normal, seed, pt_stop, normal_stop, max_tests = 10000, debug = True):
    '''
    Takes a mesh and associated world matrix of the object and returns a cross secion in local
    space which stops when it intersects the plane defined by pt_stop, normal_stop
    
    Args:
        bme: Blender BMesh
        mx:   World matrix of the object to be cut(type Mathutils.Matrix)
        point: any point on the cut plane in world coords (type Mathutils.Vector)
        normal:  cut plane normal direction in world(type Mathutisl.Vector)
        seed: face index, typically achieved by raycast.
            a known face which intersects the cutplane.
        pt_stop:  point on the plane defined to stop cutting.  World Coords
                (type Mathutils.Vector)
        normal_stop: normal direction of the plane defined to stop cutting.  World COORD
        
    Return:
        list[Vector()]  in local coords
    '''
    
    times = []
    times.append(time.time())
    
    imx = mx.inverted()
    pt = imx * point
    pt_stop_local = imx * pt_stop
    no = imx.to_3x3() * normal
    normal_stop_local =  imx.to_3x3() * normal_stop

    verts = {}
    plane_hit = {}
    
    seeds = []
    prev_eds = []
    
    #the simplest expected result is that we find 2 edges
    for ed in bme.faces[seed].edges:         
        prev_eds.append(ed.index)
        
        A = ed.verts[0].co
        B = ed.verts[1].co
        result = cross_edge(A, B, pt, no)
        
        if result[0] and result[0] != 'CROSS':
            print('got an anomoly')
            print(result[0])

        #here we are only tesing the good cases
        if result[0] == 'CROSS':
            #create a list to hold the verst we find from this seed
            #start with the a point....go toward b
            #TODO: CODE REVIEW...this looks like stupid code.
            potential_faces = [face for face in ed.link_faces if face.index != seed]
            if len(potential_faces):
                f = potential_faces[0]
                seeds.append(f)
                verts[f.index] = [pt, result[1]]

    #TODO:  debug and return values?
    if len(seeds) == 0:
        print('failure to find a direction to start with')
        return None
    
    total_tests = 0
    for initial_element in seeds:
        element_tests = 0
        element = initial_element
        stop_test = None
        while element and total_tests < max_tests and not stop_test:
            total_tests += 1
            element_tests += 1

            if type(element) == bmesh.types.BMFace:
                element = face_cycle(element, pt, no, prev_eds, verts[initial_element.index])
                 
            elif type(element) == bmesh.types.BMVert:
                print('do we ever use the vert cycle?')
                element = vert_cycle(element, pt, no, prev_eds, verts[initial_element.index])
                
            if element:
                A = verts[initial_element.index][-2]
                B = verts[initial_element.index][-1]
                cross = cross_edge(A, B, pt_stop_local, normal_stop_local)
                stop_test = cross[0]
                if stop_test:
                    prev_eds.pop()  #will need to retest this edge in case we come around a full loop
                    verts[initial_element.index].pop()
                    verts[initial_element.index].append(cross[1])
                    plane_hit[initial_element.index] = True
                    
            else:
                plane_hit[initial_element.index] = False
      
        if total_tests-2 > max_tests:
            print('maxed out tests')
                   
        print('completed %i tests in this seed search' % element_tests)
                        
    
    #this iterates the keys in verts
    if len(verts):
        plane_chains = [verts[key] for key in verts if len(verts[key]) >= 2 and plane_hit[key]]
        loose_chains = [verts[key] for key in verts if len(verts[key]) >= 2 and not plane_hit[key]]
        
        print('%i chains hit the plane' % len(plane_chains))
        print('%i chains did not hit the plane' % len(loose_chains))
        
        
        #loose chains only
        if len(plane_chains) == 0 and len(loose_chains):
            if len(loose_chains) == 1:
                print('one loose chain')
                return loose_chains[0]
            else:
                print('best loose chain')
                return min(loose_chains, key=lambda x: distance_point_to_plane(x[-1], pt_stop_local, normal_stop_local))
                
                
        if len(plane_chains) == 1:
            print('single plane chain')
            return plane_chains[0]
        
        
        if len(plane_chains) > 1:
            print('best plane chain')
            return min(plane_chains, key=lambda x: get_path_length(x))
        #if one of each:
        #return the one what hit the plane
        #plane chains only
        #pick the shortest one    
    else:
        print('failed to find a cut that hit the plane...perhaps we dont intersect that plane')
        return None

def cross_section_2_seeds(bme, mx, point, normal, pt_a, seed_index_a, pt_b, seed_index_b, max_tests = 10000, debug = True):
    '''
    Takes a mesh and associated world matrix of the object and returns a cross secion in local
    space.
    
    Args:
        bme: Blender BMesh
        mx:   World matrix (type Mathutils.Matrix)
        point: any point on the cut plane in world coords (type Mathutils.Vector)
        normal:  plane normal direction (type Mathutisl.Vector)
        seed: face index, typically achieved by raycast
        exclude_edges: list of edge indices (usually already tested from previous iterations)
    '''
    
    times = []
    times.append(time.time())
    
    imx = mx.inverted()
    pt = imx * point
    no = imx.to_3x3() * normal
    
    
    #we will store vert chains here
    #indexed by the face they start with
    #after the initial seed facc
    #___________________
    #|     |     |      |
    #|  1  |init |  2   |
    #|_____|_____|______|
    #
    verts = {}
    
    
    #we need to test all edges of both faces for plane intersection
    #we should get intersections, because we define the plane
    #initially between the two seeds
    
    seeds = []
    prev_eds = []
    
    #the simplest expected result is that we find 2 edges
    for ed in bme.faces[seed_index_a].edges:
        
                  
        prev_eds.append(ed.index)
        
        A = ed.verts[0].co
        B = ed.verts[1].co
        result = cross_edge(A, B, pt, no)
        
        
        if result[0] and result[0] != 'CROSS':
            print('got an anomoly')
            print(result[0])
            print('that is the result ^')
        #here we are only tesing the good cases
        if result[0] == 'CROSS':
            #create a list to hold the verst we find from this seed
            #start with the a point....go toward b
            
            
            #TODO: CODE REVIEW...this looks like stupid code.
            potential_faces = [face for face in ed.link_faces if face.index != seed_index_a]
            if len(potential_faces):
                f = potential_faces[0]
                seeds.append(f)
                
                #we will keep track of our growing vert chains
                #based on the face they start with
                verts[f.index] = [pt_a]
                verts[f.index].append(result[1])
                
        
    #we now have 1 or two faces on either side of seed_face_a
    #now we walk until we do or dont find seed_face_b
    #this is a brute force, and we make no assumptions about which
    #direction is better to head in first.
    total_tests = 0
    for initial_element in seeds: #this will go both ways if they dont meet up.
        element_tests = 0
        element = initial_element
        stop_test = None
        while element and total_tests < max_tests and stop_test != seed_index_b:
            total_tests += 1
            element_tests += 1
            #first, we know that this face is not coplanar..that's good
            #if new_face.no.cross(no) == 0:
                #print('coplanar face, stopping calcs until your programmer gets smarter')
                #return None
            if type(element) == bmesh.types.BMFace:
                element = face_cycle(element, pt, no, prev_eds, verts[initial_element.index])#, edge_mapping)
                if element:
                    stop_test = element.index
                else:
                    stop_test = None
            
            elif type(element) == bmesh.types.BMVert:
                print('do we ever use the vert cycle?')
                element = vert_cycle(element, pt, no, prev_eds, verts[initial_element.index])#, edge_mapping)
                stop_test = None
        
        if stop_test == seed_index_b:
            print('found the other face!')
            verts[initial_element.index].append(pt_b)
            print('%i vertices found so far' % len(verts[initial_element.index]))
            
        else:
            #trash the vert data...we aren't interested
            #if we want to do other stuff later...we can
            #for now we will go on to the other side of
            #the seed face
            print('I think we made a loop w/o finding the intiial ege?')
            print('Perhaps we found a mesh edge?')
            #del verts[initial_element.index]
            
        if total_tests-2 > max_tests:
            print('maxed out tests')
                   
        #print('completed %i tests in this seed search' % element_tests)
                        
    
    #this iterates the keys in verts
    #i have kept the keys consistent for
    #verts
    if len(verts):
        
        #print('picking the shortest path by elements')
        #print('later we will return both paths to allow')
        #print('sorting by path length or by proximity to view')
        
        chains = [verts[key] for key in verts if len(verts[key]) > 2]
        if len(chains):
            sizes = [len(chain) for chain in chains]
            #print(sizes)
            best = min(sizes)
            ind = sizes.index(best)
        
            return chains[ind]
        else:
            print('failure no chains > 2 verts')
            return []
                    
    else:
        print('failed to find connection in either direction...perhaps points arent coplanar')
        return []


def cross_section_seed_ver0(bme, mx, 
                       point, normal, 
                       seed_index, 
                       max_tests = 10000, debug = True):
    '''
    Takes a mesh and associated world matrix of the object and returns a cross secion in local
    space.
    
    Args:
        bme: Blender BMesh
        mx:   World matrix (type Mathutils.Matrix)
        point: any point on the cut plane in world coords (type Mathutils.Vector)
        normal:  plane normal direction (type Mathutisl.Vector)
        seed_index: face index, typically achieved by raycast
        self_stop: a normal vector which defines a plane to stop cutting
        direction: Vector which the cut should start traveling.
        exclude_edges: list of edge indices (usually already tested from previous iterations)
    '''
    
    times = []
    times.append(time.time())

    verts =[]
    eds = []
    
    #convert point and normal into local coords
    imx = mx.inverted()
    pt = imx * point
    no = imx.to_3x3() * normal  #local normal

    #edge_mapping = {}  #perhaps we should use bmesh becaus it stores the great cycles..answer yup
    
    #first initial search around seeded face.
    #if none, we may go back to brute force
    #but prolly not :-)
    seed_search = 0
    prev_eds = []
    seeds =[]
    
    if seed_index > len(bme.faces) - 1:
        print('looks like we hit an Ngon, tentative support')
    
        #perhaps this should be done before we pass bme to this op?
        #we may perhaps need to re raycast the new faces?    
        ngons = []
        for f in bme.faces:
            if len(f.verts) >  4:
                ngons.append(f)
        
        #we should never get to this point because we are pre
        #triangulating the ngons before this function in the
        #final work flow but this leaves no chance and keeps
        #options to reuse this in later work      
        if len(ngons):
            new_geom = bmesh.ops.triangulate(bme, faces = ngons, use_beauty = True)
            new_faces = new_geom['faces']
            
            #now we must find a new seed index since we have added new geometry
            for f in new_faces:
                if point_in_tri(pt, f.verts[0].co, f.verts[1].co, f.verts[2].co):
                    print('found the point int he tri')
                    if distance_point_to_plane(pt, f.verts[0].co, f.normal) < .0000001:
                        seed_index = f.index
                        print('found a new index to start with')
                        break

    for ed in bme.faces[seed_index].edges:
        seed_search += 1        
        prev_eds.append(ed.index)
        
        A = ed.verts[0].co
        B = ed.verts[1].co
        result = cross_edge(A, B, pt, no)
        if result[0] == 'CROSS':
            potential_faces = [face for face in ed.link_faces if face.index != seed_index]
                
            if len(potential_faces):
                f = potential_faces[0]
                verts.append(result[1])
                seeds.append(f)
            
    if not len(seeds):
        print('cancelling until your programmer gets smarter')
        return (None,None)
        
    #we have found one edge that crosses, now, baring any terrible disconnections in the mesh,
    #we traverse through the link faces, wandering our way through....removing edges from our list
    total_tests = 0
    
    #We find A then B then start at A... so there is a
    #reverse in the vert order at the middle.
    verts.reverse()
    for element in seeds: #this will go both ways if they dont meet up.
        element_tests = 0
        while element and total_tests < max_tests:
            total_tests += 1
            element_tests += 1
            #first, we know that this face is not coplanar..that's good
            #if new_face.no.cross(no) == 0:
                #print('coplanar face, stopping calcs until your programmer gets smarter')
                #return None
            if type(element) == bmesh.types.BMFace:
                element = face_cycle(element, pt, no, prev_eds, verts)#, edge_mapping)
            
            elif type(element) == bmesh.types.BMVert:
                element = vert_cycle(element, pt, no, prev_eds, verts)#, edge_mapping)
                
        #print('completed %i tests in this seed search' % element_tests)
        #print('%i vertices found so far' % len(verts))
        
 
    #The following tests for a closed loop
    #if the loop found itself on the first go round, the last test
    #will only get one try, and find no new crosses
    #trivially, mast make sure that the first seed we found wasn't
    #on a non manifold edge, which should never happen
    #TODO:  find a better way to determine this. Currently we dont preserve
    #enough information
    closed_loop = element_tests == 1 and len(seeds) == 2
    
              
    if debug:
        n = len(times)
        times.append(time.time())
        #print('calced intersections %f sec' % (times[n]-times[n-1]))
       
    #iterate through smartly to create edge keys
    #no longer have to do this...verts are created in order
    
    if closed_loop:        
        for i in range(0,len(verts)-1):
            eds.append((i,i+1))
        
        #the edge loop closure
        eds.append((i+1,0))
        
    else:
        #two more verts found than total tests
        #one vert per element test in the last loop
        
        
        #split the loop into the verts into the first seed and 2nd seed
        seed_1_verts = verts[:len(verts)-(element_tests)] #yikes maybe this index math is right
        seed_2_verts = verts[len(verts)-(element_tests):]
        seed_2_verts.reverse()
        seed_2_verts.extend(seed_1_verts)
        
        for i in range(0,len(seed_1_verts)-1):
            eds.append((i,i+1))
    
        verts = seed_2_verts
    if debug:
        n = len(times)
        times.append(time.time())
        #print('calced connectivity %f sec' % (times[n]-times[n-1]))
        
    if len(verts):
            
        return (verts, eds)
    else:
        return (None, None)



def find_bmedges_crossing_plane(pt, no, edges, epsilon):
    '''
    returns list of edges that *cross* plane and corresponding intersection points
    '''
    
    coords = {}
    for edge in edges:
        v0,v1 = edge.verts
        if v0 not in coords: coords[v0] = no.dot(v0.co-pt)
        if v1 not in coords: coords[v1] = no.dot(v1.co-pt)
    #print(str(coords))
    
    ret = []
    for edge in edges:
        v0,v1 = edge.verts
        s0,s1 = coords[v0],coords[v1]
        if s0 > epsilon and s1 > epsilon: continue
        if s0 < -epsilon and s1 < -epsilon: continue
        #if not ((s0>epsilon and s1<-epsilon) or (s0<-epsilon and s1>epsilon)):      # edge cross plane?
        #    continue
        
        i = intersect_line_plane(v0.co, v1.co, pt, no)
        ret += [(edge,i)]
    return ret

def find_distant_bmedge_crossing_plane(pt, no, edges, epsilon, eind_from, co_from):
    '''
    returns the farthest edge that *crosses* plane and corresponding intersection point
    '''
    
    if(len(edges)==3):
        # shortcut (no need to find farthest... just find first)
        for edge in edges:
            if edge.index == eind_from: continue
            v0,v1 = edge.verts
            co0,co1 = v0.co,v1.co
            s0,s1 = no.dot(co0 - pt), no.dot(co1 - pt)
            no_cross = not ((s0>epsilon and s1<-epsilon) or (s0<-epsilon and s1>epsilon))
            if no_cross: continue
            i = intersect_line_plane(co0, co1, pt, no)
            return (edge,i)
    
    d_max,edge_max,i_max = -1.0,None,None
    for edge in edges:
        if edge.index == eind_from: continue
        
        v0,v1 = edge.verts
        co0,co1 = v0.co, v1.co
        s0,s1 = no.dot(co0 - pt), no.dot(co1 - pt)
        if s0 > epsilon and s1 > epsilon: continue
        if s0 < -epsilon and s1 < -epsilon: continue
        #if not ((s0>epsilon and s1<-epsilon) or (s0<-epsilon and s1>epsilon)):      # edge cross plane?
        #    continue
        
        i = intersect_line_plane(co0, co1, pt, no)
        d = (co_from - i).length
        if d > d_max: d_max,edge_max,i_max = d,edge,i
    return (edge_max,i_max)

def cross_section_walker(bme, pt, no, find_from, eind_from, co_from, epsilon):
    '''
    returns tuple (verts,looped) by walking around a bmesh near the given plane
    verts is list of verts as the intersections of edges and cutting plane (in order)
    looped is bool indicating if walk wrapped around bmesh
    '''

    # returned values
    verts = [co_from]
    looped = False
    
    # track what we've seen
    finds_dict = {find_from: 0}

    # get blender version
    bver = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])

    if bver > '002.072.000':
        bme.edges.ensure_lookup_table();

    f_cur = next(f for f in bme.edges[eind_from].link_faces if f.index != find_from)
    find_current = f_cur.index
    
    while True:
        # find farthest point
        edge,i = find_distant_bmedge_crossing_plane(pt, no, f_cur.edges, epsilon, eind_from, co_from)
        verts += [i]
        if len(edge.link_faces) == 1: break                                     # hit end?
        
        # get next face, edge, co
        f_next = next(f for f in edge.link_faces if f.index != find_current)
        find_next = f_next.index
        eind_next = edge.index
        co_next   = i
        
        if find_next in finds_dict:                                             # looped
            looped = True
            if finds_dict[find_next] != 0:
                # loop is P-shaped (loop with a tail)
                verts = verts[finds_dict[find_next]:]      # clip off tail
            break
        
        # leave breadcrumb
        finds_dict[find_next] = len(finds_dict)
        
        find_from = find_current
        eind_from = eind_next
        co_from   = co_next
        
        f_cur = f_next
        find_current = find_next
    
    return (verts,looped)

def cross_section_seed_ver1(bme, mx, 
                       point, normal, 
                       seed_index, 
                       max_tests = 10000, debug = True):
    
    # data to be returned
    verts,edges = [],[]
    
    # max distance a coplanar vertex can be from plane
    epsilon = 0.0000000001
    
    #convert plane defn (point and normal) into local coords
    imx = mx.inverted()
    pt  = imx * point
    no  = (imx.to_3x3() * normal).normalized()

    # get blender version
    bver = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])

    if bver > '002.072.000':
        bme.faces.ensure_lookup_table();

    # make sure that plane crosses face!
    lco = [v.co for v in bme.faces[seed_index].verts]
    ld = [no.dot(co - pt) for co in lco]
    if all(d > epsilon for d in ld) or all(d < -epsilon for d in ld):               # does face cross plane?
        # shift pt so plane crosses face
        shift_dist = (min(ld)+epsilon) if ld[0] > epsilon else (max(ld)-epsilon)
        pt += no * shift_dist
        print('>>> shifting')
        print('>>> ' + str(ld))
        print('>>> ' + str(shift_dist))
        print('>>> ' + str(no*shift_dist))
    
    # find intersections of edges and cutting plane
    bmface = bme.faces[seed_index]
    bmedges = bmface.edges
    ei_init = find_bmedges_crossing_plane(pt, no, bmedges, epsilon)
    
    if len(ei_init) < 2:
        print('warning: it should not reach here! len(ei_init) = %d' % len(ei_init))
        print('lengths = ' + str([(edge.verts[0].co-edge.verts[1].co).length for edge in bmedges]))
        return (None,None)
    elif len(ei_init) == 2:
        # simple case
        ei0_max, ei1_max = ei_init
    else:
        # convex polygon
        # find two farthest points
        d_max, ei0_max, ei1_max = -1.0, None, None
        for ei0,ei1 in combinations(ei_init, 2):
            d = (ei0[1] - ei1[1]).length
            if d > d_max: d_max,ei0_max,ei1_max = d,ei0,ei1
    
    # start walking one way around bmesh
    verts0,looped = cross_section_walker(bme, pt, no, seed_index, ei0_max[0].index, ei0_max[1], epsilon)
    
    if looped:
        # looped around on self, so we're done!
        verts = verts0
        nv = len(verts)
        edges = [(i,(i+1)%nv) for i in range(nv)]
        
        return (verts, edges)
    
    # did not loop around, so start walking the other way
    verts1,looped = cross_section_walker(bme, pt, no, seed_index, ei1_max[0].index, ei1_max[1], epsilon)
    
    if looped:
        # looped around on self!?
        print('warning: looped one way but not the other')
        verts = verts1
        nv = len(verts)
        edges = [(i,(i+1)%nv) for i in range(nv)]
        
        return (verts, edges)
    
    # combine two walks
    verts = list(reversed(verts0)) + verts1
    nv = len(verts)
    edges = [(i,i+1) for i in range(nv-1)]
    
    return (verts, edges)



def cross_section_seed(bme, mx, 
                       point, normal, 
                       seed_index, 
                       max_tests = 10000, debug = True, method = False):
    '''
    Takes a mesh and associated world matrix of the object and returns a cross secion in local
    space.
    
    Args:
        bme: Blender BMesh
        mx:   World matrix (type Mathutils.Matrix)
        point: any point on the cut plane in world coords (type Mathutils.Vector)
        normal:  plane normal direction (type Mathutisl.Vector)
        seed_index: face index, typically achieved by raycast
        self_stop: a normal vector which defines a plane to stop cutting
        direction: Vector which the cut should start traveling.
        exclude_edges: list of edge indices (usually already tested from previous iterations)
    '''
    
    start = time.time()
    
    if not method:
        ret = cross_section_seed_ver0(bme, mx, point, normal, seed_index, max_tests, debug)

    else:
        ret = cross_section_seed_ver1(bme, mx, point, normal, seed_index, max_tests, debug)
    
    calc_time = time.time()
    
    print('the new method was used: %r' % method)
    if ret[0]:
        print('%i verts were found in %f seconds' % (len(ret[0]), (calc_time - start)))
    else:
        print('Cutting failed')
    
    return ret

def cross_section_seed_direction(bme, mx, 
                                 point, normal, 
                                 seed_index, direction, 
                                 stop_plane = None,
                                 max_tests = 10000,
                                 debug = True):
    '''
    Takes a bmesh and associated world matrix of the object and 
    returns a cross secion in local space.  
    bmesh should not have any ngons (tris and quads only).  
    If original bmesh has ngons, triangulate the bmesh
    or a copy of the bmesh first.
    
    Args:
        bme: Blender BMesh
        mx:   World matrix (type Mathutils.Matrix)
        point: any point on the cut plane in world coords (type Mathutils.Vector)
        normal:  plane normal direction (type Mathutisl.Vector)
        seed_index: face index, typically achieved by raycast
        direction: Vector which the cut should start traveling.
        
        stop_plane = [stop_pt, stop_no]  a 2 item list of 2 vectors defining a plane to stop at
    '''
    
    times = []
    times.append(time.time())

    #convert point and normal directoin into local coords
    imx = mx.inverted()
    pt = imx * point
    no = imx.to_3x3() * normal  #local normal
    direct = imx.to_3x3() * direction
    direct.normalize()

    if stop_plane:
        stop_pt = imx * stop_plane[0]
        stop_no = imx.to_3x3() * stop_plane[1]

    prev_eds = []
    seeds = {}  #a list of 0,1, or 2 edges.
    
    #return values
    verts =[]
    eds = []
                   
    for ed in bme.faces[seed_index].edges:  #should be 3 or 4 edges
        prev_eds.append(ed.index)
        A = ed.verts[0].co
        B = ed.verts[1].co
        result = cross_edge(A, B, pt, no)
        if result[0] == 'CROSS':
            
            verts.append(result[1])
            potential_faces = [face for face in ed.link_faces if face.index != seed_index]
               
            if len(potential_faces):

                f = potential_faces[0]
                seeds[len(verts)-1] = f

            else:
                seeds[len(verts)-1] = None
                print('seed face is an edge of mesh face')
    
    if len(verts) < 2:
        print('critical error, probably machine error (len(verts) = %d)' % len(verts))
        #TODO: debug and dump relevant info
        return (None, None)
    
    elif len(verts) > 2:
        print('critial error probably concave ngon or something (len(verts) = %d)' % len(verts))
        #TODO: debug and dump relevant info
        return (None, None) 
      
    else:
        headed = verts[0] - verts[1]
        headed.normalize()
       
        if headed.dot(direct) > .1:
            element = seeds[0]
            verts.pop(1)
            verts.insert(0,pt)
            
            if not element:
                return (verts,[(0,1)])
        else:
            element = seeds[1]
            verts.pop(0)
            verts.insert(0,pt)
            
            if not element:
                return (verts,[(0,1)])
            
    total_tests = 0
    stop_test = False
    
    while element and total_tests < max_tests and not stop_test:
        total_tests += 1
        #first, we know that this face is not coplanar..that's good
        #if new_face.no.cross(no) == 0:
            #print('coplanar face, stopping calcs until your programmer gets smarter')
            #return None
        if type(element) == bmesh.types.BMFace:
            element = face_cycle(element, pt, no, prev_eds, verts)#, edge_mapping)
        
        elif type(element) == bmesh.types.BMVert:
            #TODO: I would like to debug if we hit a
            #vert
            element = vert_cycle(element, pt, no, prev_eds, verts)#, edge_mapping)

        if element and stop_plane and total_tests > 1:
            A = verts[-2]
            B = verts[-1]
            cross = cross_edge(A, B, stop_pt, stop_no)
            stop_test = cross[0]
            if stop_test:
                prev_eds.pop()  #will need to retest this edge in case we come around a full loop
                verts.pop()
                verts.append(cross[1])
    
    #verts are created in order
    for i in range(0,len(verts)-1):
        eds.append((i,i+1))
        
    if debug:
        n = len(times)
        times.append(time.time())
        #print('calced connectivity %f sec' % (times[n]-times[n-1]))
        
    if len(verts):  
        return (verts, eds)
    else:
        return (None, None)
    
    
def intersect_path_plane(verts, pt, no, mode = 'FIRST'):
    '''
    Inds the intersection of a vert chain with a plane
    for cyclic vert paths duplicate end vert..
    may add cyclic  test later.
    mode will determine if only the first intersection is returned
    or all the intersections of a path with a plane.
    
    args:
        verts:  list of vectors type mathutils.Vector
        pt: plane pt
        no: plane normal for intersection
        mode:  enum in 'FIRST', 'ALL'
        
    return:
        a list of intersections or None
    '''
    
    #TODO:  input quality checks for variables
    
    intersects = []
    n = len(verts) if verts else 0
    
    for i in range(0,n-1):
        cross = cross_edge(verts[i], verts[i+1], pt, no)
        
        if cross[0]:
            intersects.append(cross[1])
            
            if mode == 'FIRST':
                break
            
    if len(intersects) == 0:
        intersects = [None]
        
    return intersects