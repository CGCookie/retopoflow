'''
Created on Jul 18, 2015

@author: Patrick
'''
from itertools import chain
import math

from mathutils import Vector, Matrix, Quaternion
from mathutils.geometry import  intersect_line_line
from .pat_patch import identify_patch_pattern

import bmesh
from .lib.common_mesh import edge_loops_from_bmedges, find_edge_loops, make_bme, find_perimeter_verts, join_bmesh

def find_coord(bme, v_search, vert_list = []):
    '''
    brute dumb force  clsest vert algo
    '''
    bme.verts.ensure_lookup_table()
    bme.verts.index_update()
    
    if vert_list != []:
        ds = []
        for i in vert_list:
            v = bme.verts[i]
            ds += [(v_search-v.co).length]
            
        best = min(ds)
        ind = ds.index(best)
        #print('Find Coord')
        #print(ds)
        #print(min(ds))
        #print(ind)
        return vert_list[ind]
    
    else:
        ds = []
        for v in bme.verts:
            ds += [(v_search-v.co).length]
        
        best = min(ds)
        ind = ds.index(best)
        #print('Find Coord')
        #print(ds)
        #print(min(ds))
        #print(ind)
        return ind
            
    
def relax_bmesh(bme, exclude, iterations = 1, spring_power = .1, quad_power = .1):
    '''
    takes verts
    '''
    for j in range(0,iterations):
        deltas = dict()
        #edges as springs
        for i, bmv0 in enumerate(bme.verts):
            
            if bmv0.index in exclude: continue
            
            lbmeds = bmv0.link_edges
            net_f = Vector((0,0,0))
            
            for bmed in lbmeds:
                bmv1 = bmed.other_vert(bmv0)
                net_f += bmv1.co - bmv0.co
                
            deltas[bmv0.index] = spring_power*net_f  #todo, normalize this to average spring length?
            
        
        #cross braces on faces, try to expand face to square
        for bmf in bme.faces:
            if len(bmf.verts) != 4: continue
            
            dia0 = bmf.verts[2].co - bmf.verts[0].co
            dia1 = bmf.verts[3].co - bmf.verts[1].co
            
            avg_l = .5 * dia0.length + .5 * dia1.length
            
            d0 = .5 * (dia0.length - avg_l)
            d1 = .5 * (dia1.length - avg_l)
            
            dia0.normalize()
            dia1.normalize()
            
            #only expand, no tension
            if bmf.verts[0].index not in exclude:
                deltas[bmf.verts[0].index] += quad_power * d0 * dia0
            if bmf.verts[2].index not in exclude:
                deltas[bmf.verts[2].index] += -quad_power * d0 * dia0
        
            if bmf.verts[1].index not in exclude:
                deltas[bmf.verts[1].index] += quad_power * d1 * dia1
            if bmf.verts[3].index not in exclude:
                deltas[bmf.verts[3].index] += -quad_power * d1 * dia1  
                  
        for i in deltas:
            bme.verts[i].co += deltas[i]
    

def quadrangulate_verts(c0,c1,c2,c3,x,y, x_off = 0, y_off = 0):
    '''
    simple grid interpolation of 4 points, not necessarily planar points
    
    
    c0, c1, c2, c3 are the 4 corners of the quad
    x, number of subdivisions along the x, axis (eg, loop cuts parallel to y axis)
    y, number of subdivisions along the y axis (eg, loop cuts parallel to x axis)
    x_off, leave off this number of ROW off the bottom
    y_off, leave out this number of COLUMS off the left side
    
    x_axis = C1 - C0  (final - initial)
    y_axis = C3 - C0  (final - initial)
    
    
    first column goes from C0 to C3
    final column goes from C1 to C2
    
    the width of the array is y + 2 - y_off
    the height of the array is x + 2 - x_off
    
    
    '''
    bottom = []
    right_side = []
    top = []
    left_side = []
    
    verts = []
    faces = []
    for i in range(x_off,y+2): #iterates across the row
        A= i/(y+1)
        B = 1- A
        
        for j in range(y_off,x+2):  #iterates up the column
            
            
            C = j/(x+1)
            D = 1-C
            v = B*D*c0 + A*D*c1 + A*C*c2 + B*C*c3
            verts += [v]

            
            if i != y+1 and j == y_off:
                bottom += [len(verts) -1]
            elif i == x_off and j != y_off:
                left_side += [len(verts) -1]
            elif i == y + 1 and j != x+1:
                right_side += [len(verts)-1]
            elif j == x + 1 and i != x_off:
                top += [len(verts) - 1]
            
    top.reverse()
    left_side.reverse()
    print((bottom, right_side, top, left_side))
    
    for i in range(0, y+1-y_off):
        for j in range(0,x+1-x_off):
            A = i*(x+2) + j
            B = (i+1)*(x+2) + j
            C = B + 1
            D = A + 1
            faces += [(A,B,C,D)]
    
    print(faces)
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    geom_dict['perimeter'] = bottom + right_side + top + left_side     
    return geom_dict

def subdivide_edge(v0,v1,N):
    '''
    returns line segment subdivided for N edges bewteen p0 and p1
    '''
    vs = []
    for i in range(0,N+1):
        vs += [i/N*v1 + (1-i/N)*v0]                     
    return vs
    
def face_strip(vs_0, vs_1):
    '''
    returns indexing for 2 parallel and matched vert index strips
    '''
    faces = []
    N = min(len(vs_0)-1, len(vs_1)-1) #allow mismatched vert strips to not crash
    for i in range(0,N):
        a = vs_0[i]
        b = vs_1[i]
        c = vs_1[i+1]
        d = vs_0[i+1]
        faces += [(a,b,c,d)]
    return faces

def add_offset_to_faces(faces, offset):
    '''
    edit's face indices in place to reflect adding a new list of verts
    (which has existing face mapping) to an existing list of verts.
    '''
    new_faces = []
    for f in faces:
        (a,b,c,d) = f
        new_faces += [(a+offset, b+offset, c+offset, d+offset)]
        
    return new_faces
        
def calc_weights_vert_path(vs, flip = False):
    '''
    weight is returned as list of fraction of total path length
    '''
    S = 0 #mathy symbol for path length
    ws = [0]
    for i in range(1,len(vs)):
        S += i
        #S += (vs[i] - vs[i-1]).length
        ws += [S]
    
    fw = [1/S * w for w in ws]
    rw = [1 - 1/S * w for w in ws]
    rw.reverse()
    
    #print([str(w)[0:4] for w in fw])
    #print([str(w)[0:4] for w in rw])
    if not flip:
        return fw
    else:
        return rw

def n_of_i_j(X, Y, i, j):
    '''
    given an X x Y grid of verts constructed colum by colum from x=0 to x=X
    into a list of length = X*Y
    
    return the n'th index of a vert in the list given i, j
    return -1 if i or j out of range
    '''
    #i = min(i,X)  #correct for
    #j = min(j,Y)
    if (i > X-1) or (j > Y-1): return -1
    n = i*Y + j
    return n

def blend_side_primary(V_edges, n_side, pad = 'max'):
    '''
    args:
        V_edges = list of [list of verts]: represents vert loop sides of the polygon
                  V_edges[0][-1] = V_edges[1][0]  eg...the corners are duplicated
                  
        n_side - integer:  The side to be blended with adjacent sides
        
        pad - integer or string 'max':  How far along the adjacent sides to extrude
                                        the padding side
    
    '''
    N = len(V_edges)  #number of sides of polygon
    if N < 3: return
    
    #get index of n-1, n, n+1
    n_m1, n, n_p1 = (n_side - 1) % N, n_side, (n_side + 1) % N
    
    vs_nm1, vs_n, vs_np1 =  V_edges[n_m1][::-1], V_edges[n], V_edges[n_p1]  #notice vs_nm1 are reversed
                                               
    ws_n = calc_weights_vert_path(vs_n)
    
    max_p = min(len(vs_nm1)-1, len(vs_np1)-1)  #maximum depth of padding on this side
    if pad == 'max':
        max_y = max_p
    elif pad > max_p:
        max_y = max_p
    else:
        max_y = pad
    
    verts = vs_nm1[0:max_y] #slice off the left side verts up to the max padding depth
    for xi in range(1,len(vs_n)-1):
        verts += [vs_n[xi]] #get the bottom anchor point
        for yi in range(1, max_y):
            vec_nm1 = vs_nm1[yi] - vs_nm1[yi-1]  #vector representation of corresponding segment on bordering edgeloop
            vec_np1 = vs_np1[yi] - vs_np1[yi-1]
    
            prev_vert = verts[-1]  #since we are zipping straight up each column
            verts += [prev_vert + (1-ws_n[xi])*vec_nm1 + ws_n[xi]*vec_np1]
    verts += vs_np1[0:max_y]
    
    return verts

def blend_adjacent_sides(SD_nm1, SD_n, SD_np1):
    '''
    SD = side_data = Tuple ([list verts], X, Y, W)
    verts = list of verts
    X = width of side verts = subvidivion of that side + 1
    Y = pading depth
    W = list of weights, calculated as the vertex position as % of the side length.
    
    returns new side data, does not modifiy
    '''
    
    def n_w_of_i_j_prev(i,j,X,Y,X_prev, Y_prev, ws_nm1):
        '''
        takes i,j index in current side
        X, Y dimensions of current padding
        X_prev, Y_prev dimensions of previous padding
        
        returns n index in previous verts        
        '''
        i_nm1 = X_prev - j
        j_nm1 = i
        
        if i > Y_prev-1:#todo, possible Y_prev -1 or >=
            return -1, -1
        if i_nm1 < 0:
            print('we have a problem!, bad indexing somehow')
        n_nm1 = (i_nm1 -1)*Y_prev + j_nm1
        w_nm1 = ws_nm1[i_nm1]
        
        return n_nm1, w_nm1
    
    def n_w_of_i_j_next(i,j,X,Y,X_next, Y_next, ws_np1):
        '''
        takes i,j index in current side
        X, Y dimensions of current padding. X is the subdivision of this side, Y is padding depth
        X_prev, Y_prev dimensions of previous padding
        
        returns n index in previous verts
        
        link to image showing indexing schema #TODO#        
        '''
        i_np1 = j
        j_np1 = X - i
        
        if j_np1 > Y_next: #todo, possible Y_next -1 or >=
            return -1, -1
        if j_np1 < 0:
            print('we have a problem!, bad indexing somehow')
        n_np1 = (i_np1)*Y_next + j_np1 - 1
        w_np1 = ws_np1[i_np1]
        
        return n_np1, w_np1    
        
    vs_nm1, Xnm1, Ynm1,  Wnm1  = SD_nm1[0], SD_nm1[1], SD_nm1[2], SD_nm1[3]
    vs_n,     Xn,   Yn,    Wn  =   SD_n[0],   SD_n[1],   SD_n[2],   SD_n[3]
    vs_np1, Xnp1, Ynp1,  Wnp1  = SD_np1[0], SD_np1[1], SD_np1[2], SD_np1[3]
    
    new_verts = vs_n[0:Yn]  #left boundary get's kept, but, it could technically get kept by proper weighting?
    for xi_n in range(1, Xn-1):
        i = n_of_i_j(Xn, Yn, xi_n, 0) #bottom boundary single vert get's passed through.  Ditto above with proper weighting
        new_verts += [vs_n[i]]
        for yi_n in range(1, Yn):
            i = n_of_i_j(Xn, Yn, xi_n, yi_n)
            vn = vs_n[i]  #native vertex to this side
            wn = Wn[xi_n]
            
            i_np1, w_np1 = n_w_of_i_j_next(xi_n, yi_n, Xn, Yn, Xnp1, Ynp1, Wnp1)
            i_nm1, w_nm1 = n_w_of_i_j_prev(xi_n, yi_n, Xn, Yn, Xnm1, Ynm1, Wnm1)
            
            if i_np1 != -1 and i_nm1 != -1:
                #print('index in this side, index in next side, index in prev side')
                #print((i, i_np1, i_nm1))
                v_np1 = vs_np1[i_np1]
                v_nm1 = vs_nm1[i_nm1]
                
                #coef_vn = 1 - w_nm1 - wn + wn*w_nm1 + wn*w_np1
                #coef_vnp1 =  wn*(1-w_np1)
                #coef_vnm1 =  (1-wn)*(w_nm1)
                #v_new = (1-wn)*((1-w_nm1)*vn + w_nm1*v_nm1) + wn*((1-w_np1)*v_np1 + w_np1*vn)
                
                #coef_vn = w_nm1 + (1-w_np1)
                #coef_vnp1 =  wn
                #coef_vnm1 = 1- wn
                #coef_sum = coef_vn + coef_vnp1 + coef_vnm1
                
                #coef_vnm1 =  (1-wn)*(w_nm1)
                #v_new = 1/coef_sum * (coef_vn*vn + coef_vnm1*v_nm1 + coef_vnp1*v_np1)
                #print('Coef Vn %f' % coef_vn)
                #print('Coef V n-1 %f' % coef_vnm1)
                #print('Coef V n+1 %f' % coef_vnp1)
                
                
                v_new = .5*vn + .5 * ((1-wn) * v_nm1 + wn*v_np1) #may experiment with this weighting
                new_verts += [v_new]
                #new_verts += [vn]  #actually...if 3 are involved, fuck em all
                
            elif i_np1 != -1 and i_nm1 == -1:
               
                v_np1 = vs_np1[i_np1]
                
                #coef_vn = w_np1*(1-wn)
                #coef_vnp1 =  (1-w_np1) * wn
                #v_new = (1-w_np1) * wn * v_np1 + w_np1 * (1-wn) * vn
                
                #coef_vn = (1-w_np1)
                #coef_vnp1 =  wn
                #coef_sum = coef_vn + coef_vnp1
                
                #print('Coef total %f' % coef_sum)
                #print('Coef Vn %f' % coef_vn)
                #print('Coef V n+1 %f' % coef_vnp1)
                #
                #v_new = 1/coef_sum * (coef_vn*vn + coef_vnp1*v_np1)
                v_new = 1/2*vn +  1/2*v_np1
                new_verts += [v_new]
                #new_verts += [vn]
            
            elif i_np1 == -1 and i_nm1 != -1:
                v_nm1 = vs_nm1[i_nm1]
                v_new = 1/2*vn + 1/2*v_nm1
                new_verts += [v_new]
                #new_verts += [vn]
                
            else:
                #print('no verts to blend')
                new_verts += [vn]
                    
    #right boundary gets passed through #it could technically get kept by proper weighting?
    new_verts += vs_n[len(vs_n) - Yn:len(vs_n)]  
    
    return new_verts

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
    
    if v1.length < .00000001:
        print('0 length vecs')
        mx = Matrix.Identity(3)
        return mx.to_quaternion()
    
    if v2.length < .000000001:
        print('parallel vecs')
        mx = Matrix.Identity(3)
        return mx.to_quaternion()
    
    if 1 - abs(v1.dot(v2)) < .0000001:
        print('parallel vecs')
        mx = Matrix.Identity(3)
        return mx.to_quaternion()
    
    angle = factor * v1.angle(v2)
    axis = v1.cross(v2)
    axis.normalize()
    sin = math.sin(angle/2)
    cos = math.cos(angle/2)
    
    quat = Quaternion((cos, sin*axis[0], sin*axis[1], sin*axis[2]))
    
    return quat

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
    
    
    dv1 = (v1 - vi_1).length
    dv0 = (v0 - vi_0).length
    
    if dv1 < .0000001 and dv0 < .0000001:
        #print('not really changing endpoints')
        return path.copy()
      
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

