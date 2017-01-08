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
from ..lib.common_utilities import bversion, get_object_length_scale, dprint, frange, selection_mouse, showErrorMessage
from ..lib.common_utilities import invert_matrix, matrix_normal
from ..lib.classes.profiler import profiler
from ..cache import mesh_cache

class Tweak_UI_Tools():
    
    ##############################
    # modal tool functions
    
    def modal_tweak_setup(self, context, eventd, max_dist=1.0):
        self.tweak_data = None
        
        rgn,r3d,mx = eventd['region'],eventd['r3d'],self.mx
        
        hit_p3d,_ = self.src_bmc.raycast_screen(eventd['mouse'], rgn, r3d)
        if not hit_p3d: return
        
        lmverts = [(i_mv, mx*mv.co, (mx*mv.co-hit_p3d).length / self.stroke_radius) for i_mv,mv in enumerate(self.dest_bme.verts)]
        lmverts = [(i,p,d) for i,p,d in lmverts if d <= max_dist]
        if lmverts:
            self.tweak_data = {
                'mouse': eventd['mouse'],
                'lmverts': lmverts,
            }
        
    
    def modal_tweak_move_tool(self, context, eventd):
        if eventd['release'] in self.keymap['action']:
            return 'main'
        
        rgn,r3d = eventd['region'],eventd['r3d']
        
        if eventd['type'] == 'MOUSEMOVE' and self.tweak_data:
            cx,cy = eventd['mouse']
            lx,ly = self.tweak_data['mouse']
            dx,dy = cx-lx,cy-ly
            dv = Vector((dx,dy))
            
            imx = self.imx
            
            def update(p3d, d):
                if d >= 1.0: return p3d
                p2d = location_3d_to_region_2d(rgn, r3d, p3d)
                p2d += dv * (1.0-d)
                hit_p3d,_ = self.src_bmc.raycast_screen(p2d, rgn, r3d)
                return hit_p3d or p3d
            
            vertices = self.dest_bme.verts
            for i_v,c,d in self.tweak_data['lmverts']:
                nc = update(c,d)
                vertices[i_v].co = imx * nc
                
            
            bmesh.update_edit_mesh(self.dest_obj.data, tessface=True, destructive=False)
            self.tar_bmeshrender.dirty()
             
        return ''
    
    def modal_tweak_relax_tool(self, context, eventd):
        if eventd['release'] in self.keymap['tweak tool relax']:
            self.undo_stopRepeated('relax')
            return 'main'
        
        self.create_undo_snapshot('relax')
        
        self.modal_tweak_setup(context, eventd, max_dist=1.0)
        if not self.tweak_data: return ''
        
        lmverts = self.tweak_data['lmverts']
        bmverts = self.dest_bme.verts
        
        avgDist = 0.0
        avgCount = 0
        divco = dict()
        
        mx,imx = self.mx,self.imx
        
        # collect data for smoothing
        for i,v,d in lmverts:
            bmv0 = bmverts[i]
            lbme,lbmf = bmv0.link_edges, bmv0.link_faces
            avgDist += sum(bme.calc_length() for bme in lbme)
            avgCount += len(lbme)
            divco[i] = bmv0.co
            for bme in lbme:
                bmv1 = bme.other_vert(bmv0)
                divco[bmv1.index] = bmv1.co
            for bmf in lbmf:
                for bmv in bmf.verts:
                    divco[bmv.index] = bmv.co
        
        # bail if no data to smooth
        if avgCount == 0: return ''
        
        avgDist /= avgCount
        
        # perform smoothing
        for i,v,d in lmverts:
            bmv0 = bmverts[i]
            lbme,lbmf = bmv0.link_edges, bmv0.link_faces
            if not lbme: continue
            for bme in bmv0.link_edges:
                bmv1 = bme.other_vert(bmv0)
                diff = (bmv1.co - bmv0.co)
                m = (avgDist - diff.length) * (1.0 - d) * 0.1
                divco[bmv1.index] += diff * m
            for bmf in lbmf:
                cnt = len(bmf.verts)
                ctr = sum([bmv.co for bmv in bmf.verts], Vector((0,0,0))) / cnt
                fd = sum((ctr-bmv.co).length for bmv in bmf.verts) / cnt
                for bmv in bmf.verts:
                    diff = (bmv.co - ctr)
                    m = (fd - diff.length)* (1.0- d) / cnt
                    divco[bmv.index] += diff * m
        
        # update
        for i,co in divco.items():
            bmverts[i].co = imx * self.src_bmc.find_nearest(mx * co)[0]

        bmesh.update_edit_mesh(self.dest_obj.data, tessface=True, destructive=False)
        self.tar_bmeshrender.dirty()
        

    
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

        if eventd['press'] in {'RET','NUMPAD_ENTER','LEFTMOUSE'}:
            self.tool_fn('commit', eventd)
            return 'main'

        if eventd['press'] in {'ESC', 'RIGHTMOUSE'}:
            self.tool_fn('undo', eventd)
            return 'main'

        if eventd['type'] == 'MOUSEMOVE':
            mx,my = eventd['mouse']
            self.tool_fn((mx,my), eventd)
            return ''

        return ''
    
