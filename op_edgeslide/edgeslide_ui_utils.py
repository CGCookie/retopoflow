'''
Created on Jul 13, 2015

@author: Patrick
'''
import bpy
import bmesh
from mathutils.geometry import intersect_point_line
from ..lib import common_utilities

class EdgeSlide_UI_fns():
    
    def slide_cancel(self,context,eventd, settings):
        
        return
    
    def hover_edge_pick(self,context,eventd,settings):
        x,y = eventd['mouse']
        region = context.region
        region = eventd['region']
        r3d = eventd['r3d']
        
        bpy.ops.object.editmode_toggle()
        hit = common_utilities.ray_cast_region2d(region, r3d, (x,y), self.trg_obj, settings)[1]
        bpy.ops.object.editmode_toggle()
        
        self.bme = bmesh.from_edit_mesh(self.trg_obj.data)
        self.bme.faces.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.verts.ensure_lookup_table()
        
        if hit[2] != -1: #TODO store the ed in loopcut class and only recalc if it's different
            pt = hit[0]
            def ed_dist(ed):
                p0 = ed.verts[0].co
                p1 = ed.verts[1].co
                pmin, pct = intersect_point_line(pt, p0, p1)   
                dist = pmin - pt
                return dist.length, pct
            
            
            f = self.bme.faces[hit[2]]
            eds = [ed for ed in f.edges]
            test_edge = min(eds, key = ed_dist)
            
            self.edgeslide.find_edge_loop(self.bme,test_edge)
            self.edgeslide.pct = 0
            self.edgeslide.right = True
            self.edgeslide.calc_snaps(self.bme)
        else:
            self.edgeslide.clear()
            
    def slide_update(self,context,eventd,settings):
        x,y = eventd['mouse']
        region = context.region
        region = eventd['region']
        r3d = eventd['r3d']
        
        bpy.ops.object.editmode_toggle()
        hit = common_utilities.ray_cast_region2d(region, r3d, (x,y), self.trg_obj, settings)[1]
        bpy.ops.object.editmode_toggle()
        self.bme = bmesh.from_edit_mesh(self.trg_obj.data)
        self.bme.faces.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.verts.ensure_lookup_table()
        if hit[2] != -1:
            pt = hit[0]
            def dist(v_index):
                v = self.bme.verts[v_index]
                l = v.co - pt
                return l.length
            
            v_ind = min(self.edgeslide.vert_loop_vs, key = dist)  #<  The closest edgeloop point to the mouse
            n = self.edgeslide.vert_loop_vs.index(v_ind)
            v_pt = self.bme.verts[v_ind].co
            
            p_right, pct_right = intersect_point_line(pt, v_pt, v_pt + self.edgeslide.edge_loop_right[n])
            p_left, pct_left = intersect_point_line(pt, v_pt, v_pt + self.edgeslide.edge_loop_left[n])
            
            if pct_right > 0:
                self.edgeslide.pct = min(1, pct_right)
                self.edgeslide.right = True
            else:
                self.edgeslide.right = False
                self.edgeslide.pct = min(1, pct_left)
                
                
            self.edgeslide.calc_snaps(self.bme)
            
        return            