def blend_doublet(V_edges, ps = [], side = 'all'):
    '''
    args:
        V_edges = list of [list of verts] along an edge loop which represents a side of the polygon
                  V_edges[0][-1] = V_edges[1][0]  eg...the corners are duplicated
                  
        ps = padding to slice off of each side

    returns dictionary with keys
      'verts'   list of corner patches of verts.  If a single corner
                is specified, a single element list containing a list of vertices
      'dimensions'  list of (x,y) pairs representing the dimensions of the vertex array.  
                    (L+1, p+1) (one more vert than faces in each direction)
    
    '''
    def n_of_i_j_prev(i,j,X,Y,X_prev, Y_prev):
        '''
        takes i,j index in current side
        X, Y dimensions of current padding
        X_prev, Y_prev dimensions of previous padding
        
        returns n index in previous verts
        
        This is different than the other n_of_i_j because in this scenario
        the verts are stored in rows since they are constructed from the 
        edge loops defining the boundaries   
        '''
        i_nm1 = X_prev - j
        j_nm1 = i
        
        if i > Y_prev-1:#todo, possible Y_prev -1 or >=
            return -1, -1
        if i_nm1 < 0:
            print('we have a problem!, bad indexing somehow')
        n_nm1 = j_nm1*X_prev + i_nm1 - 1
        return n_nm1
    
    def n_of_i_j_cur(X,Y,i,j):
        '''
        given an X x Y grid of verts constructed row by row from x=0 to x=X
        into a list of length = X*Y
        '''
        n = j*X + i
        return n
        
        
    N = len(V_edges)        
    L = [len(v_edge)-1 for v_edge in V_edges]  #this is the actual # of edges, or the number of times the patch side is subdivided
    W = [calc_weights_vert_path(v_edge) for v_edge in V_edges]  #all going same direction around polygon

    if N != len(L) != 2:
        print('dimensions mismatch')
        return {}
    
    #this determines how far across the patch an edge can be
    #interpolated.  It is limited by the subdivision of the
    #opposing sides
    max_pads = [math.floor((L[1]-1)/2), math.floor((L[0]-1/2))]

    #this is the desired padding by the user.  Eventually
    #this will be a required variable.  For now, if none
    #specified, just return the max padding
    if ps == []:
        pads = max_pads
    else:
        pads = [min(p,mp) for p,mp in zip(ps, max_pads)]
        
    geom_dict = {}
    
    #first round interpolation, use maximum padding across the patch  
    sides_interp = []
    for i in range(0,2):
        interps = []
        if i == 0:
            other_path = V_edges[1].copy()
        else:
            other_path = V_edges[0].copy()
        other_path.reverse()
        
        for n in range(0, pads[i]+1):
            l = len(other_path)
            v0 = other_path[n]
            v1 = other_path[l-1-n]
            interps += fit_path_to_endpoints(V_edges[i], v0, v1)
        
        sides_interp += [interps]        
        
    #blending corner 0
    for i in range(0, pads[1]+1):
        for j in range(0, pads[0]+1):
            
            n = n_of_i_j_cur(L[0]+1, pads[0]+1, i, j)
            n_prev = n_of_i_j_prev(i, j, L[0]+1, pads[0]+1, L[1]+1, pads[1]+1)
            
            #print('i,j,n,n_prev')
            #print((i,j,n,n_prev))
            
            #print('len sides_interp0 %i' % len(sides_interp[0]))
            #print('len sides_interp1 %i' % len(sides_interp[1]))
            
            v = sides_interp[0][n]
            v2 =sides_interp[1][n_prev]
            
            sides_interp[0][n] = .5*v + .5*v2
            sides_interp[1][n_prev] = .5*v + .5*v2
            
    #blendig corner 1        
    for i in range(0, pads[0]+1):
        for j in range(0, pads[1]+1):
            
            n = n_of_i_j_cur(L[1]+1, pads[1]+1, i, j)
            n_prev = n_of_i_j_prev(i, j, L[1]+1, pads[1]+1, L[0]+1, pads[0]+1)
            v = sides_interp[1][n]
            v2 =sides_interp[0][n_prev]
            
            sides_interp[1][n] = .5*v + .5*v2
            sides_interp[0][n_prev] = .5*v + .5*v2        
            
            
    if side == 'all':
        geom_dict['verts'] = sides_interp
        geom_dict['dimensions'] = [(x+1,y+1) for x,y in zip(L,pads)]
        #print(geom_dict['dimensions'])
        return geom_dict
    else:
        geom_dict['verts'] = [sides_interp[side]]  #+1
        geom_dict['dimensions'] = [(L[side]+1, pads[side]+1)] #+1?
        #print(geom_dict['dimensions'])
        return geom_dict
    
    
def blend_polygon_sides(V_edges, ps = [], side = 'all'):
    '''
    args:
        V_edges = list of [list of verts] along an edge loop which represents a side of the polygon
                  V_edges[0][-1] = V_edges[1][0]  eg...the corners are duplicated
                  
        ps = padding to slice off of each side

    returns dictionary with keys
      'verts'   list of corner patches of verts.  If a single corner
                is specified, a single element list containing a list of vertices
      'dimensions'  list of (x,y) pairs representing the dimensions of the vertex array.  
                    (L+1, p+1) (one more vert than faces in each direction)
    
    '''
    
    N = len(V_edges)        
    L = [len(v_edge)-1 for v_edge in V_edges]  #this is the actual # of edges, or the number of times the patch side is subdivided
    W = [calc_weights_vert_path(v_edge) for v_edge in V_edges]  #all going same direction around polygon

    
    #this determines how far across the patch an edge can be
    #extrapolated.  It is limited by the subdivision of the
    #adjacent sides
    max_pads = []
    for n in range(0,N):
        n_p1 = (n + 1)%N
        n_m1 = (n - 1)%N
        max_pads += [min(L[n_m1]-1,L[n_p1]-1)]

    #this is the desired padding by the user.  Eventually
    #this will be a required variable.  For now, if none
    #specified, just return the max padding
    if ps == []:
        pads = max_pads
    else:
        pads = ps
        
    geom_dict = {}
    
    #first round interpolation, use maximum padding across the patch  
    sides_interp = []
    for i in range(0,N):
        sides_interp += [blend_side_primary(V_edges, i, pad = max_pads[i]+1)]        
        
    old_verts = sides_interp
    new_verts = []
    
    #first round blending, use maxiumum padding across the patch
    for n in range(0,N):
        n_p1 = (n + 1)%N
        n_m1 = (n - 1)%N    
        '''
        SD = side_data = Tuple ([list verts], X, Y, W)
        verts = list of verts
        X = width of side verts = subvidivion of that side + 1
        Y = pading depth
        W = list of weights
        '''

        SD_nm1 =  old_verts[n_m1], L[n_m1]+1, max_pads[n_m1]+1, W[n_m1]
        SD_n   =     old_verts[n], L[n]+1,    max_pads[n]+1,    W[n]
        SD_np1 =  old_verts[n_p1], L[n_p1]+1, max_pads[n_p1]+1, W[n_p1]
        
        new_verts += [blend_adjacent_sides(SD_nm1, SD_n, SD_np1)]
    
    #slice off the appropriate amount of the desired padding
    sliced_verts = []
    for n in range(0,N):
        slice_v = []
        for i in range(0, L[n]+1):
            slice_v += new_verts[n][i*(max_pads[n]+1):i*(max_pads[n]+1)+pads[n]+1]
        #print(slice_v)
        sliced_verts += [slice_v]
        
    
    new_verts = []
    #blend the corners that still overlap
    for n in range(0,N):
        n_p1 = (n + 1)%N
        n_m1 = (n - 1)%N    
        '''
        SD = side_data = Tuple ([list verts], X, Y, W)
        verts = list of verts
        X = width of side verts = subvidivion of that side + 1
        Y = pading depth
        W = list of weights
        '''

        SD_nm1 =  sliced_verts[n_m1], L[n_m1]+1, pads[n_m1]+1, W[n_m1]
        SD_n   =  sliced_verts[n],       L[n]+1,    pads[n]+1,    W[n]
        SD_np1 =  sliced_verts[n_p1], L[n_p1]+1, pads[n_p1]+1, W[n_p1]
        
        new_verts += [blend_adjacent_sides(SD_nm1, SD_n, SD_np1)]
            
    if side == 'all':
        geom_dict['verts'] = new_verts
        geom_dict['dimensions'] = [(x+1,y+1) for x,y in zip(L,pads)]
        #print(geom_dict['dimensions'])
        return geom_dict
    else:
        geom_dict['verts'] = [new_verts[side]]  #+1
        geom_dict['dimensions'] = [(L[side]+1, pads[side]+1)] #+1?
        #print(geom_dict['dimensions'])
        return geom_dict
    
def blend_polygon(V_edges, depth, corner = 'all'):
    '''
    args:
        V_edges = list of [list of verts] along an edge loop which represents a side of the polygon
                  V_edges[0][-1] = V_edges[1][0]  eg...the corners are duplicated
    returns dictionary with keys
      'verts'   list of corner patches of verts.  If a single corner
                is specified, a single element list containing a list of vertices
      'dimensions'  list of (x,y) pairs representing the dimensions of the corner patches
    
    '''
    
    N = len(V_edges)        
    L = [len(v_edge)-1 for v_edge in V_edges]
    W = [calc_weights_vert_path(v_edge) for v_edge in V_edges]  #all going same direction around polygon
    #print(L)
    max_x, max_y = [], []
    geom_dict = {}
    for n in range(0,N):
        n_p1, n_p2 = (n + 1)%N, (n+1)%N
        n_m1, n_m2 = (n - 1)%N, (n-2)%N
        
        max_x += [min(L[n],L[n_m2])]
        max_y += [min(L[n_m1], L[n_p1])]
    
    #first round interpolation    
    corner_interp = []
    for i in range(0,N):
        corner_interp += [blend_corner_primary(V_edges, i, max_x[i],max_y[i])]        
        
    old_verts = corner_interp
    for k in range(0,depth):
        new_verts = []
        for n in range(0,N):
            n_p1, n_p2 = (n + 1)%N, (n+1)%N
            n_m1, n_m2 = (n - 1)%N, (n-2)%N    
            
            Cnm1 =  old_verts[n_m1], max_x[n_m1], max_y[n_m1], L[n_m1], W[n_m1]
            Cn   =     old_verts[n],    max_x[n],    max_y[n],    L[n],    W[n]
            Cnp1 =  old_verts[n_p1], max_x[n_p1], max_y[n_p1], L[n_p1], W[n_p1]
            
            new_verts += [blend_corner_secondary(Cnm1, Cn, Cnp1)]
            
        old_verts = new_verts
    if corner == 'all':
        geom_dict['verts'] = old_verts
        geom_dict['dimensions'] = [(x,y) for x,y in zip(max_x, max_y)]
        return geom_dict
    else:
        geom_dict['verts'] = [old_verts[corner]]
        geom_dict['dimensions'] = [(x,y) for x,y in zip(max_x, max_y)]
        return geom_dict
    
