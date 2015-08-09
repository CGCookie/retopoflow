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

import bpy
import bgl
import bmesh
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix, Quaternion
import math

from ..lib import common_utilities
from ..lib.common_utilities import bversion, get_object_length_scale, dprint, profiler, frange, selection_mouse, showErrorMessage


class Tweak_UI_Tools():
    
    ##############################
    # modal tool functions
    
    def modal_tweak_setup(self, context, eventd, max_dist=1.0):
        settings = common_utilities.get_settings()
        region = eventd['region']
        r3d = eventd['r3d']
        
        mx = self.obj.matrix_world
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        
        ray,hit = common_utilities.ray_cast_region2d(region, r3d, eventd['mouse'], self.obj, settings)
        hit_p3d,hit_norm,hit_idx = hit
        
        hit_p3d = mx * hit_p3d
        
        lgvmove = []  #GVert
        lgvextmove = []  #GVerts  and BMVert 
        lgemove = []  #Gedges
        lgpmove = [] #Patch
        lmverts = []  #BMVert
        supdate = set()
        
        for i_mv,mv in enumerate(self.dest_bme.verts):
            d = (mx*mv.co-hit_p3d).length / self.stroke_radius
            if not d < max_dist:
                continue
            lmverts.append((i_mv,mx *mv.co,d))
        
        
        self.tweak_data = {
            'mouse': eventd['mouse'],
            'lmverts': lmverts,
            'supdate': supdate,
            'mx': mx,
            'mx3x3': mx3x3,
            'imx': imx,
        }
        
    
    def modal_tweak_move_tool(self, context, eventd):
        if eventd['release'] in self.keymap['action']:
            return 'main'
        
        settings = common_utilities.get_settings()
        region = eventd['region']
        r3d = eventd['r3d']
        
        if eventd['type'] == 'MOUSEMOVE' and self.tweak_data:
            cx,cy = eventd['mouse']
            lx,ly = self.tweak_data['mouse']
            dx,dy = cx-lx,cy-ly
            dv = Vector((dx,dy))
            
            mx = self.tweak_data['mx']
            mx3x3 = self.tweak_data['mx3x3']
            imx = self.tweak_data['imx']
            
            def update(p3d, d):
                if d >= 1.0: return p3d
                p2d = location_3d_to_region_2d(region, r3d, p3d)
                p2d += dv * (1.0-d)
                hit = common_utilities.ray_cast_region2d(region, r3d, p2d, self.obj, settings)[1]
                if hit[2] == -1: return p3d
                return mx * hit[0]
                
                return pts[0]
            
            vertices = self.dest_bme.verts
            for i_v,c,d in self.tweak_data['lmverts']:
                nc = update(c,d)
                vertices[i_v].co = imx * nc
                #print('update_edit_mesh')
                
            
            if bpy.context.mode == 'EDIT_MESH':
                bmesh.update_edit_mesh(self.dest_obj.data, tessface=True, destructive=False)
            
            
            if eventd['release'] in self.keymap['action']:
                for u in self.tweak_data['supdate']:
                   u.update()
                for u in self.tweak_data['supdate']:
                   u.update_visibility(eventd['r3d'])
                self.tweak_data = None
        
    
                
        return ''
    
    def modal_tweak_relax_tool(self, context, eventd):
        print('modal_tweak_relax_tool not implemented')
        return 'main'
        
        if eventd['release'] == 'SHIFT+T':
            return 'main'
        
        settings = common_utilities.get_settings()
        region = eventd['region']
        r3d = eventd['r3d']
        
        if eventd['press'] in self.keymap['action']:
            self.modal_tweak_setup(context, eventd, max_dist=2.0)
            return ''
        
        if (eventd['type'] == 'MOUSEMOVE' and self.tweak_data) or eventd['release'] == 'LEFTMOUSE':
            cx,cy = eventd['mouse']
            
            mx = self.tweak_data['mx']
            mx3x3 = self.tweak_data['mx3x3']
            imx = self.tweak_data['imx']
            
            def update(p3d, d):
                if d >= 1.0: return p3d
                p2d = location_3d_to_region_2d(region, r3d, p3d)
                p2d += dv * (1.0-d)
                hit = common_utilities.ray_cast_region2d(region, r3d, p2d, self.obj, settings)[1]
                if hit[2] == -1: return p3d
                return mx * hit[0]
                
                return pts[0]
            
            vertices = self.dest_bme.verts
            for i_v,c,d in self.tweak_data['lmverts']:
                nc = update(c,d)
                vertices[i_v].co = imx * nc
                print('update_edit_mesh')
            
            for gv,ic,c,d in self.tweak_data['lgvextmove']:
                if ic == 0:
                    gv.corner0 = update(c,d)
                    #vertices[gv.corner0_ind].co = imx*gv.corner0
                elif ic == 1:
                    gv.corner1 = update(c,d)
                    #vertices[gv.corner1_ind].co = imx*gv.corner1
                elif ic == 2:
                    gv.corner2 = update(c,d)
                    #vertices[gv.corner2_ind].co = imx*gv.corner2
                elif ic == 3:
                    gv.corner3 = update(c,d)
                    #vertices[gv.corner3_ind].co = imx*gv.corner3
            
            bmesh.update_edit_mesh(self.dest_obj.data, tessface=True, destructive=False)
            
            for gv,ic,c,d in self.tweak_data['lgvmove']:
                if ic == 0:
                    gv.corner0 = update(c,d)
                elif ic == 1:
                    gv.corner1 = update(c,d)
                elif ic == 2:
                    gv.corner2 = update(c,d)
                elif ic == 3:
                    gv.corner3 = update(c,d)
            
            for gv,ic,c0,d0,c1,d1 in self.tweak_data['lgemove']:
                nc0 = update(c0,d0)
                nc1 = update(c1,d1)
                gv.position = (nc0+nc1)/2.0
                gv.tangent_y = (nc0-nc1).normalized()
                gv.radius = (nc0-nc1).length / 2.0
            
            for gp,i0,i1,c,d in self.tweak_data['lgpmove']:
                nc = update(c,d)
                gp.pts = [(_0,_1,_p) if _0!=i0 or _1!=i1 else (_0,_1,nc) for _0,_1,_p in gp.pts]
                gp.map_pts[(i0,i1)] = nc
                
            
            if eventd['release'] in self.keymap['action']:
                for u in self.tweak_data['supdate']:
                   u.update()
                for u in self.tweak_data['supdate']:
                   u.update_visibility(eventd['r3d'])
                self.tweak_data = None
        
        return ''
    
    ##############################
    # tools
    
    def ready_tool(self, eventd, tool_fn):
        rgn   = eventd['context'].region
        r3d   = eventd['context'].space_data.region_3d
        mx,my = eventd['mouse']
        cx,cy = mx-100,my
        rad   = math.sqrt((mx-cx)**2 + (my-cy)**2)

        self.action_center = (cx,cy)
        self.mode_start    = (mx,my)
        self.action_radius = rad
        self.mode_radius   = rad
        
        self.prev_pos      = (mx,my)

        # spc = bpy.data.window_managers['WinMan'].windows[0].screen.areas[4].spaces[0]
        # r3d = spc.region_3d
        vrot = r3d.view_rotation
        self.tool_x = (vrot * Vector((1,0,0))).normalized()
        self.tool_y = (vrot * Vector((0,1,0))).normalized()

        self.tool_rot = 0.0

        self.tool_fn = tool_fn
        self.tool_fn('init', eventd)

    def scale_brush_pixel_radius(self,command, eventd):
        if command == 'init':
            self.footer = 'Scale Brush Pixel Size'
            self.tool_data = self.stroke_radius
            x,y = eventd['mouse']
            self.sketch_brush.brush_pix_size_init(eventd['context'], x, y)
        elif command == 'commit':
            self.sketch_brush.brush_pix_size_confirm(eventd['context'])
            if self.sketch_brush.world_width:
                self.stroke_radius = self.sketch_brush.world_width
        elif command == 'undo':
            self.sketch_brush.brush_pix_size_cancel(eventd['context'])
            self.stroke_radius = self.tool_data
        else:
            x,y = command
            self.sketch_brush.brush_pix_size_interact(x, y, precise = eventd['shift'])
    
    def modal_scale_brush_pixel_tool(self, context, eventd):
        '''
        This is the pixel brush radius
        self.tool_fn is expected to be self.
        '''
        mx,my = eventd['mouse']

        if eventd['press'] in {'RET','NUMPAD_ENTER','LEFTMOUSE'}:
            self.tool_fn('commit', eventd)
            return 'main'

        if eventd['press'] in {'ESC', 'RIGHTMOUSE'}:
            self.tool_fn('undo', eventd)

            return 'main'

        if eventd['type'] == 'MOUSEMOVE':
            '''
            '''
            self.tool_fn((mx,my), eventd)

            return ''

        return ''
    
