'''
Copyright (C) 2015 CG Cookie
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

# Blender imports
import bmesh
from mathutils import Matrix

def edge_loops_from_bmedges(bmesh, bm_edges):
    """
    Edge loops defined by edges

    Takes list of [mesh edge indices] and returns the edge loops

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

def find_face_loop(bme, ed, select = False):
    '''
    takes a bmedge, and walks perpendicular to it
    returns [face inds], [ed inds]
    '''
    #reality check
    if not len(ed.link_faces): return []
    
    def ed_to_vect(ed):
        vect = ed.verts[1].co - ed.verts[0].co
        vect.normalize()
        return vect
        
    def next_edge(cur_face, cur_ed):
        ledges = [ed for ed in cur_face.edges]
        n = ledges.index(cur_ed)
        j = (n+2) % 4
        return cur_face.edges[j]
    
    def next_face(cur_face, edge):
        if len(edge.link_faces) == 1: return None
        next_face = [f for f in edge.link_faces if f != cur_face][0]
        return next_face
    
    loop_eds = []
    loop_faces = []
    loop_revs = []
    cyclic = False
    
    for f in ed.link_faces:
        if len(f.edges) != 4: continue            
        eds = [ed.index]
        fs = [f.index]
        revs = [False]   
        
        f_next = True
        f_cur = f
        ed_cur = ed
        while f_next != f:
            if select:
                f_cur.select_set(True) 
                ed_cur.select_set(True)
            
            ed_next = next_edge(f_cur, ed_cur)
            eds += [ed_next.index]
            
            parallel = ed_to_vect(ed_next).dot(ed_to_vect(ed_cur)) > 0
            prev_rev = revs[-1]
            rever = parallel == prev_rev                
            revs += [rever]
            
            f_next = next_face(f_cur, ed_next)
            if not f_next: break
            
            fs += [f_next.index]
            if len(f_next.verts) != 4:
                break
            
            ed_cur = ed_next
            f_cur = f_next
            
        #if we looped
        if f_next == f:
            cyclic = True
            face_loop_fs = fs
            face_loop_eds = eds[:len(eds)-1]
            slide_reverse = revs[:len(eds)-1]
            return face_loop_fs, face_loop_eds
        else:
            if len(fs):
                loop_faces.append(fs)
                loop_eds.append(eds)
                loop_revs.append(revs)
    
    if len(loop_faces) == 2:    
        loop_faces[0].reverse()    
        face_loop_fs = loop_faces[0] +  loop_faces[1]
        tip = loop_eds[0][1:]
        tip.reverse()
        face_loop_eds = tip + loop_eds[1]
        rev_tip = loop_revs[0][1:]
        rev_tip.reverse()
        slide_reverse = rev_tip + loop_revs[1]
        
    else:
        face_loop_fs = loop_faces[0]
        face_loop_eds = loop_eds[0]
        slide_reverse = loop_revs[0]
        
    return  face_loop_fs, face_loop_eds

def find_edge_loop(bme, ed, select = False):
    '''
    takes a bmede and walks parallel to it
    returns [vert inds], [ed_inds]
    '''
    
    
    #reality check
    if not ed.verts[0].is_manifold and not ed.verts[1].is_manifold: return [], []
    bme.edges.ensure_lookup_table()
    bme.verts.ensure_lookup_table()
    def ed_to_vect(ed):
        vect = ed.verts[1].co - ed.verts[0].co
        vect.normalize()
        return vect
      
    def next_edge(cur_ed, cur_vert):
        ledges = [ed for ed in cur_vert.link_edges if ed != cur_ed]
        
        fset = set([f.index for f in cur_ed.link_faces])
        
        next_eds = [ed for ed in ledges if not fset & set([f.index for f in ed.link_faces])]
        
        if len(next_eds):
            return next_eds[0]
        else:
            return None
        
        #forward = cur_vert.co - cur_ed.other_vert(cur_vert).co
        #forward.normalize()
        
        #sides = set(ledges)
        #sides.remove(next_edge)
        #esides = list(sides)
        #side0 = esides[0].other_vert(cur_vert).co - cur_vert.co
        #side1 = esides[1].other_vert(cur_vert).co - cur_vert.co
        
        
        #if cur_vert.normal.dot(side0.cross(forward)) > 0:
        #    v_right, v_left = side0, side1
        #else:
        #    v_left, v_right = side0, side1

        #return next_ed, v_right, v_left
    
    def next_vert(cur_ed, cur_vert):
        next_vert = cur_ed.other_vert(cur_vert)
        return next_vert
    
    loop_eds = []
    loop_verts = []
    loop_rights = []
    loop_lefts = []
    
    cyclic = False
    pole0 = -1
    pole1 = -1
    for i, v in enumerate(ed.verts):
        if len(v.link_edges) != 4:
            if all(l_ed.is_manifold for l_ed in v.link_edges) or len(v.link_edges) > 3:  #Pole within mesh
                if i == 0: pole0 = v.index
                else: pole1 = v.index
                continue #this is a pole for sure
                
            elif len([l_ed for l_ed in v.link_edges if l_ed.is_manifold]) == 1 and len(v.link_edges) == 3: #End of mesh
                #forward = v.co - ed.other_vert(v).co
                #esides = [l_ed for l_ed in v.link_edges if l_ed != ed]
                #side0 = esides[0].other_vert(v).co - v.co
                #side1 = esides[1].other_vert(v).co - v.co
                     
                #if v.normal.dot(side0.cross(forward)) > 0:
                #    v_right, v_left = side0, side1
                #else:
                #    v_left, v_right = side0, side1
                loop_eds.append([ed.index])        
                loop_verts.append([v.index])
                #loop_rights.append([v_right])
                #loop_lefts.append([v_left])
                continue
        elif len(v.link_edges) == 4 and not all(ed.is_manifold for ed in v.link_edges):  #corner vert
            if i == 0: pole0 = v.index
            else: pole1 = v.index
            continue  #corner!             
        eds = [ed.index]
        vs = [v.index]
        
        rights = []   
        lefts = []
        
        
        ed_cur = ed
        v_cur = v
        v_next = True
        while v_next != v:
            
            if select:
                v_cur.select_set(True) 
                ed_cur.select_set(True)
            
            #ed_next, right, left = next_edge(ed_cur, v_cur)
            ed_next = next_edge(ed_cur, v_cur)
            if not ed_next: break
            eds += [ed_next.index]
            #rights += [right]
            #lefts += [left]
            
            v_next = next_vert(ed_next, v_cur)
            
            if len(v_next.link_edges) != 4:
                
                if all(ed.is_manifold for ed in v_next.link_edges):
                    if i == 0: pole0 = v_next.index
                    else: pole1 = v_next.index
                    break #this is a pole for sure
                
                elif len([ed for ed in v_next.link_edges if ed.is_manifold]) == 1 and len(v_next.link_edges) == 3:
                    #forward = v_next.co - ed_next.other_vert(v_next).co
                    #esides = [ed for ed in v_next.link_edges if ed != ed_next]
                    #side0 = esides[0].other_vert(v_next).co - v_next.co
                    #side1 = esides[1].other_vert(v_next).co - v_next.co
                     
                    #if v_next.normal.dot(side0.cross(forward)) > 0:
                    #    v_right, v_left = side0, side1
                    #else:
                    #    v_left, v_right = side0, side1
                        
                    vs += [v_next.index]
                    #rights += [v_right]
                    #lefts += [v_left]
                    break
                
                else: break  #should never get here
            
            elif len(v_next.link_edges) == 4 and not all(ed.is_manifold for ed in v_next.link_edges):  
                if i == 0: pole0 = v_next.index
                else: pole1 = v_next.index
                break  #corner!
             
            vs += [v_next.index]
            ed_cur = ed_next
            v_cur = v_next
            
        
        if v_next == v: #we looped
            cyclic = True
            vert_loop_vs = vs[:len(vs)-1]
            edge_loop_eds = eds[:len(eds)-1] #<--- discard the edge we walked across to get back to start vert
            #self.edge_loop_right = rights
            #self.edge_loop_left = lefts

            return vert_loop_vs, edge_loop_eds
        else:
            if len(vs):
                loop_verts.append(vs)
                loop_eds.append(eds)
                #loop_rights.append(rights)
                #loop_lefts.append(lefts)
    
    if len(loop_verts) == 2:    
        loop_verts[0].reverse()    
        vert_loop_vs = loop_verts[0] +  loop_verts[1]
        tip = loop_eds[0][1:]
        tip.reverse()
        edge_loop_eds = tip + loop_eds[1]
        
        #loop_rights[0].reverse()
        #loop_lefts[0].reverse()
        
        #self.edge_loop_right = loop_lefts[0] + loop_rights[1]
        #self.edge_loop_left = loop_rights[0] + loop_lefts[1]
        
    else:
        vert_loop_vs = loop_verts[0]
        edge_loop_eds = loop_eds[0]
        #edge_loop_right = loop_rights[0]
        #edge_loop_left = loop_lefts[0]
        
    return vert_loop_vs, edge_loop_eds

def find_edge_loops(bme, sel_vert_corners, select = False, max_chain = 20, max_iters = 1000):
    '''takes N verts which define the corners of a
    polygon patch and returns the edges ordered in
    one direction around the loop.  
    
    border eds must be non manifold.
    
    corner verts should only have 2 non man edges,
    eg, no edge_net networks are supported yet
    
    
    
    returns 
    '''
    
    if len(sel_vert_corners) == 0: return []
    bme.edges.ensure_lookup_table()
    bme.verts.ensure_lookup_table()
       
    def next_edge(cur_ed, cur_vert):
        ledges = [ed for ed in cur_vert.link_edges if ed != cur_ed]
        next_edges = [ed for ed in ledges if not ed.is_manifold]
        
        if len(next_edges):
            return next_edges[0]
        else:
            return None
    
    def next_vert(cur_ed, cur_vert):
        next_vert = cur_ed.other_vert(cur_vert)
        return next_vert
    
    
    
    
    corner_inds = [v.index for v in sel_vert_corners]
    
    
    #start with the first one! 
    v_cur = bme.verts[corner_inds[0]]
    ed_curs = [ed for ed in v_cur.link_edges if not ed.is_manifold]
    
    
    if len(ed_curs) == 0: return [],[]
    ed_cur = ed_curs[0]
    iters = 0
    
    seen = set()
    seen.add(v_cur.index)
    
    vert_chains_co = []
    vert_chains_ind = []
    confirmed_corners = [v_cur.index]
    
    
    loops = []
    
    
    #the first v_cur is left in the corner_inds, so it will get popped off when looped back around
    while len(corner_inds) and iters < max_iters:  
        v_chain = [v_cur.co]
        v_chain_ind = [v_cur.index]
        print('starting at current v index: %i' % v_cur.index)
        marching = True
        steps = 0
        while marching and steps < max_chain:
            steps += 1
            iters += 1
            ed_next = next_edge(ed_cur, v_cur)
            if not ed_next: break
            v_next = next_vert(ed_next, v_cur)
            
            v_chain += [v_next.co]
            v_chain_ind += [v_next.index]
            ed_cur = ed_next
            v_cur = v_next
            if v_next.index in corner_inds:
                print('Stopping: found a corner %i' % v_next.index)
                
                corner_inds.pop(corner_inds.index(v_next.index))
                vert_chains_co.append(v_chain)
                vert_chains_ind.append(v_chain_ind)
                marching = False
                if v_next.index in seen:
                    loops += [(vert_chains_co, vert_chains_ind, confirmed_corners)]
                    vert_chains_co = []
                    vert_chains_ind = []
                    
                    if len(corner_inds): #another loop may exist, start over
                        v_cur = bme.verts[corner_inds[0]]
                        confirmed_corners = [v_cur.index]
                        seen.add(v_cur.index)
                        ed_curs = [ed for ed in v_cur.link_edges if not ed.is_manifold]
                        if not len(ed_curs):
                            return loops
                        ed_cur = ed_curs[0]
                else:
                    confirmed_corners += [v_next.index]
                
    
    return loops



def loops_from_edge_net(bme):
    ''' not implemented yet'''
    
    #find nodes
    
    #walk around those nodes
    
    #return the loops
    return None
    
    
def make_bme(verts, faces):
    bme = bmesh.new()
    bmverts = [bme.verts.new(v) for v in verts]  #TODO, matrix stuff
    bme.verts.index_update()
        
    bmfaces = [bme.faces.new(tuple(bmverts[iv] for iv in face)) for face in faces]
    bme.faces.index_update()
    bme.verts.ensure_lookup_table()
    bme.faces.ensure_lookup_table()
    return bme

def join_bmesh(source, target, src_trg_map = dict(), src_mx = None, trg_mx = None):
    '''
    
    '''
    L = len(target.verts)
    
    if not src_mx:
        src_mx = Matrix.Identity(4)
    
    if not trg_mx:
        trg_mx = Matrix.Identity(4)
        i_trg_mx = Matrix.Identity(4)
    else:
        i_trg_mx = trg_mx.inverted()
        
        
    #TDOD  matrix math stuff
    new_bmverts = [target.verts.new(i_trg_mx * src_mx * v.co) for v in source.verts]# if v.index not in src_trg_map]
    
    def src_to_trg_ind(v):
        if v.index in src_trg_map:
            new_ind = src_trg_map[v.index]
        else:
            new_ind = v.index + L  #TODO, this takes the actual versts from sources, these verts are in target
            
        return new_ind
    
    #new_bmfaces = [target.faces.new(tuple(new_bmverts[v.index] for v in face.verts)) for face in source.faces]
    target.verts.index_update()  #does this still work?
    target.verts.ensure_lookup_table()
    #print('new faces')
    #for f in source.faces:
        #print(tuple(src_to_trg_ind(v) for v in f.verts))
    new_bmfaces = [target.faces.new(tuple(target.verts[src_to_trg_ind(v)] for v in face.verts)) for face in source.faces]
    target.faces.ensure_lookup_table()
    target.verts.ensure_lookup_table()
    
    #throw away the loose verts...not very elegant with edges and what not
    
    for vert in new_bmverts:
        if (vert.index - L) in src_trg_map: #these are verts that are not needed
            target.verts.remove(vert) 
            
    target.verts.ensure_lookup_table()
    target.verts.index_update()
            
def find_perimeter_verts(bme):
    '''
    returns a list of vert indices, in order
    around the perimeter of a mesh
    '''
    bme.edges.index_update()
    bme.edges.ensure_lookup_table()
    bme.verts.ensure_lookup_table()
    
    non_man_eds = [ed.index for ed in bme.edges if not ed.is_manifold]
    ed_loops = edge_loops_from_bmedges(bme, non_man_eds)
    
    
    if len(ed_loops) == 0:
        print('no perimeter, watertight surface')
        return []
    
    else:
        perim = ed_loops[0]
        perim.pop()
        n = perim.index(min(perim))
        return perim[n:] + perim[:n]