def blend_corner_secondary(Cnm1, Cn, Cnp1):
    '''
    corners = Tuple ([list verts], X, Y, L, W)
    verts = list of verts
    X = width of corner
    Y = height of corner
    L = subdivision along edge Vn to Vn+1
    W = list of weights 
    '''
    vs_nm1, Xnm1, Ynm1, Lnm1, Wnm1  = Cnm1[0], Cnm1[1], Cnm1[2], Cnm1[3], Cnm1[4]
    vs_n,     Xn,   Yn,   Ln,   Wn  =   Cn[0],   Cn[1],   Cn[2],   Cn[3],   Cn[4]
    vs_np1, Xnp1, Ynp1, Lnp1, Wnp1  = Cnp1[0], Cnp1[1], Cnp1[2], Cnp1[3], Cnp1[4]
    
    
    new_verts = vs_n[0:Yn]  #left boundary get's kept
    for xi_n in range(1, Xn):
        i = n_of_i_j(Xn, Yn, xi_n, 0) #bottom boundary get's passed through
        new_verts += [vs_n[i]]
        for yi_n in range(1, Yn):
            
            i = n_of_i_j(Xn, Yn, xi_n, yi_n)
            v = vs_n[i]
            
            xi_np1 = yi_n
            yi_np1 = Ln - xi_n
            i_np1 = n_of_i_j(Xnp1, Ynp1, xi_np1, yi_np1)
            
            xi_nm1 = Lnm1 - yi_n
            yi_nm1 = xi_n
            i_nm1 = n_of_i_j(Xnm1, Ynm1, xi_nm1, yi_nm1)
            
            v_nm1, v_np1  = Vector((0,0,0)),  Vector((0,0,0))
            w_nm1, w_np1 = 0, 0
            if i_np1 != -1:
                v_np1 = vs_np1[i_np1]
                w_np1 = 1 - Wn[xi_n]
            
            if i_nm1 != -1:
                v_nm1 = vs_nm1[i_nm1]
                w_nm1 = Wnm1[xi_nm1] 
                
            #print((w_np1, w_nm1))
            #evenly average the two blended verts from each side?
            if i_nm1 == -1 and i_np1 == -1:
                #print('invalid nm1 and nm2!!')
                new_verts += [v]
                
            elif i_np1 == -1 and i_nm1 != -1:
                #print('only blending n minus 1 side, no equivalent np1 side')
                #new_verts += [(1-w_nm1 )* v + w_nm1* v_nm1]
                new_verts += [.6667* v +.3333* v_nm1]
            
            elif i_np1 != -1 and i_nm1 == -1:
                #print('only blending n minus 1 side, no equivalent np1 side')
                #new_verts += [(1-w_np1 )* v + w_np1* v_np1]
                new_verts += [.6667 * v + .3333 * v_np1]
            else:
                #new_verts +=  [.5*(w_np1+w_nm1)*v  +.5*(1-w_np1)*v_np1 + .5*(1-w_nm1)*v_nm1]
                new_verts +=  [.5*v  +.25*v_np1 + .25*v_nm1]
            
    #print(new_verts[0:5])
    return new_verts
             
def blend_corner_primary(V_edges, n_corner, nx,ny):
    '''
    blends a corner based on 2 adjacent sides forward and backward
    args:
        V_edges = list of verts along an edge loop which represents a side of the polygon
                  V_edges[0][-1] = V_edges[1][0]  eg...the corners are duplicated
                  
        n_corner = interger index of corner to blend
        nx = how far to blend along V_edges[n] direction
        n = how far to blend along V_edges[n-1] direction
    '''
    
    N = len(V_edges)  #number of sides of polygon
    if N < 3: return
    
    #get index of n-2, n-1, n, n+1, n+2
    n_m2, n_m1, n, n_p1 = (n_corner - 2) % N,(n_corner - 1) % N, n_corner, (n_corner + 1) % N
    
    print('corner indices')
    print((n_m2, n_m1, n, n_p1))
    vs_nm2, vs_nm1, vs_n, vs_np1 =  V_edges[n_m2][::-1], V_edges[n_m1][::-1], V_edges[n], V_edges[n_p1]
                                               
    ws_nm2, ws_nm1, ws_n, ws_np1 = calc_weights_vert_path(vs_nm2), calc_weights_vert_path(vs_nm1), calc_weights_vert_path(vs_n), calc_weights_vert_path(vs_np1)

    #print('REALITY CHECK!!')
    #print('Vn[0] = Vnm1[0] now that its flipped')
    #print((vs_n[0], vs_nm1[0]))
    
    #print('Vnp1[0] = Vn[-1] going the same direction')
    #print((vs_np1[0], vs_n[-1]))
    
    ##print('weights')
    #print((ws_nm1, ws_n, ws_np1))
    #make sure we aren't going past where we can blend
    nx = min([nx, len(vs_nm2), len(vs_n)])
    ny = min([ny, len(vs_nm1), len(vs_np1)])
    blend_verts = []
    blend_verts += vs_nm1[0:ny]        
    for xi in range(1,nx):
        blend_verts += [vs_n[xi]]
        for yi in range(1,ny):
            v_n = vs_n[xi] - vs_n[xi-1]
            v_nm2 = vs_nm2[xi] - vs_nm2[xi-1]
            v_nm1 = vs_nm1[yi] - vs_nm1[yi-1]
            v_np1 = vs_np1[yi] - vs_np1[yi-1]
            
            coef_n   =  1-ws_nm1[yi]
            coef_nm2 =  ws_nm1[yi]
            coef_nm1 =  1 - ws_n[xi] #x location controls mixing of y vectors
            coef_np1 =  ws_n[xi]  #x location controls mixing of y vectors
            
            vx = coef_n*v_n +coef_nm2*v_nm2
            vy = coef_nm1*v_nm1 + coef_np1*v_np1
            prev_vert_index = (xi-1)*ny + yi-1
            print((xi, yi, prev_vert_index))
            v_prev = blend_verts[prev_vert_index]

            blend_verts += [v_prev + vx + vy]
      
    return blend_verts

def pad_patch(vs, ps, L, pattern, mode = 'edges'):
    '''
    takes a list of corner verts [v0,v1,v2,v3....]  and paddings = [p0,p1,p2,p3...]
    returns geom_dict
    
    args:
        vs - list of vectors representing corners OR edge loops of polygon
        ps - list of integers representing paddings
        L - list of subdivsions
        pattern - integer paddern identifier
        mode - determines wether vs is a list of corners or edge loops
               'corners' or 'edges'
           
    geom_dict['verts'] = list of vectors representing all verts
    geom_dict['faces'] = list of tupples represeting quad faces
    geom_dict['new subdiv'] = list of remaining subdivision after padding
    geom_dict['outer_verts'] = list of vert indices corresponding to outer verts. Starting at V0...v00,v01,v02..V1....V2.....VN..vN0, vn1..
    geom_dict['inner_verts'] = list of vert indices corresponding to center ring of verts
    geom_dict['inner_corners'] = list of vert indices corresponding to new V0, V1, V2, V3 after the patch has been padded/reduced
    
    '''
    def orig_v_index(n):    
        ind = sum([L[i] for i in range(0,n)])
        return ind
    
    def slice_corner(c_verts, x_dim, y_dim, x, y):
        cvs = []
        for i in range(1,x):
            for j in range(1, y):
                n = n_of_i_j(x_dim, y_dim, i, j)
                cvs += [c_verts[n]]
                
        return cvs
        
        
    #check that pdding is valid
    N = len(L)
    
    if (len(vs) != N) or (len(ps) != N):
        print('dimension mismatch in vs, ps, L')
        return
    
    for k, l in enumerate(L):
        k_min_1 = (k - 1) % N
        k_plu_1 = (k + 1) % N
        
        L_k = L[k]
        p_min_1 = ps[k_min_1]
        p_plu_1 = ps[k_plu_1]
        if L_k + 1 < p_min_1 + p_plu_1:
            print('Invalid because of p-1: %i p+1: %1 greater than Ln: %i' % (p_min_1, p_plu_1, L[k]))
            return [], []
    
    geom_dict = {}
    verts = []
    faces = []
    new_subdivs = []
    
    #make the perimeter
    if mode == 'corners':
        v_edges = []
        v_corners = vs
        for i,v in enumerate(vs):
            i_m1, i_p1 = (i - 1) % N, (i + 1) % N      
            p, l = ps[i], L[i]
            v_m1, p_m1, L_m1  = vs[i_m1], ps[i_m1], L[i_m1]
            v_p1, p_p1, L_p1  = vs[i_p1], ps[i_p1], L[i_p1]

            v_ed = subdivide_edge(v, v_p1, l)
            verts += v_ed[0:l]
            v_edges += [v_ed]
            new_subdivs += [l - p_m1 - p_p1]
    elif mode == 'edges':
        v_edges = vs
        v_corners = [v_ed[0] for v_ed in vs]
        
        for i,v in enumerate(vs):
            i_m1, i_p1 = (i - 1) % N, (i + 1) % N      
            p, l = ps[i], L[i]
            v_m1, p_m1, L_m1  = vs[i_m1], ps[i_m1], L[i_m1]
            v_p1, p_p1, L_p1  = vs[i_p1], ps[i_p1], L[i_p1]

            verts += vs[i][0:len(vs[i])-1]
            new_subdivs += [l - p_m1 - p_p1]
    
    
    ###
    #We blend each side, to maximum depth based on adjacent sides
    #collect the "blended" side geometry into a dictionary
    ###
    c_blend_geom = blend_polygon(v_edges, depth=1, corner = 'all')
    c_blend_verts = c_blend_geom['verts']
    c_blend_dims = c_blend_geom['dimensions']
        
    geom_dict['perimeter verts'] = [i for i in range(0,len(verts))]
    geom_dict['new subdivs'] = new_subdivs
    
    #make the inner corner verts and fill the quad patch created by them
    inner_corners = []
    inner_verts = []
    for i,v in enumerate(v_corners):
        i_m1, i_p1, i_m11, i_p11 = (i - 1) % N, (i + 1) % N,(i - 2) % N, (i + 2) % N  #the index of the elements forward and behind of the current
        p, l = ps[i], L[i]
        v_m1, p_m1, l_m1  = v_corners[i_m1], ps[i_m1], L[i_m1]
        v_p1, p_p1, l_p1  = v_corners[i_p1], ps[i_p1], L[i_p1]

        i_p_m1 = orig_v_index(i_m1) + L[i_m1] - p
        i_p_p1 = orig_v_index(i) + p_m1
        
        if p_m1 == 0 and p == 0: #this might be rare
            inner_corners += [orig_v_index(i)]
        
        elif p_m1 == 0 and p != 0:
            inner_corners += [orig_v_index(i_m1) + L[i_m1] - p] 
        
        elif p_m1 != 0 and p == 0:
            inner_corners += [orig_v_index(i) + p_m1]

        else:
            v_ed_m1 = verts[i_p_m1] 
            v_ed_p1 = verts[i_p_p1]    
            
            v_ed_m11 = verts[orig_v_index(i_m11)+L[i_m11]-p_m1]
            v_ed_p11 = verts[orig_v_index(i_p1)+p]
            
            v_inner_corner = .5*((1- p_m1/l)*v_ed_m1 + p_m1/l*v_ed_p11 + (1-p/l_m1)*v_ed_p1 + p/l_m1*v_ed_m11)
            
            corner_quad_verts2 = quadrangulate_verts(v, v_ed_p1, v_inner_corner, v_ed_m1, p-1, p_m1-1, x_off=1, y_off=1)['verts']
            x_dim, y_dim = c_blend_dims[i]
            corner_quad_verts = slice_corner(c_blend_verts[i], x_dim, y_dim, p_m1+1, p+1)
            #print('ready for new corner blending')
            #print('original method has %i verts: ' % len(corner_quad_verts))
            #print('new method has  %i verts: ' % len(corner_quad_verts2))
            
            N_now = len(verts)-1
            verts += corner_quad_verts
            
            inner_corners += [len(verts)-1]
            
            for n in range(0,p_m1-1):
                A = orig_v_index(i)+1+n
                B = A + 1
                D = N_now + 1 +p*n
                C = D + p
                faces += [(A,B,C,D)]
                
                for j in range(0,p-1):
                    A = N_now + 1 +(p)*n + j
                    B = A + p
                    C = B + 1
                    D = A + 1
                    faces += [(A,B,C,D)]
            if i == 0:
                strip_0 = [ind for ind in range(N_now-p+1,N_now+1)]
            else:
                strip_0 = [ind for ind in range(orig_v_index(i)-p, orig_v_index(i))]
            strip_0.reverse()
            strip_1 = [ind for ind in range(N_now+1,N_now+1+p)]
            strip_0.insert(0,orig_v_index(i))
            strip_1.insert(0,orig_v_index(i)+1)
            strip_faces = face_strip(strip_0, strip_1)
            faces += strip_faces
        
    for i,v in enumerate(v_corners):
        #INDEXING FOR THIS PASS
        i_m1, i_p1, i_m11, i_p11 = (i - 1) % N, (i + 1) % N,(i - 2) % N, (i + 2) % N  
        p, l = ps[i], L[i]
        v_m1, p_m1, l_m1  = v_corners[i_m1], ps[i_m1], L[i_m1]
        v_p1, p_p1, l_p1  = v_corners[i_p1], ps[i_p1], L[i_p1]
        i_p_m1 = orig_v_index(i_m1) + L[i_m1] - p
        i_p_p1 = orig_v_index(i) + p_m1
        p_m11 = ps[i_m11]
        
        #Fill in middle patches of padding along each side
        a = orig_v_index(i) + p_m1
        c = inner_corners[i_p1]
        d = inner_corners[i]
        if i == len(v_corners)-1:
            if p_p1 == 0:
                b = 0
            else:
                b = len(geom_dict['perimeter verts'])-p_p1
        else:
            b = orig_v_index(i_p1) - p_p1
            
        
        N_now = len(verts)
        middle_verts = quadrangulate_verts(verts[a], verts[b], verts[c], verts[d], p-1, l-p_m1 - p_p1-1, x_off=1, y_off=1)['verts']
        verts += middle_verts[0:len(middle_verts)-p]
        inner_verts += [inner_corners[i]]
        
        for n in range(0,l-p_m1-p_p1-2):
            if p == 0: continue
            A = orig_v_index(i)+1+p_m1+n
            B = A + 1   
            D = N_now +p*n
            C = D + p
            #print((A,B,C,D))
            faces += [(A,B,C,D)]
            for j in range(0,p-1):
                A = N_now +(p)*n + j
                B = A + p
                C = B + 1
                D = A + 1
                #print((A,B,C,D))
                faces += [(A,B,C,D)]
        
        #Zip the middle segment to the corner segments
        if p == 0:
            inner_verts += [inner_corners[i] + n for n in range(1,l-p_m1-p_p1)]
            #print(continued, did not make strips because this side has 0 padding')
            continue
        if l - p_m1 - p_p1 < 1:
            #print('could not zip because too much padding relative to subdivision')
            continue
        
        if l - p_m1 - p_p1 == 1 and p_m1 != 0 and p_p1 != 0:
            #print('Side %i' % i)
            #print('special zipping 1 strip up middle')            
            strip_0 = [inner_corners[i] - p +1 + n for n in range(0,p)]
            alpha = orig_v_index(i) + p_m1
            strip_0.insert(0,alpha)
            
            strip_1 = [inner_corners[i_p1] - p_p1*n for n in range(0,p)]
            strip_1.reverse()
            strip_1.insert(0,alpha+1)
            faces += face_strip(strip_0, strip_1)
            #print(strip_0)
            #print(strip_1)
            continue

        
        inner_verts += [N_now -1 + k for k in range(p,len(middle_verts),p)]
        
        if l - p_m1 == 1: print('Side %i: prev adjacent padding 1 less than this subdiv' % i)
        if l - p_p1 == 1: print('Side %i: next adjacent padding 1 less than this subdiv'% i)
        if l_m1 - p == 1 and p != 0: print('Side %i: padding on this side, no corner verts on previous side'% i)
        if l_m1 - p_m11 == 1 and p_m11 != 0 and p != 0: print('Side %i: no corner verts on previous side because m11 side padding'% i)
        
        
        
        if p_m1 != 0 and not ((l_m1 - p == 1 and p != 0) or 
                              (l_m1 - p_m11 == 1 and p_m11 != 0) or
                              (l - p_m1 == 1) or
                              (l - p_p1 == 1)):#normal padding previous adjacent side
        
            #print('Side %i' % i)
            #print('Side %i, normal padding on previous side' %i)
            strip_0 = [ind for ind in range(inner_corners[i]-p+1, inner_corners[i]+1)]
            strip_1 = [ind for ind in range(N_now,N_now+p)]
            strip_0.insert(0,orig_v_index(i)+p_m1)
            strip_1.insert(0,orig_v_index(i)+p_m1+1)
            strip_faces = face_strip(strip_0, strip_1)
            faces += strip_faces
            #print(strip_0)
            #print(strip_1)
                
        elif p_m1 == 0: #no padding on previous adjacent side
            #print('Side %i' % i)
            ##print('no padding on previous side')
            
            if p_p1 == l -1:
                alpha = inner_corners[i_p1]
                strip_1 = [alpha - n*p_p1 for n in range(0,p)]
                strip_1.reverse()
            else:
                alpha = len(verts)
                strip_1 = [ind for ind in range(N_now,N_now + p)]
            
            strip_1.insert(0, orig_v_index(i)+1)
            alpha = orig_v_index(i_m1) + l_m1 - p
            strip_0 = [alpha + n for n in range(0,p)]
            strip_0.reverse()
            strip_0.insert(0,orig_v_index(i))
            faces += face_strip(strip_0, strip_1)
            #print(strip_0)
            #print(strip_1)
            
        if p_p1 != 0 and p_p1 != (l - 1): #normal padding forward adjacent side
            #print('Side %i' % i)
            #print('Side %i: normal padding forward adjacent side, compare strips' %i)
            alpha = len(verts) - 1
            strip_0 = [alpha - n for n in range(0,p)]
            strip_0.reverse()
            strip_0.insert(0,orig_v_index(i) + l -p_p1-1)
            strip_1 = [inner_corners[i_p1] - n*p_p1 for n in range(0,p)]
            strip_1.reverse()
            strip_1.insert(0,orig_v_index(i) + l - p_p1)
            faces += face_strip(strip_0, strip_1)
            #print(strip_0)
            #print(strip_1)
        
        elif p_p1 == 0: #no padding on forward adjacent side
            #print('Side %i' % i)
            #print('no padding forward adjacent side, compare strips')
            
            if p_m1 == l -1: #we didn't add verts, so we need to hook to previous corner
                alpha = inner_corners[i]
            else: #we added middle vertices
                alpha = len(verts) - 1    
            strip_0 = [alpha - n for n in range(0,p)]
            strip_0.reverse()
            strip_0.insert(0,orig_v_index(i) + l -1)
            strip_1 = [orig_v_index(i_p1) + n for n in range(0,p+1)]
            faces += face_strip(strip_0, strip_1)
            #print(strip_0)
            #print(strip_1)

    #print(ARE THERE DOUBLES IN INNER CORNERS?')
    #pat, nl0, direction = identify_patch_pattern(new_subdivs, check_pattern = pattern)
    
    #if direction == -1:
    #    nl0_p1 = (nl0 + 1) % N
    #    inner_corners = inner_corners[nl0_p1:] + inner_corners[:nl0_p1]
    #    inner_corners.reverse()
       
    #else:
    #inner_corners = inner_corners[nl0:] + inner_corners[:nl0]

    geom_dict['inner corners'] = inner_corners
    geom_dict['original corners'] = [orig_v_index(n) for n in range(0,len(v_corners))]
    geom_dict['inner verts'] = inner_verts
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces  
    return geom_dict

    
