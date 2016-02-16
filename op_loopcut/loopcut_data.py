'''
Created on Jul 12, 2015

@author: Patrick
'''
import bpy
import bmesh
from mathutils import Matrix
from mathutils.bvhtree import BVHTree

class LoopCut(object):
    def __init__(self, context, targ_obj, trg_bvh, source_obj = None, source_bvh = None):
        self.target_name = targ_obj.name
        self.trg_bvh = trg_bvh
        self.source_name = None
        self.source_mx = Matrix.Identity(4)
        
        if source_obj:
            self.source_name = source_obj.name
            self.src_bvh = source_bvh
            self.source_mx = source_obj.matrix_world
            
        self.face_loop_eds = []
        self.face_loop_fs = []
        self.vert_snaps_local = []
        self.vert_snaps_world = []
        self.slide_reverse = []
        self.slide = False
        self.pct = .5
        
    def clear(self):
        self.face_loop_eds = []
        self.face_loop_fs = []
        self.vert_snaps_local = []
        self.vert_snaps_world = []
        self.slide_reverse = []
        
        self.cyclic = False
        self.slide = False
        self.pct = .5 
    
    def find_face_loop(self,bme, ed, select = False):
        '''takes a bmface and bmedgse'''
        #reality check
        if not len(ed.link_faces): return
        
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
        self.cyclic = False
        
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
                self.cyclic = True
                self.face_loop_fs = fs
                self.face_loop_eds = eds[:len(eds)-1]
                self.slide_reverse = revs[:len(eds)-1]
                return
            else:
                if len(fs):
                    loop_faces.append(fs)
                    loop_eds.append(eds)
                    loop_revs.append(revs)
        
        if len(loop_faces) == 2:    
            loop_faces[0].reverse()    
            self.face_loop_fs = loop_faces[0] +  loop_faces[1]
            tip = loop_eds[0][1:]
            tip.reverse()
            self.face_loop_eds = tip + loop_eds[1]
            rev_tip = loop_revs[0][1:]
            rev_tip.reverse()
            self.slide_reverse = rev_tip + loop_revs[1]
            
        else:
            self.face_loop_fs = loop_faces[0]
            self.face_loop_eds = loop_eds[0]
            self.slide_reverse = loop_revs[0]
            
        return
    
    def find_edge_loop(self,bme,edge,vert):
        ''' '''
        pass

    def calc_snaps(self,bme):

        if not len(self.face_loop_eds): return
        self.vert_snaps_local = []
        self.vert_snaps_world = []
        
        if self.source_name:
            ob = bpy.data.objects[self.source_name]
            mx_src = ob.matrix_world
            imx_src = mx_src.inverted()
            
        
        mx_trg = bpy.data.objects[self.target_name].matrix_world
        imx_trg = mx_trg.inverted()

        for i, n in enumerate(self.face_loop_eds):
            ed = bme.edges[n]
            
            if self.slide_reverse[i]:
                v = (1- self.pct) * ed.verts[1].co + (self.pct) * ed.verts[0].co
            else:
                v = (1 - self.pct) * ed.verts[0].co + (self.pct) * ed.verts[1].co
            
            if not self.source_name:
                self.vert_snaps_local += [v]
                self.vert_snaps_world += [mx_trg * v]
            else:
                loc, no, indx, d = self.src_bvh.find_nearest(imx_src * mx_trg * v)
                self.vert_snaps_local += [imx_trg * mx_src * loc]
                self.vert_snaps_world += [mx_src * loc]
       
    def cut_loop(self, bme, select = True):
        '''
        bme is the target bme
        '''

        eds = [bme.edges[i] for i in self.face_loop_eds]
        
        #dummy ed percentage map
        ed_pcts = {}
        for ed in eds:
            ed_pcts[ed] = .1

        geom =  bmesh.ops.bisect_edges(bme, edges = eds,cuts = 1,edge_percents = ed_pcts)
        new_verts = [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMVert)]
        for i,v in enumerate(new_verts):
            v.co = self.vert_snaps_local[i]
            
        new_edges = []
        for i in range(0,len(new_verts)):
            bme.verts.ensure_lookup_table()
            v_pair = [new_verts[i], new_verts[i-1]]
            geom = bmesh.ops.connect_verts(bme, verts = v_pair, faces_exclude = [], check_degenerate = False)
            new_edges += [ele for ele in geom['edges'] if isinstance(ele, bmesh.types.BMEdge)]
        
        if select:
            for ed in bme.edges:
                ed.select_set(False)
            bme.select_flush(False)
            for ed in new_edges:
                ed.select_set(True)
        return
    
    def update_trg_bvh(self, bme):
        bme.faces.ensure_lookup_table()
        bme.edges.ensure_lookup_table()
        bme.verts.ensure_lookup_table()
        self.trg_bvh = BVHTree.FromBMesh(bme)
        return self.trg_bvh
        
    def push_to_edit_mesh(self,bme):
        target_ob = bpy.data.objects[self.target_name]
        bmesh.update_edit_mesh(target_ob.data)
    