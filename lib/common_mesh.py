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

#### Small Utils###
def face_neighbors_by_edge(bmface):
    neighbors = []
    for ed in bmface.edges:
        neighbors += [f for f in ed.link_faces if f != bmface]
        
    return neighbors

def face_neighbors_by_vert(bmface):
    neighbors = []
    for v in bmface.verts:
        neighbors += [f for f in v.link_faces if f != bmface]
        
    return neighbors

def edge_loops_from_bmedges(bmesh, bm_edges, ret = {'VERTS'}):
    """
    args:
       bmesh - a BMEsh
       bm_edges - an UNORDERED list of edge indices in the bmesh
       ret - a dictionary with {'VERTS', 'EDGES'}  which determines what data to return
    
    returns:
        a dictionary with keys 'VERTS' 'EDGES' containing lists of the corresponding data

    geom_dict['VERTS'] =   [ [1, 6, 7, 2], ...]

    closed loops have matching start and end vert indices
    closed loops will not have duplicate edge indices
    
    Notes:  This method is not "smart" in any way, and does not leverage BMesh
    connectivity data.  Therefore it could iterate  len(bm_edges)! (factorial) times
    There are better methods to use if your bm_edges are already in order  This is mostly
    used to sort non_man_edges = [ed.index for ed in bmesh.edges if not ed.is_manifold]
    There will be better methods regardless that utilize walking some day....
    """
    geom_dict = dict()
    geom_dict['VERTS'] = []
    geom_dict['EDGES'] = []
    edges = bm_edges.copy()
    
    while edges:
        current_edge = bmesh.edges[edges.pop()]
        
        vert_e, vert_st = current_edge.verts[:]
        vert_end, vert_start = vert_e.index, vert_st.index
        line_poly = [vert_start, vert_end]
        ed_loop = [current_edge.index]
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
                    ed_loop.append(ed.index)
                    vert_end = line_poly[-1]
                    ok = 1
                    del edges[i]
                    # break
                elif v2 == vert_end:
                    line_poly.append(v1)
                    ed_loop.append(ed.index)
                    vert_end = line_poly[-1]
                    ok = 1
                    del edges[i]
                    #break
                elif v1 == vert_start:
                    line_poly.insert(0, v2)
                    ed_loop.insert(0, ed.index)
                    vert_start = line_poly[0]
                    ok = 1
                    del edges[i]
                    # break
                elif v2 == vert_start:
                    line_poly.insert(0, v1)
                    ed_loop.insert(0, ed.index)
                    vert_start = line_poly[0]
                    ok = 1
                    del edges[i]#break
        
          
        if 'VERTS' in ret:            
            geom_dict['VERTS'] += [line_poly]
        if 'EDGES' in ret:
            print('adding edge loop to dict')
            geom_dict['EDGES'] += [ed_loop]

    return geom_dict

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

            face_loop_fs = fs
            face_loop_eds = eds[:len(eds)-1]

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

        
    elif len(loop_faces) == 1:
        face_loop_fs = loop_faces[0]
        face_loop_eds = loop_eds[0]

    else:
        face_loop_fs, face_loop_eds = [], []
            
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
    
    def next_vert(cur_ed, cur_vert):
        next_vert = cur_ed.other_vert(cur_vert)
        return next_vert
    
    loop_eds = []
    loop_verts = []

    for i, v in enumerate(ed.verts):
        if len(v.link_edges) != 4:
            if all(l_ed.is_manifold for l_ed in v.link_edges) or len(v.link_edges) > 3:  #Pole within mesh
                if i == 0: pole0 = v.index
                else: pole1 = v.index
                continue #this is a pole for sure
                
            elif len([l_ed for l_ed in v.link_edges if l_ed.is_manifold]) == 1 and len(v.link_edges) == 3: #End of mesh

                loop_eds.append([ed.index])        
                loop_verts.append([v.index])

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
            
            ed_next = next_edge(ed_cur, v_cur)
            if not ed_next: break
            eds += [ed_next.index]

            
            v_next = next_vert(ed_next, v_cur)
            
            if len(v_next.link_edges) != 4:
                
                if all(ed.is_manifold for ed in v_next.link_edges):
                    break #this is a pole for sure
                
                elif len([ed for ed in v_next.link_edges if ed.is_manifold]) == 1 and len(v_next.link_edges) == 3:
   
                    vs += [v_next.index]

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


            return vert_loop_vs, edge_loop_eds
        else:
            if len(vs):
                loop_verts.append(vs)
                loop_eds.append(eds)

    
    if len(loop_verts) == 2:    
        loop_verts[0].reverse()    
        vert_loop_vs = loop_verts[0] +  loop_verts[1]
        tip = loop_eds[0][1:]
        tip.reverse()
        edge_loop_eds = tip + loop_eds[1]
   
    else:
        vert_loop_vs = loop_verts[0]
        edge_loop_eds = loop_eds[0]

        
    return vert_loop_vs, edge_loop_eds