def pad_patch_sides_method(vs, ps, L, pattern, mode = 'edges'):
    '''
    list of patch boundaries in ordered vert chains representing the boundaries
    args:
        vs - list of vectors representing corners OR edge loops of polygon
        ps - list of integers representing paddings
        L - list of subdivsions
        pattern - integer paddern identifier
        mode - determines wether vs is a list of corners or edge loops
               'corners' or 'edges'
           
    geom_dict['verts'] = list of vectors representing all verts
    geom_dict['faces'] = list of tupples represeting quad faces
    geom_dict['new subdiv'] = list of remaining subdivision after padding
    geom_dict['outer_verts'] = list of vert indices corresponding to outer verts. Starting at V0...v00,v01,v02..V1....V2.....VN..vN0, vn1..
    geom_dict['inner_verts'] = list of vert indices corresponding to center ring of verts
    geom_dict['inner_corners'] = list of vert indices corresponding to new V0, V1, V2, V3 after the patch has been padded/reduced
    
    '''
    def orig_v_index(n):    
        ind = sum([L[i] for i in range(0,n)])
        return ind
    def slice_corner(c_verts, x_dim, y_dim, x, y):
        '''
        because the perimeter verts are already included in the geom dict
        for dumb reasons.  So this leaves out the left and bottom boundary
        '''
        cvs = []
        for i in range(1,x):
            for j in range(1, y):
                n = n_of_i_j(x_dim, y_dim, i, j)
                cvs += [c_verts[n]]
        return cvs
    
    def slice_middle(side_verts, x_dim, y_dim, x_start, width,y):
        '''
        because the perimeter verts are already included in the geom dict
        for dumb reasons.  So this leaves out the left and bottom boundary
        '''
        mvs = [] #middle verts
        for i in range(x_start,x_start+width):
            for j in range(1, y):
                n = n_of_i_j(x_dim, y_dim, i, j)
                mvs += [side_verts[n]]
        return mvs 
    
    
    #validate padding. By definition, padding can not change the number of sides
    
    if mode == 'edges':
        new_L = [len(v)-1 for v in vs]
        #print('Subdiv provided by vert lists')
        #print(new_L)
        #print('Subdiv provided by input')
        #print(L)
        L = new_L 
    
    #check that pdding is valid
    N = len(L)
    
    if (len(vs) != N) or (len(ps) != N):
        print('dimension mismatch in vs, ps, L')
        return
    
    for k, l in enumerate(L):
        k_min_1 = (k - 1) % N
        k_plu_1 = (k + 1) % N
        
        L_k = L[k]
        p_min_1 = ps[k_min_1]
        p_plu_1 = ps[k_plu_1]
        if  p_min_1 + p_plu_1 > L_k - 1:
            print('Invalid because of p-1: %i p+1: %i greater than Ln - 1: %i' % (p_min_1, p_plu_1, L_k))
            return
    
    geom_dict = {}
    verts = []
    faces = []
    new_subdivs = []
    
    #make the perimeter
    if mode == 'corners':
        v_edges = []
        v_corners = vs
        for i,v in enumerate(vs):
            i_m1, i_p1 = (i - 1) % N, (i + 1) % N      
            p, l = ps[i], L[i]
            v_m1, p_m1, L_m1  = vs[i_m1], ps[i_m1], L[i_m1]
            v_p1, p_p1, L_p1  = vs[i_p1], ps[i_p1], L[i_p1]

            v_ed = subdivide_edge(v, v_p1, l)
            verts += v_ed[0:l]
            v_edges += [v_ed]
            new_subdivs += [l - p_m1 - p_p1]
    
    elif mode == 'edges':
        v_edges = vs
        v_corners = [v_ed[0] for v_ed in vs]
        
        for i,v in enumerate(vs):
            i_m1, i_p1 = (i - 1) % N, (i + 1) % N      
            p, l = ps[i], L[i]
            v_m1, p_m1, L_m1  = vs[i_m1], ps[i_m1], L[i_m1]
            v_p1, p_p1, L_p1  = vs[i_p1], ps[i_p1], L[i_p1]

            verts += vs[i][0:len(vs[i])-1]  #this removes the duplciated corner, goes around the whole permiter
            new_subdivs += [l - p_m1 - p_p1]  #This is the remaining subdivision after adjacent padding has been sliced off
    
    
    
    geom_dict['perimeter verts'] = [i for i in range(0,len(verts))]  #keep track of the external indices
    geom_dict['new subdivs'] = new_subdivs
    
    ###
    #We blend each side, to maximum depth based on adjacent sides
    #collect the "blended" side geometry into a dictionary
    c_blend_geom = blend_polygon_sides(v_edges, ps=ps, side = 'all')
    c_blend_verts = c_blend_geom['verts']
    c_blend_dims = c_blend_geom['dimensions']
        
    #make the inner corner verts and fill the quad patch created by them
    inner_corners = []
    inner_verts = []
    for i,v in enumerate(v_corners):
        #print('Corner %i' % i)
        i_m1, i_p1, i_m11, i_p11 = (i - 1) % N, (i + 1) % N,(i - 2) % N, (i + 2) % N  #the index of the elements forward and behind of the current
        p, l = ps[i], L[i]
        v_m1, p_m1, l_m1  = v_corners[i_m1], ps[i_m1], L[i_m1]
        v_p1, p_p1, l_p1  = v_corners[i_p1], ps[i_p1], L[i_p1]

        i_p_m1 = orig_v_index(i_m1) + L[i_m1] - p
        i_p_p1 = orig_v_index(i) + p_m1
        
        if p_m1 == 0 and p == 0: #
            #print('no padding on this side, no padding on prev side.  Corner remains unchanged')
            inner_corners += [orig_v_index(i)]
        
        elif p_m1 == 0 and p != 0:  #no padding previous side, padding on this side.
            #print('no padding previous side, some padding on this side, corner is moved along previous edge')
            inner_corners += [orig_v_index(i_m1) + L[i_m1] - p] 
        
        elif p_m1 != 0 and p == 0:
            #print('no padding this side, some padding prev side, corner is moved along this edge')
            inner_corners += [orig_v_index(i) + p_m1]

        else:
            #use the blended side, and pull out the corne
            #print('padding on both adjacents sides, inner corner becomes quadrangulated')
            x_dim, y_dim = c_blend_dims[i]
            corner_quad_verts = slice_corner(c_blend_verts[i], x_dim, y_dim, p_m1+1, p+1)
            #print('ready for new corner blending')
            #print('original method has %i verts: ' % len(corner_quad_verts))
            #print('new method has  %i verts: ' % len(corner_quad_verts2))
            
            N_now = len(verts)-1
            verts += corner_quad_verts
            
            inner_corners += [len(verts)-1]
            
            for n in range(0,p_m1-1):
                A = orig_v_index(i)+1+n
                B = A + 1
                D = N_now + 1 +p*n
                C = D + p
                faces += [(A,B,C,D)]
                
                for j in range(0,p-1):
                    A = N_now + 1 +(p)*n + j
                    B = A + p
                    C = B + 1
                    D = A + 1
                    faces += [(A,B,C,D)]
            if i == 0:
                strip_0 = [ind for ind in range(N_now-p+1,N_now+1)]
            else:
                strip_0 = [ind for ind in range(orig_v_index(i)-p, orig_v_index(i))]
            strip_0.reverse()
            strip_1 = [ind for ind in range(N_now+1,N_now+1+p)]
            strip_0.insert(0,orig_v_index(i))
            strip_1.insert(0,orig_v_index(i)+1)
            strip_faces = face_strip(strip_0, strip_1)
            faces += strip_faces
        
    for i,v in enumerate(v_corners):
        #INDEXING FOR THIS PASS
        i_m1, i_p1, i_m11, i_p11 = (i - 1) % N, (i + 1) % N,(i - 2) % N, (i + 2) % N  
        p, l = ps[i], L[i]
        v_m1, p_m1, l_m1  = v_corners[i_m1], ps[i_m1], L[i_m1]
        v_p1, p_p1, l_p1  = v_corners[i_p1], ps[i_p1], L[i_p1]
        i_p_m1 = orig_v_index(i_m1) + L[i_m1] - p
        i_p_p1 = orig_v_index(i) + p_m1
        p_m11 = ps[i_m11]
        
        #Fill in middle patches of padding along each side
        a = orig_v_index(i) + p_m1
        c = inner_corners[i_p1]
        d = inner_corners[i]
        if i == len(v_corners)-1:
            if p_p1 == 0:
                b = 0
            else:
                b = len(geom_dict['perimeter verts'])-p_p1
        else:
            b = orig_v_index(i_p1) - p_p1
            
        
        N_now = len(verts)
        middle_verts = quadrangulate_verts(verts[a], verts[b], verts[c], verts[d], p-1, l-p_m1 - p_p1-1, x_off=1, y_off=1)['verts']
        
        x_dim, y_dim = c_blend_dims[i]
        width = l - p_m1 - p_p1-1
        middle_verts2 = slice_middle(c_blend_verts[i], x_dim, y_dim, p_m1+1, width, y_dim) #p_m1+1?
        
        #if width != 0:
            #print('Side %i, Width of midlle is %i' % (i,width))
            #print('subdiv %i, padding %i, padding_m1 %i, padding_p1 %i' % (l, p, p_m1, p_p1))
        
        #verts += middle_verts[0:len(middle_verts)-p]
        verts += middle_verts2 #new method
        inner_verts += [inner_corners[i]]
        
        for n in range(0,l-p_m1-p_p1-2):
            if p == 0: continue
            A = orig_v_index(i)+1+p_m1+n
            B = A + 1   
            D = N_now +p*n
            C = D + p
            #print((A,B,C,D))
            faces += [(A,B,C,D)]
            for j in range(0,p-1):
                A = N_now +(p)*n + j
                B = A + p
                C = B + 1
                D = A + 1
                #print((A,B,C,D))
                faces += [(A,B,C,D)]
        
        #Zip the middle segment to the corner segments
        if p == 0:
            inner_verts += [inner_corners[i] + n for n in range(1,l-p_m1-p_p1)]
            #print(continued, did not make strips because this side has 0 padding')
            continue
        if l - p_m1 - p_p1 < 1:
            print('could not zip because too much padding relative to subdivision')
            continue
        
        if l - p_m1 - p_p1 == 1 and p_m1 != 0 and p_p1 != 0:
            #print('Side %i' % i)
            #print('special zipping 1 face strip up middle, basically a ladder between 2 corner patches')           
            strip_0 = [inner_corners[i] - p +1 + n for n in range(0,p)]
            alpha = orig_v_index(i) + p_m1
            strip_0.insert(0,alpha)
            
            strip_1 = [inner_corners[i_p1] - p_p1*n for n in range(0,p)]
            strip_1.reverse()
            strip_1.insert(0,alpha+1)
            faces += face_strip(strip_0, strip_1)
            #print(strip_0)
            #print(strip_1)
            continue

        
        inner_verts += [N_now -1 + k for k in range(p,len(middle_verts),p)]
        
        if l - p_m1 == 1: print('Side %i: prev adjacent padding 1 less than this subdiv' % i)
        if l - p_p1 == 1: print('Side %i: next adjacent padding 1 less than this subdiv'% i)
        if l_m1 - p == 1 and p != 0: print('Side %i: Previously disallowed case, may cause rare bad outcomes'% i)
        if l_m1 - p_m11 == 1 and p_m11 != 0 and p != 0: print('Side %i: no corner verts on previous side because m11 side padding'% i)
        
        
        if p_m1 != 0 and not (#(l_m1 - p == 1 and p != 0) or 
                              (l_m1 - p_m11 == 1 and p_m11 != 0) or
                              (l - p_m1 == 1) or
                              (l - p_p1 == 1)):#normal padding previous adjacent side
        
            #print('Side %i' % i)
            #print('Side %i, normal padding on previous side' % i)
            strip_0 = [ind for ind in range(inner_corners[i]-p+1, inner_corners[i]+1)]
            strip_1 = [ind for ind in range(N_now,N_now+p)]
            strip_0.insert(0,orig_v_index(i)+p_m1)
            strip_1.insert(0,orig_v_index(i)+p_m1+1)
            strip_faces = face_strip(strip_0, strip_1)
            faces += strip_faces
            #print(strip_0)
            #print(strip_1)
                
        elif p_m1 == 0: #no padding on previous adjacent side
            #print('Side %i' % i)
            #print('no padding on previous side')
            
            if p_p1 == l -1:
                alpha = inner_corners[i_p1]
                strip_1 = [alpha - n*p_p1 for n in range(0,p)]
                strip_1.reverse()
            else:
                alpha = len(verts)
                strip_1 = [ind for ind in range(N_now,N_now + p)]
            
            strip_1.insert(0, orig_v_index(i)+1)
            alpha = orig_v_index(i_m1) + l_m1 - p
            strip_0 = [alpha + n for n in range(0,p)]
            strip_0.reverse()
            strip_0.insert(0,orig_v_index(i))
            faces += face_strip(strip_0, strip_1)
            #print(strip_0)
            #print(strip_1)
        
        if p_p1 != 0 and p_p1 != (l - 1): #normal padding forward adjacent side
            #print('Side %i' % i)
            #print('Side %i: normal padding forward adjacent side, compare strips' % i)
            alpha = len(verts) - 1
            strip_0 = [alpha - n for n in range(0,p)]
            strip_0.reverse()
            strip_0.insert(0,orig_v_index(i) + l -p_p1-1)
            strip_1 = [inner_corners[i_p1] - n*p_p1 for n in range(0,p)]
            strip_1.reverse()
            strip_1.insert(0,orig_v_index(i) + l - p_p1)
            faces += face_strip(strip_0, strip_1)
            #print(strip_0)
            #print(strip_1)
        
        elif p_p1 == 0: #no padding on forward adjacent side
            #print('Side %i' % i)
            #print('no padding forward adjacent side, compare strips')
            
            if p_m1 == l -1: #we didn't add verts, so we need to hook to previous corner
                alpha = inner_corners[i]
            else: #we added middle vertices
                alpha = len(verts) - 1    
            strip_0 = [alpha - n for n in range(0,p)]
            strip_0.reverse()
            strip_0.insert(0,orig_v_index(i) + l -1)
            strip_1 = [orig_v_index(i_p1) + n for n in range(0,p+1)]
            faces += face_strip(strip_0, strip_1)
            #print(strip_0)
            #print(strip_1)

    #print(ARE THERE DOUBLES IN INNER CORNERS?')
    #pat, nl0, direction = identify_patch_pattern(new_subdivs, check_pattern = pattern)
    
    #if direction == -1:
    #    nl0_p1 = (nl0 + 1) % N
    #    inner_corners = inner_corners[nl0_p1:] + inner_corners[:nl0_p1]
    #    inner_corners.reverse()
       
    #else:
    #inner_corners = inner_corners[nl0:] + inner_corners[:nl0]

    geom_dict['inner corners'] = inner_corners
    geom_dict['original corners'] = [orig_v_index(n) for n in range(0,len(v_corners))]
    geom_dict['inner verts'] = inner_verts
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces  
    return geom_dict

