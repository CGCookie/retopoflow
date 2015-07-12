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


class EdgePatches_UI_Tools:
    def modal_sketching(self, context, eventd):
        settings = common_utilities.get_settings()

        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            if settings.use_pressure:
                p = eventd['pressure']
                r = eventd['mradius']
            else:
                p = 1
                r = self.stroke_radius

            stroke_point = self.sketch[-1]

            (lx, ly) = stroke_point[0]
            lr = stroke_point[1]
            self.sketch_curpos = (x,y)
            self.sketch_pressure = p

            ss0,ss1 = self.stroke_smoothing,1-self.stroke_smoothing
            # Smooth radii
            self.stroke_radius_pressure = lr*ss0 + r*ss1
            if settings.use_pressure:
                self.sketch += [((lx*ss0+x*ss1, ly*ss0+y*ss1), self.stroke_radius_pressure)]
            else:
                self.sketch += [((lx*ss0+x*ss1, ly*ss0+y*ss1), self.stroke_radius)]

            return ''

        if eventd['release'] in {'LEFTMOUSE','SHIFT+LEFTMOUSE', 'CTRL+LEFTMOUSE'}:
            # correct for 0 pressure on release
            if self.sketch[-1][1] == 0:
                self.sketch[-1] = self.sketch[-2]

            # if is selection mouse, check distance
            if 'LEFTMOUSE' in selection_mouse():
                dist_traveled = 0.0
                for s0,s1 in zip(self.sketch[:-1],self.sketch[1:]):
                    dist_traveled += (Vector(s0[0]) - Vector(s1[0])).length

                # user like ly picking, because distance traveled is very small
                if dist_traveled < 5.0:
                    self.pick(eventd)
                    self.sketch = []
                    return 'main'

            p3d = common_utilities.ray_cast_stroke(eventd['context'], self.obj, self.sketch) if len(self.sketch) > 1 else []
            if len(p3d) <= 1: return 'main'

            # tessellate stroke (if needed) so we have good stroke sampling
            # TODO, tesselate pressure/radius values?
            # length_tess = self.length_scale / 700
            # p3d = [(p0+(p1-p0).normalized()*x) for p0,p1 in zip(p3d[:-1],p3d[1:]) for x in frange(0,(p0-p1).length,length_tess)] + [p3d[-1]]
            # stroke = [(p,self.stroke_radius) for i,p in enumerate(p3d)]

            self.sketch = []
            
            lepv0 = self.edgepatches.pick_epverts(p3d[0][0], maxdist=self.stroke_radius, allowInner=False)
            lepv3 = self.edgepatches.pick_epverts(p3d[-1][0], maxdist=self.stroke_radius, allowInner=False)
            
            sepv0 = lepv0[0][0] if lepv0 else None
            sepv3 = lepv3[0][0] if lepv3 else None
            
            self.edgepatches.insert_epedge_from_stroke(p3d, sepv0=sepv0, sepv3=sepv3)
            
            #self.polystrips.remove_unconnected_gverts()
            #self.polystrips.update_visibility(eventd['r3d'])

            self.act_gvert = None
            self.act_gedge = None
            self.act_gpatch = None
            self.sel_gedges = set()
            self.sel_gverts = set()

            return 'main'

        return ''
    
    def modal_grab_tool(self, context, eventd):
        cx,cy = self.action_center
        mx,my = eventd['mouse']
        px,py = self.prev_pos #mode_pos
        sx,sy = self.mode_start

        if eventd['press'] in {'RET','NUMPAD_ENTER','LEFTMOUSE','SHIFT+RET','SHIFT+NUMPAD_ENTER','SHIFT+LEFTMOUSE'}:
            self.tool_fn('commit', eventd)
            return 'main'

        if eventd['press'] in {'ESC','RIGHTMOUSE'}:
            self.tool_fn('undo', eventd)
            return 'main'

        if eventd['type'] == 'MOUSEMOVE':
            self.tool_fn((mx-px,my-py), eventd)
            self.prev_pos = (mx,my)
            return ''

        return ''
    
    ##############################
    # tools
    
    def ready_tool(self, eventd, tool_fn):
        rgn   = eventd['context'].region
        r3d   = eventd['context'].space_data.region_3d
        mx,my = eventd['mouse']
        if self.act_epvert:
            loc   = self.act_epvert.position
            cx,cy = location_3d_to_region_2d(rgn, r3d, loc)
        elif self.act_epedge:
            loc   = (self.act_epedge.epvert0.position + self.act_epedge.epvert3.position) / 2.0
            cx,cy = location_3d_to_region_2d(rgn, r3d, loc)
        else:
            cx,cy = mx-100,my
        rad   = math.sqrt((mx-cx)**2 + (my-cy)**2)

        self.action_center = (cx,cy)
        self.mode_start    = (mx,my)
        self.action_radius = rad
        self.mode_radius   = rad
        
        self.prev_pos      = (mx,my)

        vrot = r3d.view_rotation
        self.tool_x = (vrot * Vector((1,0,0))).normalized()
        self.tool_y = (vrot * Vector((0,1,0))).normalized()

        self.tool_rot = 0.0

        self.tool_fn = tool_fn
        self.tool_fn('init', eventd)

    def scale_tool_gvert(self, command, eventd):
        if command == 'init':
            self.footer = 'Scaling GVerts'
            sgv = self.act_gvert
            lgv = [ge.gvert1 if ge.gvert0==sgv else ge.gvert2 for ge in sgv.get_gedges() if ge]
            self.tool_data = [(gv,Vector(gv.position)) for gv in lgv]
        elif command == 'commit':
            pass
        elif command == 'undo':
            for gv,p in self.tool_data:
                gv.position = p
                gv.update()
            self.act_gvert.update()
            self.act_gvert.update_visibility(eventd['r3d'], update_gedges=True)
        else:
            m = command
            sgv = self.act_gvert
            p = sgv.position
            for ge in sgv.get_gedges():
                if not ge: continue
                gv = ge.gvert1 if ge.gvert0 == self.act_gvert else ge.gvert2
                gv.position = p + (gv.position-p) * m
                gv.update()
            sgv.update()
            self.act_gvert.update_visibility(eventd['r3d'], update_gedges=True)

    def scale_tool_gvert_radius(self, command, eventd):
        if command == 'init':
            self.footer = 'Scaling GVert radius'
            self.tool_data = self.act_gvert.radius
        elif command == 'commit':
            pass
        elif command == 'undo':
            self.act_gvert.radius = self.tool_data
            self.act_gvert.update()
            self.act_gvert.update_visibility(eventd['r3d'], update_gedges=True)
        else:
            m = command
            self.act_gvert.radius *= m
            self.act_gvert.update()
            self.act_gvert.update_visibility(eventd['r3d'], update_gedges=True)

    def scale_tool_stroke_radius(self, command, eventd):
        if command == 'init':
            self.footer = 'Scaling Stroke radius'
            self.tool_data = self.stroke_radius
        elif command == 'commit':
            pass
        elif command == 'undo':
            self.stroke_radius = self.tool_data
        else:
            m = command
            self.stroke_radius *= m

    def grab_tool_epvert_list(self, command, eventd, lepv):
        '''
        translates list of epverts
        note: translation is relative to first epvert
        '''

        def l3dr2d(p): return location_3d_to_region_2d(eventd['region'], eventd['r3d'], p)

        if command == 'init':
            self.footer = 'Translating EPVert position(s)'
            s2d = l3dr2d(lepv[0].position)
            self.tool_data = [(epv, Vector(epv.position), l3dr2d(epv.position)-s2d) for epv in lepv]
        elif command == 'commit':
            #for epv,_,_ in self.tool_data:
            #    epv.update_gedges()
            pass
        elif command == 'undo':
            for epv,p,_ in self.tool_data: epv.position = p
            for epv,_,_ in self.tool_data:
                epv.update()
                #epv.update_visibility(eventd['r3d'], update_epedges=True)
        else:
            factor_slow,factor_fast = 0.2,1.0
            dv = Vector(command) * (factor_slow if eventd['shift'] else factor_fast)
            s2d = l3dr2d(self.tool_data[0][0].position)
            lgv2d = [s2d+relp+dv for _,_,relp in self.tool_data]
            pts = common_utilities.ray_cast_path(eventd['context'], self.obj, lgv2d)
            if len(pts) != len(lgv2d): return ''
            for d,p2d in zip(self.tool_data, pts):
                d[0].position = p2d
            for epv,_,_ in self.tool_data:
                epv.update()
                #epv.update_visibility(eventd['r3d'], update_gedges=True)

    def grab_tool_epvert(self, command, eventd):
        '''
        translates selected epvert
        '''
        if command == 'init':
            lepv = [self.act_epvert]
        else:
            lepv = None
        self.grab_tool_gvert_list(command, eventd, lgv)

    def grab_tool_epvert_neighbors(self, command, eventd):
        '''
        translates selected epvert and its neighbors
        note: translation is relative to selected epvert
        '''
        if command == 'init':
            sepv = self.act_epvert
            if sepv.is_inner():
                lepv = [sepv]
            else:
                lepv = [sepv] + [epe.get_inner_epvert_at(sepv) for epe in sepv.get_epedges()]
        else:
            lepv = None
        self.grab_tool_epvert_list(command, eventd, lepv)

    def grab_tool_gedge(self, command, eventd):
        if command == 'init':
            sge = self.act_gedge
            lgv = [sge.gvert0, sge.gvert3]
            lgv += [ge.get_inner_gvert_at(gv) for gv in lgv for ge in gv.get_gedges_notnone()]
        else:
            lgv = None
        self.grab_tool_gvert_list(command, eventd, lgv)

    def rotate_tool_gvert_neighbors(self, command, eventd):
        if command == 'init':
            self.footer = 'Rotating GVerts'
            self.tool_data = [(gv,Vector(gv.position)) for gv in self.act_gvert.get_inner_gverts()]
        elif command == 'commit':
            pass
        elif command == 'undo':
            for gv,p in self.tool_data:
                gv.position = p
                gv.update()
        else:
            ang = command
            q = Quaternion(self.act_gvert.snap_norm, ang)
            p = self.act_gvert.position
            for gv,up in self.tool_data:
                gv.position = p+q*(up-p)
                gv.update()

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