def edge_loop_neighbors(bme, edge_loop, strict = False, trim_tails = True, expansion = 'EDGES', quad_only = True):
    '''
    bme - the bmesh which the edges belongs to
    edge_loop - list of BMEdge indices.  Not necessarily in order, possibly multiple edge loops
    strict - Bool
           False , not strict, returns all loops regardless of topology
           True  ,  loops must be connected by quads only
                    Only returns  if the parallel loops are exactly the same length as original loop
        
    trim_tails - will trim p shaped loops or figure 8 loops
    
    expansion - 'EDGES'  - a single edge loop within a mesh will return 
                           2 parallel and equal length edge loops
                'VERTS'  - a single edge loop within a mesh will return
                           a single edge loop around the single loop
                           only use with strict = False
    
    quad_only  - Allow for generic edge loop expansion in triangle meshes if False
    
    returns a dictionary  with keys 'VERTS' 'EDGES' 'FACES'.  geom_dict
    
    the 'VERTS' and 'EDGES' lists are correlated.
    Eg geom_dict['VERTS'][0] and geom_dict['EDGES'][0] are corresponding vert and edge loops
    However geom_dict['FACES'][0] may correlate with geom_dict['EDGES'][1]
    
    
    '''
    
    
    ed_loops = edge_loops_from_bmedges(bme, edge_loop, ret = {'VERTS','EDGES'})
    
    geom_dict = dict()
    geom_dict['VERTS'] = []
    geom_dict['EDGES'] = []
    geom_dict['FACES'] = []
    
    for v_inds, ed_inds in zip(ed_loops['VERTS'],ed_loops['EDGES']):
        
        v0 = bme.verts[v_inds[0]]
        e0 = bme.edges[ed_inds[0]]
        v1 = e0.other_vert(v0)
        
        orig_eds = set(ed_inds)
        #find all the faces directly attached to this edge loop
        all_faces = set()
        
        if quad_only:
            if expansion == 'EDGES':
                for e_ind in ed_inds:
                    all_faces.update([f.index for f in bme.edges[e_ind].link_faces if len(f.verts) == 4])
                
            elif expansion == 'VERTS':
                for v_ind in v_inds:
                    all_faces.update([f.index for f in bme.verts[v_ind].link_faces if len(f.verts) == 4])
                
        else:
            for e_ind in ed_inds:
                for v in bme.edges[e_ind].verts:            
                    all_faces.update([f.index for f in v.link_faces])
        
        #find all the edges perpendicular to this edge loop
        perp_eds = set()
        for v_ind in v_inds:
            perp_eds.update([ed.index for ed in bme.verts[v_ind].link_edges if ed.index not in orig_eds])
        
        
        parallel_eds = []
        
        if quad_only:
            for f_ind in all_faces:
                parallel_eds += [ed.index for ed in bme.faces[f_ind].edges if 
                             ed.index not in perp_eds and ed.index not in orig_eds
                             and not (all([f.index in all_faces for f in ed.link_faces]) and trim_tails)]
        else:
            for f_ind in all_faces:
                parallel_eds += [ed.index for ed in bme.faces[f_ind].edges if
                                 ed.index not in orig_eds
                                 and not all([f.index in all_faces for f in ed.link_faces])]
        
            print('Triangle Problems ')
            print(parallel_eds)
        #sort them!    
        parallel_loops =  edge_loops_from_bmedges(bme, parallel_eds, ret = {'VERTS','EDGES'})   
        
        #get the face loops, a little differently, just walk from 2 perpendicular edges

        for ed in v1.link_edges:
            if ed.index not in perp_eds: continue
            f_inds, _e_inds = find_face_loop(bme, ed, select=False)
            print(f_inds)
            #keep only the part of face loop direclty next door
            if strict:
                f_inds = [f for f in f_inds if f in all_faces]
            geom_dict['FACES'] += [f_inds]
        
        if strict:
            if all([len(e_loop) == len(ed_inds) for e_loop in parallel_loops['EDGES']]):
                for v_loop in parallel_loops['VERTS']:
                    geom_dict['VERTS'] += [v_loop]
                for e_loop in parallel_loops['EDGES']:
                    geom_dict['EDGES'] += [e_loop]
                
                
            elif any([len(e_loop) == len(ed_inds) for e_loop in parallel_loops['EDGES']]):

                for pvs, peds in zip(parallel_loops['VERTS'],parallel_loops['EDGES']):
                    if len(peds) == len(ed_inds):
                        geom_dict['VERTS'] += [pvs]
                        geom_dict['EDGES'] += [peds]
                

        else:
            for v_loop in parallel_loops['VERTS']:
                geom_dict['VERTS'] += [v_loop]
            for e_loop in parallel_loops['EDGES']:
                geom_dict['EDGES'] += [e_loop]
    
                      
    return geom_dict
                