def bi_prim_0(vs, ps, x, y):
    
    #we cheat with x and p1 to make face generation easier
    #since they are effectively interchangeable
    
    #validate that ps, x, y make sense with perimeter subdivisions
    Ls = [len(v)-1 for v in vs]
    print('Subdivs provided to the primitive')
    print(Ls)
    valid = True
    if Ls[0] != 3 + 2*x + y + 2*ps[1]:
        print('0 side subdiv doesnt match, will try anyway')
        print(Ls[0])
        print(3 + 2*x + y + 2*ps[1])
        valid = False    
    elif Ls[1] != 1 + y + 2*ps[0]:
        print('1 side deosnt match, but will try anyway')
        print(Ls[1])
        print(1 + y + 2*ps[0])
        valid = False
    
    sides_interp = blend_doublet(vs, ps=[ps[0], ps[1]+x+1], side='all') #change 2 back to 1
    
    verts = []
    faces = []
    #add 0 side
    verts += vs[0][0:len(vs[0])-1]
    #add the 1 side
    verts += vs[1][0:len(vs[1])-1]
    
    #store the perimeter indices
    perimeter_verts = [i for i in range(0,len(vs[0]) + len(vs[1]) - 2)]
    
    #special case, no real padding, just vertical slices through
    if ps[1] + x == 0 and ps[0] == 0:
        strip0 = [i for i in range(1,Ls[0])]
        strip1 = [0] + [i for i in range(Ls[0]+Ls[1]-1, Ls[0]-1, -1)]
        print('just zip these two boundaries')
        print(strip0)
        print(strip1)
        faces += face_strip(strip0, strip1)
        #Done
        geom_dict = {}
        geom_dict['verts'] = verts
        geom_dict['faces'] = faces
        return geom_dict
    
    
    if ps[0] != 0:
        #add in all the top side verts
        print('len of sides interp')
        print(len(sides_interp['verts'][1]))
        print('max n expected')
        print((ps[1]+x+1)*len(vs[1]))
        for j in range(1, ps[1] + x+2):
            for i in range(1, len(vs[1])-1):
                n = j * len(vs[1]) + i
                print(n)
                verts += [sides_interp['verts'][1][n]]  #<< even if ps[1] == 0, we will interpolate the top side as the bottom of the patch, it looks better, and easier to think about.
    
    else:
        #add in all the top side verts, one less strip, because the Side0 is the bottom of the actual minimal patch
        for j in range(1, ps[1] + x+ 1):
            print('jth row to interp %i' % j)
            for i in range(1, len(vs[1])-1):
                n = j * len(vs[1]) + i
                verts += [sides_interp['verts'][1][n]]
    #make faces
    #make the strip along the top
    strip0 = [i for i in range(Ls[0], Ls[0]+Ls[1])]
    strip0.append(0)
    print('strip along Side 1')
    print(strip0)
    
    if ps[0] != 0:
        for n in range(0, ps[1]+x+1):
            alpha = Ls[0] + Ls[1] + n*(Ls[1]-1)
            strip1 = [Ls[0]-(n+1)] + [i for i in range(alpha, alpha + Ls[1]-1)]
            strip1 += [n+1]
            faces += face_strip(strip0, strip1)
            print(strip1)
            strip0 = strip1
    else:
        for n in range(0, ps[1]+x):
            alpha = Ls[0] + Ls[1] + n*(Ls[1]-1)
            strip1 = [Ls[0]-(n+1)] + [i for i in range(alpha, alpha + Ls[1]-1)]
            strip1 += [n+1]
            faces += face_strip(strip0, strip1)
            print(strip1)
            strip0 = strip1    
    
    if ps[0] != 0:
        alpha = len(verts)  #just record where we are right now
        print('alpha')
        print(alpha)
        
        width = Ls[0] + 1 - 2*ps[1] - 2*x - 4
        print('width is %i' % width)

        for j in range(0, ps[0]-1):
            #print('ps[1] + x + 2, Ls[0] - ps[1]-2')
            #print((ps[1] + x + 2, Ls[0] - ps[1]-2))
            for k in range(0, width):
                
                i = ps[1] + x + 2 + k
                #print('add in a vert from side0, at index %i' % len(verts))
                n = (j+1) * len(vs[0]) + i
                verts += [sides_interp['verts'][0][n]]
                

        #this is the bottom strip on the perimeter
        print('strip along the bottom')
        strip0 = [i for i in range(ps[1]+x+1, Ls[0]-ps[1])]  #this may need extension with p0 ==1 
        #print(strip0)

        for n in range(0, ps[0]-1):
            tip = alpha - 1 - n
            tail = alpha -1 - (Ls[1] - 2) + n
            strip1 = [tip] + [i for i in range(alpha + n*width, alpha + (n+1)*width)] + [tail]
            #print(strip1)
            faces += face_strip(strip0, strip1)
            strip0 = strip1
        
        pole0 = alpha - ps[0]
        pole1 = pole0 - (width+1)
        print('poles')
        print((pole0, pole1))
        
        
        print('strip0 should be the bottom of the patch unless p1 and x are both 0')
        #print(strip0)
        strip1 = [i for i in range(pole0, pole1-1, -1)]
        print('strip 1 should be something totally different')
        #print(strip1)
    else:
        print('the poles are along the bottom existing boundary')
        pole0 = ps[1] + x + 1
        pole1 = pole0 + y + 1
        strip1 = [i for i in range(pole1, pole0-1,-1)]
        print('poles')
        print((pole0, pole1))
        #print(strip1)
    
    if valid:    
        faces += face_strip(strip0, strip1)
                        

    bme_rep = make_bme(verts, faces)
    relax_bmesh(bme_rep, perimeter_verts, iterations=4, spring_power=.2, quad_power=.2)
    
    verts = [v.co for v in bme_rep.verts]
    faces = [[v.index for v in f.verts] for f in bme_rep.faces]
    
    
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    geom_dict['bme'] = bme_rep
    geom_dict['perimeter verts'] = perimeter_verts
    #seal/sew together the individual regions
    return geom_dict

