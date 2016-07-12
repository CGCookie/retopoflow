'''
Created on Jul 13, 2015

@author: Patrick
'''
import bpy
import bmesh
from mathutils.geometry import intersect_point_line
from ..lib import common_utilities

class loopslide_UI_fns():

    def slide_cancel(self,context,eventd, settings):
        return

    def hover_edge_pick(self,context,eventd,settings):
        x,y = eventd['mouse']
        region = context.region
        region = eventd['region']
        r3d = eventd['r3d']

        hit = common_utilities.ray_cast_region2d_bvh(region, r3d, (x,y), self.trg_bvh, self.trg_mx, settings)[1]

        if hit[2] != None: #TODO store the ed in loopcut class and only recalc if it's different
            pt = hit[0]
            def ed_dist(ed):
                p0 = ed.verts[0].co
                p1 = ed.verts[1].co
                pmin, pct = intersect_point_line(pt, p0, p1)   
                dist = pmin - pt
                return dist.length, pct


            f = self.trg_bme.faces[hit[2]]
            eds = [ed for ed in f.edges]
            test_edge = min(eds, key = ed_dist)

            self.loopslide.find_edge_loop(self.trg_bme,test_edge)
            self.loopslide.pct = 0
            self.loopslide.right = True
            self.loopslide.calc_snaps(self.trg_bme, snap = False)
        else:
            self.loopslide.clear()

    def slide_update(self,context,eventd,settings):
        x,y = eventd['mouse']
        region = context.region
        region = eventd['region']
        r3d = eventd['r3d']
        hit = common_utilities.ray_cast_region2d_bvh(region, r3d, (x,y), self.trg_bvh, self.trg_mx, settings)[1]

        if hit[2] != None:
            pt = hit[0]
            def dist(v_index):
                v = self.trg_bme.verts[v_index]
                l = v.co - pt
                return l.length

            v_ind = min(self.loopslide.vert_loop_vs, key = dist)  #<  The closest edgeloop point to the mouse
            n = self.loopslide.vert_loop_vs.index(v_ind)
            v_pt = self.trg_bme.verts[v_ind].co
            
            p_right, pct_right = intersect_point_line(pt, v_pt, v_pt + self.loopslide.edge_loop_right[n])
            p_left, pct_left = intersect_point_line(pt, v_pt, v_pt + self.loopslide.edge_loop_left[n])

            if pct_right > 0:
                self.loopslide.pct = min(1, pct_right)
                self.loopslide.right = True
            else:
                self.loopslide.right = False
                self.loopslide.pct = min(1, pct_left)


            self.loopslide.calc_snaps(self.trg_bme, snap = False)

        return
