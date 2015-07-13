'''
Created on Jul 12, 2015

@author: Patrick
'''
import bpy
import bmesh

class LoopCut(object):
    
    def __init__(self, context, targ_obj, source_obj = None):
        self.target_name =targ_obj.name
        self.source_name = None
        if source_obj:
            self.source_name = source_obj.name
            
        self.face_loop_eds = []
        self.face_loop_fs = []
        self.vert_snaps_local = []
        self.vert_snaps_world = []
    
    def clear(self):
        self.face_loop_eds = []
        self.face_loop_fs = []
        self.vert_snaps_local = []
        self.vert_snaps_world = []
        self.cyclic = False
         
    def find_face_loop(self,bme, ed, select = False):
        '''takes a bmface and bmedgse'''
        #reality check
        if not len(ed.link_faces): return
        
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
        self.cyclic = False
        
        for f in ed.link_faces:
            if len(f.edges) != 4: continue            
            eds = [ed.index]
            fs = [f.index]    
            
            f_next = True
            f_cur = f
            ed_cur = ed
            while f_next != f:
                if select:
                    f_cur.select_set(True) 
                    ed_cur.select_set(True)
                
                ed_next = next_edge(f_cur, ed_cur)
                eds += [ed_next.index]
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
                return
            else:
                if len(fs):
                    loop_faces.append(fs)
                    loop_eds.append(eds)
        
        if len(loop_faces) == 2:    
            loop_faces[0].reverse()    
            self.face_loop_fs = loop_faces[0] +  loop_faces[1]
            tip = loop_eds[0][1:]
            tip.reverse()
            self.face_loop_eds = tip + loop_eds[1]
        else:
            self.face_loop_fs = loop_faces[0]
            self.face_loop_eds = loop_eds[0]
            
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
        for i in self.face_loop_eds:
            ed = bme.edges[i]
            v = .5 * ed.verts[1].co + .5 * ed.verts[0].co
            if not self.source_name:
                self.vert_snaps_local += [v]
                self.vert_snaps_world += [mx_trg * v]
            else:
                loc, no, indx = ob.closest_point_on_mesh(imx_src * mx_trg * v)
                self.vert_snaps_local += [imx_trg * mx_src * loc]
                self.vert_snaps_world += [mx_src * loc]
            
                 
    def cut_loop(self, bme, select = True):

        eds = [bme.edges[i] for i in self.face_loop_eds]
        
        #dummy ed percentage map
        ed_pcts = {}
        for ed in eds:
            ed_pcts[ed] = .1

        geom =  bmesh.ops.bisect_edges(bme, edges = eds,cuts = 1,edge_percents = ed_pcts)
        new_verts = [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMVert)]

        print([len(new_verts),len(self.vert_snaps_local)])
        for i,v in enumerate(new_verts):
            v.co = self.vert_snaps_local[i]
            
        new_edges = []
        for i in range(0,len(new_verts)):
            bme.verts.ensure_lookup_table()
            v_pair = [new_verts[i], new_verts[i-1]]
            geom = bmesh.ops.connect_verts(bme, verts = v_pair, faces_exclude = [], check_degenerate = False)
            new_edges += [ele for ele in geom['edges'] if isinstance(ele, bmesh.types.BMEdge)]
        
        if select:
            for ed in new_edges:
                ed.select_set(True)
        return
    
    def push_to_edit_mesh(self,bme):
        target_ob = bpy.data.objects[self.target_name]
        bmesh.update_edit_mesh(target_ob.data)
    