def bi_prim_1(vs, ps, x, y):
    
    #we cheat with x and p1 to make face generation easier
    #since they are effectively interchangeable
    
    #validate that ps, x, y make sense with perimeter subdivisions
    Ls = [len(v)-1 for v in vs]
    
    valid = True
    if Ls[0] != 2 + x + y + 2*ps[1]:
        print('0 side subdiv doesnt match, will try anyway')
        print('actual subdiv %i' % Ls[0])
        print('estimated subdiv %i' % (2 + x + y + 2*ps[1]))
         
        valid = False    
    elif Ls[1] != 2 + x + y + 2*ps[0]:
        print('1 side deosnt match, but will try anyway')
        print('0 side subdiv doesnt match, will try anyway')
        print('actual subdiv %i' % Ls[1])
        print('estimated subdiv %i' % (2 + x + y + 2*ps[0]))
        valid = False
    
    sides_interp = blend_doublet(vs, ps=[ps[0], ps[1]+x+1], side='all')
    
    verts = []
    faces = []
    #add 0 side
    verts += vs[0][0:len(vs[0])-1]
    #add the 1 side
    verts += vs[1][0:len(vs[1])-1]
    
    #store the perimeter indices
    perimeter_verts = [i for i in range(0,len(vs[0]) + len(vs[1]) - 2)]
    inner_verts = []
    if ps[0] == 0:
        corner0 = ps[1]
        pole0 = ps[1] + x + 1
        corner1 = Ls[0]-1-ps[1]
        print((corner0, corner1, pole0))
        inner_verts += [i for i in range(corner0,corner1+1)]
        print('inner verts')
        print(inner_verts)
        
    if ps[1] == 0:
        corner0 = Ls[0] + Ls[1] - 1 - ps[0]
        corner1 = Ls[0] + ps[0]
        pole1 = Ls[0] + ps[0] + x + 1
        print((corner0, corner1, pole1))
        inner_verts += [i for i in range(corner1, corner0+1)]
        print('inner verts')
        print(inner_verts)
    
    if ps[0] != 0:
        #add in all the top side verts
        for j in range(1, ps[1]+1):
            for i in range(1, len(vs[1])-1):
                n = j * len(vs[1]) + i
                verts += [sides_interp['verts'][1][n]]  #<< even if ps[1] == 0, we will interpolate the top side as the bottom of the patch, it looks better, and easier to think about.
    
                if i == ps[1] and j == ps[1]:
                    print('corner0, pole0, corner1')
                    corner0 = len(verts)-1
                    pole1 = corner0 + x + 1
                    corner1 = pole1 + y + 1
                    print((corner0, pole1, corner1))
                    inner_verts += [m for m in range(corner0, corner1+1)]
                    print('inner verts')
                    print(inner_verts)
                    
    #make the strip along the top
    strip0 = [i for i in range(Ls[0], Ls[0]+Ls[1])]
    strip0.append(0)
    print('strip along Side 1')
    #print(strip0)
    
    for n in range(0, ps[1]):
        alpha = Ls[0] + Ls[1] + n*(Ls[1]-1)
        strip1 = [Ls[0]-(n+1)] + [i for i in range(alpha, alpha + Ls[1]-1)]
        strip1 += [n+1]
        faces += face_strip(strip1, strip0)
        #print(strip1)
        strip0 = strip1

    alpha = len(verts)  #just record where we are right now
    print('alpha')
    print(alpha)
    
    #width = x + y + 1  #the strict way which necessitates x and y being correct
    width = Ls[0] - 2*ps[1]-1
    print('width is %i' % width)

    for j in range(0, ps[0]):
        
        for k in range(0, width):
            
            i = ps[1] + 1 + k
            #print('add in a vert from side0, at index %i' % len(verts))
            n = (j+1) * len(vs[0]) + i
            verts += [sides_interp['verts'][0][n]]
                
            if j == ps[0] -1:
                inner_verts += [len(verts) -1]
                if i == ps[1] + y + 1:
                    print('pole0')
                    print(len(verts)-1)
                    pole0 = len(verts) - 1
    
    #this is the bottom strip on the perimeter
    print('strip along the bottom')
    strip0 = [i for i in range(ps[1], Ls[0]+1-ps[1])]
    #print(strip0)

    for n in range(0, ps[0]):
        tip = alpha - 1 - n
        tail = alpha -1 - (Ls[1] - 2) + n
        strip1 = [tip] + [i for i in range(alpha + n*width, alpha + (n+1)*width)] + [tail]
        #print(strip1)
        faces += face_strip(strip1, strip0)
        strip0 = strip1
        
    
    print(inner_verts)
    bme_rep = make_bme(verts, faces)
    relax_bmesh(bme_rep, perimeter_verts, iterations=5, spring_power=.2, quad_power=.2)
    
    if not valid:
        verts = [v.co for v in bme_rep.verts]
        faces = [[v.index for v in f.verts] for f in bme_rep.faces]
        geom_dict = {}
        geom_dict['verts'] = verts
        geom_dict['faces'] = faces
        geom_dict['poles'] = [pole0, pole1]
        geom_dict['bme'] = bme_rep
        geom_dict['perimeter verts'] = perimeter_verts
        return geom_dict
                        
    #fill in the middle
    #verts += quadrangulate_verts(corner0, pole0, corner1, pole1, x, y)
    beta = len(verts)
    middle = quadrangulate_verts(verts[corner0], 
                                 verts[pole1],
                                 verts[corner1],
                                 verts[pole0],
                                 y, x)
    
    middle_map = {}
    for n,m in zip(inner_verts, middle['perimeter']):
        middle_map[m] = n
        
    middle_bme = make_bme(middle['verts'],middle['faces'])
    
    join_bmesh(middle_bme, bme_rep, middle_map)
    middle_bme.free()
    relax_bmesh(bme_rep, perimeter_verts, iterations=5, spring_power=.2, quad_power=.2)
    
    verts = [v.co for v in bme_rep.verts]
    faces = [[v.index for v in f.verts] for f in bme_rep.faces]
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    geom_dict['poles'] = [pole0, pole1]
    geom_dict['bme'] = bme_rep
    geom_dict['perimeter verts'] = perimeter_verts
    return geom_dict
    
def tri_prim_0(vs):
    '''
    args:
        vs - list of list of vectors representing corners of patch
    '''
    
    #reality check
    if not len(vs) == 3:
        print('dimensions mismatch!!')
        return {}
    
    #[v0, v1, v2] = [pad_bme.verts[i].co for i in geom_dict['inner corners']]
    #else:
    #    if mode != 'corners':
    #        print('must give corners only for this to work')
    #        return
    #    [v0, v1, v2] = vs
    

    [v0, v1, v2] = vs  
    pole0 = .5*v0 + .5*v1
    verts = [v0, pole0, v1, v2]
    faces = [(0,1,2,3)]
    
    geom_dict = {}
    geom_dict['faces'] = faces
    geom_dict['verts'] = verts
    geom_dict['poles'] = [1]
    
    return geom_dict
    
def tri_prim_1(vs, q1, q2, x):
    '''
    because LpProblem outputs variables in alphabetical
    order by name, q1, q2, x etc have to be in alphabetical
    order
    '''
    
    print('x:  %i' % x)
    print('q1:  %i' % q1)
    print('q2:  %i' % q2)
    
    if not len(vs) == 3:
        print('dimensions mismatch!!')
        return {}
    
    [v0, v1, v2] = vs
    #else:
    #    if mode != 'corners':
    #        print('must give corners only for this to work')
    #        return
    #    [v0, v1, v2] = vs
        
    p0 = .5*v0 + .5*v1 
    p1 = .5*v2 + .5*p0
    c00 = .5*v0 + .5*p0
    c01 = .5*p0 + .5*v1

    #verts = [v0, c00, pole0, c01, v1, v2, pole1]
    #faces= [(0,1,6,5),
    #        (1,2,3,6),
    #        (3,4,5,6)]
    
    V00geom = quadrangulate_verts(v0, c00, p1, v2, q1, x)
    V00 = V00geom['verts'] 
    V01 = quadrangulate_verts(v2, p1, c01, v1, q2, x, y_off =1)['verts']
    
    verts= []
    for i in range(0,x+2):
        verts += chain(V00[i*(q1+2):i*(q1+2)+q1+2], V01[i*(q2+1):i*(q2+1)+q2+1])
    
    #add in the bottom verts
    vs = quadrangulate_verts(p1, c00, p0, c01,q2,q1, x_off=1, y_off=1)['verts']
    verts += vs
    
    faces = []
    for i in range(0,x+1):
        for j in range(0, q2+q1+2):
            A =i*(q1+q2+3) + j
            B =(i+1)*(q1+q2+3) + j
            faces += [(A, B, B+1, A+1)]

    #make the bottom faces
    alpha = (x+1)*(q1+q2+3)
    n_p1 = alpha + q1 + 1 #index of the pole
    n_beta = n_p1 + q2+1
    N = (7 +3*q1 + 3*q2 + 3*x + q1*x + q2*x + q1*q2)

    for i in range(0,q1+1):
        for j in range(0, q2):
            A = n_p1 + j + 1 + i*(q2 + 1)
            B = A + 1
            C = A + (q2 +1)
            D = C + 1
            faces += [(C,D,B,A)]
        
        a = alpha + i
        b = N-(i+1)*(q2+1)
        c = b - q2-1
        d = a + 1           
        faces += [(a,b,c,d)]
    
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict

def quad_prim_0(vs):#, x, y):  #TODO TODO, make it fit with other solns format
    '''
    this is dumb...but it's how other primitives work
    '''
    
    
    #y = ps[1] + ps[3]
    #x = ps[0] + ps[2]
    [v0,v1,v2,v3] = vs
    #verts = quadrangulate_verts(v0, v1, v2, v3, x, y, x_off = 0, y_off = 0)
    #faces = []
    #for i in range(0, y+1):
    #    for j in range(0,x+1):
    #        A =i*(x+2) + j
    #        B =(i + 1) * (x+2) + j
    #        faces += [(A, B, B+1, A+1)]
    
    faces = [[0,1,2,3]]
    geom_dict = {}
    geom_dict['verts'] = [v0,v1,v2,v3]       
    geom_dict['faces'] = faces
    return geom_dict

def quad_prim_1(vs, x):
    if not len(vs) == 4:
        print('dimensions mismatch!!')
        return {}

    #geom_dict = pad_patch_sides_method(vs, ps, L, 1, mode = mode)
    #pad_bme = make_bme(geom_dict['verts'], geom_dict['faces'])
    #relax_bmesh(pad_bme, geom_dict['perimeter verts'], iterations = 4, spring_power = .1, quad_power=.2)
    #if not geom_dict:
    #    return {}
    #[v0, v1, v2, v3] = [geom_dict['verts'][i] for i in geom_dict['inner corners']]
    
    [v0, v1, v2, v3] = vs    
    N = 3*x + 7
    pole0 = 0.25 * (v0 + v1 + v2 + v3)
    c0 = .5*v0 + .5*v1
    c1 = .5*v1 + .5*v2
    
    
    verts = [v0, v3, v2]
    faces = []
    for i in range(0,x):
        A = (i+1)/(x+1)
        B =  (x-i)/(x+1)
        verts += [A*c0 + B*v0]
        verts += [A*pole0 + B*v3]
        verts += [A*c1 + B*v2]
    
    verts += [c0, pole0, c1, v1]
     
    for i in range(0,x+1):
        for j in range(0,2):
            f = (3*i+j, 3*i+j+3, 3*i+j+4, 3*i+j+1)
            faces += [f]
        
    faces += [(N-4, N-1, N-2, N-3)]
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict

def quad_prim_2(vs, x, y):
    if not len(vs)== 4:
        print('dimensions mismatch!!')
        return {}

    #geom_dict = pad_patch_sides_method(vs, ps, L, 2, mode = mode)
    #pad_bme = make_bme(geom_dict['verts'], geom_dict['faces'])
    #relax_bmesh(pad_bme, geom_dict['perimeter verts'], iterations = 4, spring_power = .1, quad_power=.2)
    #if not geom_dict:
    #    return {}
    #[v0, v1, v2, v3] = [geom_dict['verts'][i] for i in geom_dict['inner corners']]
     
    [v0, v1, v2, v3] = vs     
    c0 = .67 * v0 + .33 * v1
    pole0 = .67 * v1 + .33 * v0
    
    verts = []
    for i in range(0,y+2):
        A = (i)/(y+1)
        B =  (y-i+1)/(y+1) 
    
        verts += [B*v3 + A*v0]
        
        vlow  = B*v2 + A*c0
        vhigh = B*v1 + A*pole0
        
        for j in range(0,x+2):
            C = (j)/(x+1)
            D =  (x-j+1)/(x+1)
            
            verts+= [D*vlow + C*vhigh]
            
    faces = []
    N = 6 + 2*x + 3*y + x*y
    for i in range(0, y+1):
        for j in range(0,x+2):
            A =i*(x+3) + j
            B =(i + 1) * (x+3) + j
            faces += [(A, B, B+1, A+1)] 
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict

