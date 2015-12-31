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

def find_edge_loops(bme, sel_vert_corners, select = False):
    '''takes N verts which define the corners of a
    polygon patch and returns the edges ordered in
    one direction around the loop.  Eds must be non
    manifold
    '''
    
    bme.edges.ensure_lookup_table()
    bme.verts.ensure_lookup_table()
       
    def next_edge(cur_ed, cur_vert):
        ledges = [ed for ed in cur_vert.link_edges if ed != cur_ed]
        next_edge = [ed for ed in ledges if not ed.is_manifold][0]
        return next_edge
    
    def next_vert(cur_ed, cur_vert):
        next_vert = cur_ed.other_vert(cur_vert)
        return next_vert
    
    vert_chains_co = []
    vert_chains_ind = []
    
    corner_inds = [v.index for v in sel_vert_corners]
    max_iters = 1000
     
    v_cur = bme.verts[corner_inds[0]]
    ed_cur = [ed for ed in v_cur.link_edges if not ed.is_manifold][0]
    iters = 0
    while len(corner_inds) and iters < max_iters:
        v_chain = [v_cur.co]
        v_chain_ind = [v_cur.index]
        print('starting at current v index: %i' % v_cur.index)
        marching = True
        while marching:
            iters += 1
            ed_next = next_edge(ed_cur, v_cur) 
            v_next = next_vert(ed_next, v_cur)
            
            v_chain += [v_next.co]
            ed_cur = ed_next
            v_cur = v_next
            if v_next.index in corner_inds:
                print('Stopping: found a corner %i' % v_next.index)
                corner_inds.pop(corner_inds.index(v_next.index))
                vert_chains_co.append(v_chain)
                vert_chains_ind.append(v_chain_ind)
                marching = False
    
    return vert_chains_co, vert_chains_ind

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
    
    #TDOD  matrix math stuff
    new_bmverts = [target.verts.new(v.co) for v in source.verts]# if v.index not in src_trg_map]
    
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