def find_edge_loops(bme, sel_vert_corners, select = False, max_chain = 20, max_iters = 1000):
    '''takes N verts which define the corners of a
    polygon patch and returns the edges ordered in
    one direction around the loop.  
    
    border eds must be non manifold.
    
    corner verts should only have 2 non man edges,
    eg, no edge_net networks are supported yet
    
    
    
    returns vert coords, vert_inds, ed_inds
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

def face_region_boundary_loops(bme, sel_faces):
    '''
    bme - BMesh object
    sel_faces:  list of face indices
    
    '''
    face_set = set(sel_faces)
    edges_raw = [ed.index for ed in bme.edges if ed.select and len([f.index for f in ed.link_faces if f.index in face_set]) == 1]
    
    geom_dict = edge_loops_from_bmedges(bme, edges_raw, ret={'VERTS','EDGES'})
    
    return geom_dict
     
def grow_selection_between_faces(bme, start_face, stop_face, max_iters = 1000, reverse = False):
    '''
    Takes a face pair, expands topologically from start_face untilthe stop_face is reached.
    
    if reverse, it will do the search in reverse, to trimm off excess faces which expanded
    the other direction.
    '''

    total_selection = set([start_face])
    new_faces = set(face_neighbors_by_vert(start_face))
    
    if stop_face in new_faces:
        total_selection |= new_faces
        return total_selection
    
    iters = 0
    while iters < max_iters and stop_face not in new_faces:
        iters += 1
        candidates = set()
        for f in new_faces:
            candidates.update(face_neighbors_by_vert(f))
        
        new_faces = candidates - total_selection   
        if new_faces:
            total_selection |= new_faces
             
    if iters == max_iters:
        print('max iterations reached in initial growing')   
        return total_selection
    
    if not reverse:
        return total_selection


    overlapped_selection = set([stop_face])
    new_faces = set(face_neighbors_by_vert(stop_face)) & total_selection
    overlapped_selection |= new_faces
    
    iters = 0
    while iters < max_iters and start_face not in new_faces:
        iters += 1
        candidates = set()
        for f in new_faces:
            candidates.update(face_neighbors_by_vert(f))
        
        new_faces = (candidates & total_selection) - overlapped_selection 
        if new_faces:
            overlapped_selection |= new_faces
             
    if iters == max_iters:
        print('max iterations reached in trim operation')   
        return overlapped_selection
    
    return overlapped_selection

def grow_selection_between_faces2(bme, face1, face2, max_iters = 1000, trim = True):
    '''
    Takes a face pair, expands topologically from both faces until the the two regions meet
    
    
    if trim, it will do the search in from one to the other, to trim off excess faces.
    '''

    
    
    set1 = set([face1])
    set2 = set([face2])
    
    
    new_faces1 = set(face_neighbors_by_vert(face1))
    new_faces2 = set(face_neighbors_by_vert(face2))
    
    if new_faces1 & new_faces2:
        return new_faces1 | new_faces2 
    
    iters = 0
    while iters < max_iters and (new_faces1 or new_faces2):
        iters += 1
        candidates1 = set()
        candidates2 = set()
        
        for f in new_faces1:
            candidates1.update(face_neighbors_by_vert(f))
        
        new_faces1 = candidates1 - set1   
        if new_faces1:
            set1 |= new_faces1
        
        for f in new_faces2:
            candidates2.update(face_neighbors_by_vert(f))
        
        new_faces2 = candidates2 - set2   
        if new_faces2:
            set2 |= new_faces2
            
        if new_faces1 & new_faces2:
            print('overlap found')
            set1 |= set2
            break
             
    if iters == max_iters:
        print('max iterations reached')   
        return set1 | set2
    
    if not trim:
        return set1


    overlapped_selection = set([face1])
    new_faces = set(face_neighbors_by_vert(face1)) & set1
    overlapped_selection |= new_faces
    
    iters = 0
    while iters < max_iters and face2 not in new_faces:
        iters += 1
        candidates = set()
        for f in new_faces:
            candidates.update(face_neighbors_by_vert(f))
        
        new_faces = (candidates & set1) - overlapped_selection 
        if new_faces:
            overlapped_selection |= new_faces
             
    if iters == max_iters:
        print('max iterations reached in trim1')   
        return overlapped_selection
    
    final_selection = set([face2])
    new_faces = set(face_neighbors_by_vert(face2)) & overlapped_selection
    iters = 0
    while iters < max_iters and face1 not in new_faces:
        iters += 1
        candidates = set()
        for f in new_faces:
            candidates.update(face_neighbors_by_vert(f))
        
        new_faces = (candidates & overlapped_selection) - final_selection 
        if new_faces:
            final_selection |= new_faces
             
    if iters == max_iters:
        print('max iterations reached in trim1')   
        return overlapped_selection
    
    return final_selection

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
    l = len(src_trg_map)
    if not src_mx:
        src_mx = Matrix.Identity(4)
    
    if not trg_mx:
        trg_mx = Matrix.Identity(4)
        i_trg_mx = Matrix.Identity(4)
    else:
        i_trg_mx = trg_mx.inverted()
        
        

    new_bmverts = []
    
    source.verts.ensure_lookup_table()

    for v in source.verts:
        if v.index not in src_trg_map:
            new_ind = len(target.verts)
            new_bv = target.verts.new(i_trg_mx * src_mx * v.co)
            new_bmverts.append(new_bv)
            #new_bv.index = new_ind
            src_trg_map[v.index] = new_ind
    
    #new_bmverts = [target.verts.new(i_trg_mx * src_mx * v.co) for v in source.verts]# if v.index not in src_trg_map]

    #def src_to_trg_ind(v):
    #    subbed = False
    #    if v.index in src_trg_map:

    #       new_ind = src_trg_map[v.index]
    #        subbed = True
    #    else:
    #        new_ind = v.index + L  #TODO, this takes the actual versts from sources, these verts are in target
            
    #    return new_ind, subbed
    
    #new_bmfaces = [target.faces.new(tuple(new_bmverts[v.index] for v in face.verts)) for face in source.faces]
    target.verts.index_update()
    #target.verts.sort()  #does this still work?
    target.verts.ensure_lookup_table()
    #print('new faces')
    #for f in source.faces:
        #print(tuple(src_to_trg_ind(v) for v in f.verts))
    
    #subbed = set()
    new_bmfaces = []
    for f in source.faces:
        v_inds = []
        for v in f.verts:
            new_ind = src_trg_map[v.index]
            v_inds.append(new_ind)
            
        new_bmfaces += [target.faces.new(tuple(target.verts[i] for i in v_inds))]
    
    #new_bmfaces = [target.faces.new(tuple(target.verts[src_to_trg_ind(v)] for v in face.verts)) for face in source.faces]
    target.faces.ensure_lookup_table()
    target.verts.ensure_lookup_table()
    target.verts.index_update()
    
    #throw away the loose verts...not very elegant with edges and what not
    #n_removed = 0
    #for vert in new_bmverts:
    #    if (vert.index - L) in src_trg_map: #these are verts that are not needed
    #        target.verts.remove(vert)
    #        n_removed += 1
    
    #bmesh.ops.delete(target, geom=del_verts, context=1)
            
    target.verts.index_update()        
    target.verts.ensure_lookup_table()
    target.faces.ensure_lookup_table()
    
    new_L = len(target.verts)
    
    if src_trg_map:
        if new_L != L + len(source.verts) -l:
            print('seems some verts were left in that should not have been')
                       
def find_perimeter_verts(bme):
    '''
    returns a list of vert indices, in order
    around the perimeter of a mesh
    '''
    bme.edges.index_update()
    bme.edges.ensure_lookup_table()
    bme.verts.ensure_lookup_table()
    
    non_man_eds = [ed.index for ed in bme.edges if not ed.is_manifold]
    ed_loops = edge_loops_from_bmedges(bme, non_man_eds)['VERTS']
    
    
    if len(ed_loops) == 0:
        print('no perimeter, watertight surface')
        return []
    
    else:
        perim = ed_loops[0]
        perim.pop()
        n = perim.index(min(perim))
        return perim[n:] + perim[:n]

def flood_selection_edge_loop(bme, edge_loop, seed_face, max_iters = 1000):
    '''
    bme - bmesh
    edge_loop - should create a closed edge loop to contain "flooded" selection
    if an empty set, selection will grow to non manifold boundaries
    seed_face - a face within/out selected_faces loop
    max_iters - maximum recursions to select_neightbors
    
    return - set of faces
    '''
    total_selection = set()
    total_selection.add(seed_face)
    
    face_levy = set()
    for e in edge_loop:
        face_levy.update([f for f in e.link_faces])  #it's funny because it stops the flood :-)

    edge_levy = set([e for e in edge_loop])
    
    new_faces = set(face_neighbors_by_edge(seed_face)) - face_levy
    iters = 0
    while iters < max_iters and new_faces:
        iters += 1
        new_candidates = set()
        for f in new_faces:
            new_candidates.update(face_neighbors_by_edge(f))
            
        new_faces = (new_candidates - total_selection)
        #remove = set()
        #for f in new_faces:
        #    if any([e for e in f.edges if e in edge_levy]):
        #        remove.add(f)
                
        
        
        if new_faces:
            total_selection |= new_faces
            new_faces -= face_levy    
    if iters == max_iters:
        print('max iterations reached')   
        

    return total_selection