def quad_prim_3(vs, q1, x):
    '''
    alphabetical variables because LpProblem spits back
    out variables in alphabetical order
    '''
    
    print('varaibles alphabetized')
    print("q1 %i" % q1)
    print("x %i" % x)
    
    if not len(vs) == 4:
        print('dimensions mismatch!!')
        return {}

    [v0, v1, v2, v3] = vs
    
    c00 = .67 * v0 + .33 * v1
    c01 = .33 * v0 + .67 * v1
    
    pole0 = .67 * (.5*v0 + .5*v3) + .33 * (.5*v1 + .5*v2) 
    pole1 = .33 * (.5*v0 + .5*v3) + .67 * (.5*v1 + .5*v2)
    
    verts = []
    
    for i in range(0, x+2):
        A = (i)/(x+1)
        B =  (x-i+1)/(x+1)  
        verts += [A*c00 + B*v0]
        
        vlow  = A*pole0 + B*v3
        vhigh = A*pole1 + B*v2
        
        for j in range(0, q1 + 2):
           
            C = (j)/(q1+1)
            D =  (q1-j+1)/(q1+1)
            verts += [D*vlow + C*vhigh]

        verts += [A*c01 + B*v1]
    
            
    for m in range(0,q1):
        E = (m+1)/(q1+1)
        F =  (q1-m)/(q1+1)
        verts += [F*c01 + E*c00] 
        
        
    faces = []
    for i in range(0, x+1):
        for j in range(0,q1+3):
            A =i*(q1+4) + j
            B =(i+1)*(q1+4) + j  #x + 3 to q+4
            faces += [(A, B, B+1, A+1)]
    N = 8 + 4*x + 3*q1 + x*q1
    beta = (4+q1)*(x+1)  #This is the corner of the last face
    sigma = (4+q1)*(x+2)-1
    for c in range(0, q1):
        a = sigma + c
        b = sigma - 2 - c
        faces += [(a, b+1, b, a+1)]
            
    faces += [(beta+2, beta +1, beta, N-1)]        
     
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict

def quad_prim_4(vs, q1, x, y):
    
    if not len(vs) == 4:
        print('dimensions mismatch!!')
        return {}

    
    [v0, v1, v2, v3] = vs
    
    c00 = .75 * v0 + .25 * v1
    c01 = .5 * v0 + .5 * v1
    c02 = .25 * v0 + .75 * v1
    c10 = .5*v1 + .5*v2
    
    pole0 = .4 * c00 + .6*(.25*v2 + .75*v3)
    pole1 = .6 * c02 + .4*(.75*v2 + .25*v3)
    cp01 = .5*pole0 + .5*pole1
    
    '''
    verts = [v0, c00, c01, c02, v1, c10, v2, v3, pole0, cp01, pole1]
    faces  = [(0,1,8,7),
              (1,2,9,8),
              (2,3,10,9),
              (3,4,5,10),
              (5,6,9,10),
              (8,9,6,7)]
    '''
    verts = []
    for i in range(0, x+2):
        A = (i)/(x+1)  #small to big  -> right side on my paper
        B =  (x-i+1)/(x+1)  #big to small  -> left side on my paper
        verts += [A*c00 + B*v0]
        
        vlow  = A*pole0 + B*v3
        vhigh = A*cp01 + B*v2
        
        for j in range(0, q1 + 2):
           
            C = (j)/(q1+1)  #small to big - top vert component
            D =  (q1-j+1)/(q1+1)  #big to small - bottom vert component
            verts += [D*vlow + C*vhigh]
            
        vlow = vhigh
        vhigh = A*pole1 + B*c10
        
        for j in range(1, y + 2): #<---starts at 1 the, the top edge of last segment is the bottom edge here
            C = (j)/(y+1)  #small to big - top vert component
            D =  (y-j+1)/(y+1)  #big to small - bottom vert component
            verts += [D*vlow + C*vhigh]
    
        verts += [(B*v1 + A*c02)]
        
    #now add in blue region    
    for j in range(1, y + 2): #<---starts at 1 the, the top prev vert already added, however the middle vert has not
        C = (j)/(y+1)  #small to big - top vert component
        D =  (y-j+1)/(y+1)  #big to small - bottom vert component
        verts += [D*c02 + C*c01]

    for j in range(1, q1 + 1):  #don't need to add in bordres so these start at 1 and end at N-1
        C = (j)/(q1+1)  #small to big - top vert component
        D =  (q1-j+1)/(q1+1)  #big to small - bottom vert component
        verts += [D*c01 + C*c00]

        
        
    faces = []
    for i in range(0, x+1):
        for j in range(0,q1+y+5 -1):
            A =i*(q1+ y + 5) + j
            B =(i+1)*(q1+y+5) + j
            faces += [(A, B, B+1, A+1)]
    
    N = 11 + 5*x + 3*q1 + 3*y + q1*x + x*y
    beta = (5+q1+y)*(x+1)  #This is the corner of the last face to be added
    sigma = (5+q1+y)*(x+2)-1  #this is the corner of the first face in the leftover segment
    for c in range(0, y+q1+1):
        a = sigma + c
        b = sigma - 2 - c
        faces += [(a, b+1, b, a+1)]
            
    faces += [(beta+2, beta +1, beta, N-1)]
      
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict

def pent_prim_0(vs):  #Done, any cuts can be represented as padding, however may want to make this fall in line with other fns
    if not len(vs) == 5:
        print('dimensions mismatch!!')
        return {}

    [v0, v1, v2, v3,v4] = vs
        
    c0 = .5*v0 + .5*v1
    verts = [v0,c0,v1,v2,v3,v4]
    faces = [(0,1,4,5),(1,2,3,4)]
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict
    
def pent_prim_1(vs, q4, x):
    
    if not len(vs) == 5:
        print('dimensions mismatch!!')
        return {}
    

    [v0, v1, v2, v3,v4] = vs
    pole0 = .5*v0 + .5*v1
    
    #verts = [v0,pole0,v1,v2,v3,v4]
    #faces = [(0,1,2,3),(0,3,4,5)]
    
    verts = []
    for i in range(0,q4+2):
        A = (i)/(q4+1)
        B =  (q4-i+1)/(q4+1) 
    
        verts += [B*v3 + A*v4]
        
        vlow  = B*v2 + A*v0
        vhigh = B*v1 + A*pole0
        
        for j in range(0,x+2):
            C = (j)/(x+1)
            D =  (x-j+1)/(x+1)
            
            verts+= [D*vlow + C*vhigh]
            
    faces = []
    N = 6 + 2*x + 3*q4 + x*q4
    for i in range(0, q4+1):
        for j in range(0,x+2):
            A =i*(x+3) + j
            B =(i + 1) * (x+3) + j
            faces += [(A, B, B+1, A+1)]
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict
       
def pent_prim_2(vs, q0, q1, q4, x):
    
    if not len(vs) == 5:
        print('dimensions mismatch!!')
        return {}

    [v0, v1, v2, v3, v4] = vs
    
    c00 = .75*v0 + .25*v1
    p0 = .5*v0 + .5*v1
    c01 = .25*v0 + .75*v1
    p1 = .75*p0 + .25*v3
    cp0 = .5*p1 + .5*v3
    
    V00 = quadrangulate_verts(v4, v0, cp0, v3, q4, q0)['verts']
    V01 = quadrangulate_verts(v3, cp0, v1, v2, q1, q0, y_off = 1)['verts']
    V10 = quadrangulate_verts(v0, c00, p1, cp0, q4, x, x_off = 1)['verts']
    V11 = quadrangulate_verts(cp0, p1, c01, v1, q1, x, x_off =1, y_off =1)['verts']
    
    verts= []
    #slice these lists together so the verts are coherent for making faces
    for i in range(0,q0+2):
        verts += chain(V00[i*(q4+2):i*(q4+2)+q4+2],V01[i*(q1+1):i*(q1+1)+q1+1])
        
    for i in range(0,x+1):
        verts += chain(V10[i*(q4+2):i*(q4+2)+q4+2], V11[i*(q1+1):i*(q1+1)+q1+1])
    
    
    #add in the bottom verts
    vs = quadrangulate_verts(p1, c00, p0, c01,q1,q4, x_off=1, y_off=1)['verts']
    verts += vs
    
    faces = []
    for i in range(0,x+q0+2):
        for j in range(0, q1+q4+2):
            A =i*(q1+q4+3) + j
            B =(i+1)*(q1+q4+3) + j
            faces += [(A, B, B+1, A+1)]
    
    #make the bottom faces
    alpha = (q0+x+2)*(q1+q4+3)
    n_p1 = alpha + q4 + 1 #index of the pole
    n_beta = n_p1 + q1+1
    N = (10 + 
         3*x   + 3*q0  + 4*q1  + 4*q4  + 
         q0*q1 + q1*x  + q1*q4 + q4*q0 + x*q4)
    #print('Total verts %i' % N)
    #print(alpha)
    for i in range(0,q4+1):
        for j in range(0,q1):
            A = n_p1 + j + 1 + i*(q1 + 1)
            B = A + 1
            C = A + (q1 +1)
            D = C + 1
            faces += [(C, D, B, A)]
    
        a = alpha + i
        b = N-(i+1)*(q1+1)
        c = b - q1-1
        d = a + 1
        faces += [(a,b,c,d)]
              
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict

def pent_prim_3(vs, q1, q4, x, y):
    
    if not len(vs)  == 5:
        print('dimensions mismatch!!')
        return {}

    [v0, v1, v2, v3,v4] = vs
    
    c00 = .8*v0 + .2*v1
    c01 = .6*v0 + .4*v1
    c02 = .4*v0 + .6*v1
    c03 = .2*v0 + .8*v1
    
    c10 = .5*v1 + .5*v2
    
    p0 = .6*c00 + .4*(.5*v3 + .5*v4)
    cp0 = .35 * c01 + .65*v3
    cp1 = .65 * (.33*v2 + .67*v3) + .35*c02
    p1 = .7 * c03 + .3*(.67*v2 + .33*v3)
    
    
    V00 = quadrangulate_verts(v0, c00, p0, v4, 0,  x,y_off = 0)['verts']
    V01 = quadrangulate_verts(v4, p0, cp0, v3, q4, x,y_off = 1)['verts']
    V02 = quadrangulate_verts(v3, cp0,cp1, v2, q1, x,y_off = 1)['verts']
    V03 = quadrangulate_verts(v2, cp1, p1, c10, y,  x, y_off = 1)['verts']
    V04 = quadrangulate_verts(c10, p1, c03, v1, 0,  x, y_off = 1)['verts']
    
    verts = []
    for i in range(0,x+2):
        verts += chain(V00[i*2:i*2 + 2],
                       V01[i*(q4+1):i*(q4+1)+q4+1],
                       V02[i*(q1+1):i*(q1+1)+q1+1],
                       V03[i*(y+1):i*(y+1)+y+1],
                       V04[i:i+1])

    V10 = quadrangulate_verts(p1, cp1, c02, c03, 0, y, x_off=1, y_off=1)['verts']
    V11 = quadrangulate_verts(cp1, cp0, c01, c02, 0, q1, x_off=1, y_off=1)['verts']
    V12 = quadrangulate_verts(cp0, p0, c00, c01, 0, q4, x_off=1, y_off=1)['verts']
    V12.pop()  #duplicate of the corner where it meets.
    
    verts += V10 + V11 + V12
    faces = []
    for i in range(0,x+1):
        for j in range(0, 5+q4+q1+y):
            A =i*(6+q4+q1+y) + j
            B =(i+1)*(6+q4+q1+y) + j
            faces += [(A, B, B+1, A+1)]
    
    alpha = (x+2)*(6+q4+q1+y)-1
    sigma = (x+1)*(6+q4+q1+y)
    #print((alpha, sigma))
    
    N = 14 + 6*x + 3*q4 + 3*q1 + 3*y + x*(q4 + q1+y)
    #print(N)
    for i in range(0,2+q4+q1+y):
        a = alpha - i- 2
        b = alpha +1 + i
        c = b-1
        d = a + 1
        faces += [(a,b,c,d)]
    
    faces += [(sigma + 2, sigma + 1, sigma, N-1)]  
    #verts = [v0,c00,c01,c02,c03,v1,c10,v2,v3,v4, pole0, cp0, cp1, pole1]
    #faces = [(0,1,10,9), (1,2,11,10),(2,3,12,11),(3,4,13,12),
    #         (4,5,6,13),(6,7,12,13),(7,8,11,12),(8,9,10,11)]
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict
    
def hex_prim_0(vs, x):
    if not len(vs) == 6:
        print('dimensions mismatch!!')
        return {}

    [v0, v1, v2, v3,v4,v5] = vs
    #verts = [v0,v1,v2,v3,v4,v5]
    #faces = [(0,1,2,5), (2,3,4,5)]
    verts = []
    faces = []
    
    V00 = quadrangulate_verts(v0, v1, v2, v5, 0, x, x_off = 0, y_off = 0)['verts']
    V01 = quadrangulate_verts(v5, v2, v3, v4, 0, x, x_off = 0, y_off = 1)['verts']
    
    #verts = V00 + V01
    for i in range(0,x+2): #TODO, better to slice other direction fewer iterations of loop
        verts += chain(V00[2*i:2*i+2],V01[i:i+1])
    
    #print(len(verts))    
    for i in range(0, x+1):
        for j in range(0,2):
            A =i*(3) + j
            B =(i + 1) * 3 + j
            #print((A,B,B+1,A+1))
            faces += [(A, B, B+1, A+1)]
                
    geom_dict= {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict

def hex_prim_1(vs, w, x, y, z):
   
    if not len(vs) == 6:
        print('dimensions mismatch!!')
        return {}

    [v0, v1, v2, v3,v4,v5] = vs
    
    c0 = .5*v0  +.5*v1
    c1 = .5*v1 + .5*v2
    cp0 = .18*(v3 + v4 + v5) + .1533*(v0 + v1 + v2)
    p0 = .33*c0 + .33 * c1 + .34 * cp0
    #verts = [v0, c0, v1, c1, v2, v3, v4, v5, cp0, pole1]
    #faces = [(0,1,9,8),
    #         (1,2,3,9),
    #         (3,4,8,9),
    #         (4,5,6,8),
    #         (6,7,0,8)]
    
    V00 = quadrangulate_verts(v5, v0, cp0, v4, z, w)['verts']
    V01 = quadrangulate_verts(v4, cp0, v2, v3, y, w, y_off = 1)['verts']
    V10 = quadrangulate_verts(v0, c0, p0, cp0, z, x, x_off = 1)['verts']
    V11 = quadrangulate_verts(cp0, p0, c1, v2, y, x, x_off =1, y_off =1)['verts']
    
    verts= []
    #slice these lists together so the verts are coherent for making faces
    for i in range(0,w+2):
        verts += chain(V00[i*(z+2):i*(z+2)+z+2],V01[i*(y+1):i*(y+1)+y+1])
        
    for i in range(0,x+1):
        verts += chain(V10[i*(z+2):i*(z+2)+z+2], V11[i*(y+1):i*(y+1)+y+1])
    
    
    #add in the bottom verts 
    vs = quadrangulate_verts(p0, c0, v1, c1,y,z, x_off=1, y_off=1)['verts']
    verts += vs
    
    faces = []
    for i in range(0,x+w+2):
        for j in range(0, y+z+2):
            A =i*(y+z+3) + j
            B =(i+1)*(y+z+3) + j
            faces += [(A, B, B+1, A+1)]
    
    #make the bottom faces
    alpha = (w+x+2)*(y+z+3)
    n_p1 = alpha + z + 1 #index of the pole
    n_beta = n_p1 + y+1
    N = (10 + 
         3*x   + 3*w  + 4*y  + 4*z  + 
         w*y + y*x  + y*z + z*w + x*z)
    #print('Total verts %i' % N)
    #print(alpha)
    for i in range(0,z+1):
        for j in range(0,y):
            A = n_p1 + j + 1 + i*(y + 1)
            B = A + 1
            C = A + (y +1)
            D = C + 1
            faces += [(C, D, B, A)]
    
        a = alpha + i
        b = N-(i+1)*(y+1)
        c = b - y-1
        d = a + 1
        faces += [(a,b,c,d)]
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict

def hex_prim_2(vs, q0, q3, x, y):
    
    if not len(vs) == 6:
        print('dimensions mismatch!!')
        return {}

    [v0, v1, v2, v3,v4,v5] = vs
    
    c00 = .67*v0 + .33 * v1
    c01 = .33*v0 + .67*v1
    
    cp0 = .8 * (.65 * v5 + .35*v2) + .2 * (.8*v4 + .2*v3)
    cp1 = .8 * (.35 * v5 + .65*v2) + .2 * (.2*v4 + .8*v3)
    
    p0 = .5 * (.5*c00 + .5*c01) + .5*cp0
    p1 = .5 * (.5*c00 + .5*c01) + .5*cp1
    
    #verts = [v0, c00, c01, v1, v2, v3, v4, v5, cp0, cp1, p0, p1]
    #faces = [(0,1,10,8),
    #         (1,2,11,10),
    #         (2,3,9,11),
    #         (3,4,5,9),
    #         (5,6,8,9),
    #         (6,7,0,8),
    #         (8,10,11,9)]
    
    
    verts = []
    V00 = quadrangulate_verts(v5, v0, cp0, v4, q3, q0, x_off = 0, y_off = 0)['verts']
    V01 = quadrangulate_verts(v4, cp0, cp1, v3, y, q0, x_off = 0, y_off = 1)['verts']
    V02 = quadrangulate_verts(v3, cp1, v1, v2, q3, q0, x_off = 0, y_off = 1)['verts']
    V10 = quadrangulate_verts(v0, c00, p0, cp0, q3, x, x_off = 1, y_off = 0)['verts']
    V11 = quadrangulate_verts(cp0, p0, p1, cp1, y, x, x_off = 1, y_off = 1)['verts']
    V12 = quadrangulate_verts(cp1, p1, c01, v1, q3, x, x_off = 1, y_off = 1)['verts']
    
    for i in range(0,q0+2):
        verts += chain(V00[i*(q3+2):i*(q3+2)+q3+2],V01[i*(y+1):i*(y+1)+y+1], V02[i*(q3+1):i*(q3+1)+q3+1])
        
    for i in range(0,x+1):
        verts += chain(V10[i*(q3+2):i*(q3+2)+q3+2],V11[i*(y+1):i*(y+1)+y+1], V12[i*(q3+1):i*(q3+1)+q3+1])
    
    #fill in q3/y patch
    V20 = quadrangulate_verts(p1, p0, c00, c01, q3, y, x_off = 1, y_off = 1)['verts']

    verts += V20[0:len(V20) - (q3 +1)]
    faces = []
    for i in range(0,x+q0+2):
        for j in range(0, 2*q3+y+3):
            A =i*(2*q3+y+4) + j
            B =(i+1)*(2*q3+y+4) + j
            faces += [(A, B, B+1, A+1)]
    
    n_p1 = (q0 + x + 3) * (2*q3 + y + 4) - (q3 + 1)        
    for i in range(0, y):
        for j in range(0, q3):
            A = n_p1  + i*(q3+1) + j
            B = n_p1  + (i+1)*(q3+1) + j
            faces += [(A, B, B+1, A+1)]
    
    #strip  c00 to p0
    n_c00 = (q0 + x + 2) * (2*q3 + y + 4)
    N = (q0 + x + 3) * (2*q3 + y + 4) + (q3 + 1)*(y)
    for i in range(0, q3):
        a = n_c00 + i
        b = N - i-1
        c = N - 1 - (i+1)
        d = a + 1
        faces += [(a,b,c,d)]
    
    #strip p1 to p0    
    for i in range(0, y):
        a = n_p1 -1 - i
        b = n_p1 + i*(q3+1)
        c = n_p1 + (i+1)*(q3+1)
        d = a -1
        faces += [(a,d,c,b)]
            
    #final quad at p0
    n_p0 = n_c00 + q3 + 1
    a = n_p0
    b = n_p0-1
    c = N - 1 - q3
    d = n_p0 + 1

    faces += [(a,b,c,d)]
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict
        
def hex_prim_3(vs,q3,x,y,z):    
    
    if not len(vs) == 6:
        print('dimensions mismatch!!')
        return {}

    [v0, v1, v2, v3,v4,v5] = vs
    
    c00 = .75 * v0 + .25 * v1
    c01 = .5 * v0 + .5 * v1
    c02 = .25 * v0 + .75 * v1
    
    c10 = .5*v1 + .5*v2
    
    
    cp0 = .4*v2 + .6*v5
    p2 = .6*v2 + .4*v5
    
    p0 = .5*(.75*v4 + .25*v3) + .5*cp0
    p1 = .5*(.25*v4 + .75*v3) + .5*p2
    p3 = .334*p0 + .333*c02 + .333*c10
    
    #verts = [v0, c00, c01, c02, v1, c10, v2, v3, v4, v5, p1, p2, cp0, p0, p3]
    #faces = [(0,1,12,9),
    #         (1,2,13,12),
    #         (2,3,14,13),
    #         (3,4,5,14),
    #         (5,6,13,14),
    #         (6,7,11,13),
    #         (7,8,10,11),
    #         (8,9,12,10),
    #         (10,12,13,11)]
    
    verts = []
    faces = []
    
    V00 = quadrangulate_verts(v0, c00, cp0, v5, 0, x, x_off=0, y_off=0)['verts']
    V01 = quadrangulate_verts(v5, cp0, p0,  v4, q3, x, x_off=0, y_off=1)['verts']
    V02 = quadrangulate_verts(v4, p0,  p1,  v3, z, x, x_off=0, y_off=1)['verts']
    V03 = quadrangulate_verts(v3, p1,  p2,  v2, q3, x, x_off=0, y_off=1)['verts']
    V04 = quadrangulate_verts(v2, p2,  p3, c10, y, x, x_off=0, y_off=1)['verts']
    V05 = quadrangulate_verts(c10, p3,  c02, v1, 0, x, x_off=0, y_off=1)['verts']
    
    V10 = quadrangulate_verts(p1, p0,  cp0, p2, q3, z, x_off=1, y_off=1)['verts']
    V11 = quadrangulate_verts(p2, cp0,  c00, c01, 0, z, x_off=1, y_off=1)['verts']
    
    V21 = quadrangulate_verts(p3, p2, c01, c02, 0, y, x_off =1, y_off =1 )['verts']
    
    #verts = V00 + V01 + V02 + V03 + V04 + V05 + V10 + V11 + V21
    
    for i in range(0,x+2):
        verts += chain(V00[i*(2):i*(2)+2],
                       V01[i*(q3+1):i*(q3+1)+q3+1],
                       V02[i*(z+1):i*(z+1)+z+1],
                       V03[i*(q3+1):i*(q3+1)+q3+1],
                       V04[i*(y+1):i*(y+1)+y+1],
                       V05[i:i+1])
    
    for i in range(0,z): #trims off extra verst and stacks them
        verts += chain(V10[i*(q3+1):(i+1)*(q3+1)],
                       V11[i:i+1])
    verts += V21
           
    for i in range(0,x+1):
        for j in range(0, 6 + 2*q3+z+y):
            A =i*(7 + 2*q3+z+y) + j
            B =(i+1)*(7 + 2*q3+z+y) + j
            faces += [(A, B, B+1, A+1)]
            #print((A, B, B+1, A+1))
    
    
    N = x*(7+2*q3+z+y) + q3*(4+z) + z*4 + y*3 + 15
    alpha = (7+2*q3+z+y)*(x+1)
    beta = (7+2*q3+z+y)*(x+2) + q3 + 1
    n_p0 = alpha + q3 + 2
    n_p1 = n_p0 + z + 1
    n_p2 = n_p1 + q3 + 1
    n_p3 = n_p1 + q3 + y + 2
    #print('Alpha, Beta, np0, np1, np2, np3')
    #print((alpha,beta, n_p0,n_p1,n_p2,n_p3))
    
    #print('right Z Strip')
    if z > 0:
        for i in range(0, q3+1):
            if i == 0:
                A=N-1
                B=n_p2
                C=beta - 1
                D=beta
            else:
                A = n_p2 - i + 1
                B = A - 1
                C = beta - i - 1
                D = beta - i 
            #print((A,B,C,D))
            faces += [(A,B,C,D)]
        #the face on pole 1
        #print('The face on pole 1')
        #print((n_p1 + 1, n_p1, n_p1-1, n_p3+2))
        faces += [(n_p1 + 1, n_p1, n_p1-1, n_p3+2)]
           
        #print('Left Z Strip')
        for i in range(0, q3+1):
            A = alpha + i
            B = N-2-y-i
            C = B-1
            D = A + 1
            #print((A,B,C,D))
            faces += [(A,B,C,D)]
    
        #the face on pole 0
        #print('The face on pole 0')
        #print((n_p0 -1, N-y-3-q3, n_p0+1, n_p0))
        faces += [(n_p0 -1, N-y-3-q3, n_p0+1, n_p0)]
    
        #Z strip
        #print('Middle Z Strip')
        if z >= 2:  #because z strip is bounded on both sides by weirdness
            for i in range(0, z-1):
                #down the q3 cuts
                for j in range(0,q3+1):
                    A = n_p3 + 2 + i*(q3 + 2) + j
                    D = n_p3 + 2 + (i+1)*(q3+2) + j
                    B = A + 1
                    C = D + 1
                    #print((A,D,C,B))
                    faces += [(A,D,C,B)]
    
    
                #top cap
                a = n_p3 + 2 + i*(q3 + 2)
                b = n_p1 - i - 1
                c = n_p1 - i - 2
                d = n_p3 + 2 + (i+1)*(q3 + 2)
                #print((a,b,c,d))
                faces += [(a,b,c,d)]
    else: #Z = 0
        for i in range(0,q3+1):
            A = alpha + i
            D = alpha + 1 + i
            
            if i == 0:
                B = N - 1
                C = n_p2
            else:
                B = n_p2 + 1 - i
                C = n_p2 - i
            
            faces += [(A,B,C,D)]
            
        faces += [(n_p0, n_p0-1, n_p1 + 1, n_p1)]
          
    #print('y patch')
    for i in range(0,y):
        A = n_p2 + i
        B = N - 1 - i
        C = B - 1
        D = A + 1
        faces += [(A,B,C,D)]
    
    d = n_p3
    c = n_p3 + 1
    b = N -1 - y
    a = n_p3 - 1
    faces += [(a,b,c,d)]
    
    geom_dict = {}
    geom_dict['verts'] = verts
    geom_dict['faces'] = faces
    
    #return geom_dict['verts'], geom_dict['faces'], geom_dict
    return geom_dict
