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
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix
import math


class Polystrips_UI_Tools:
    
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
            
            if settings.symmetry_plane == 'x':
                while p3d:
                    next_i_p = len(p3d)
                    for i_p,p in enumerate(p3d):
                        if p[0].x < 0.0:
                            next_i_p = i_p
                            break
                    self.polystrips.insert_gedge_from_stroke(p3d[:next_i_p], False)
                    p3d = p3d[next_i_p:]
                    next_i_p = len(p3d)
                    for i_p,p in enumerate(p3d):
                        if p[0].x >= 0.0:
                            next_i_p = i_p
                            break
                    p3d = p3d[next_i_p:]
            else:
                self.polystrips.insert_gedge_from_stroke(p3d, False)
            
            self.polystrips.remove_unconnected_gverts()
            self.polystrips.update_visibility(eventd['r3d'])

            self.act_gvert = None
            self.act_gedge = None
            self.act_gpatch = None
            self.sel_gedges = set()
            self.sel_gverts = set()

            return 'main'

        return ''
    
    
    
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
        
        for gv in self.polystrips.gverts:
            lcorners = gv.get_corners()
            ld = [(c-hit_p3d).length / self.stroke_radius for c in lcorners]
            if not any(d < max_dist for d in ld):
                continue
            gv.freeze()
            lgvmove += [(gv,ic,c,d) for ic,c,d in zip([0,1,2,3], lcorners, ld) if d < max_dist]
            supdate.add(gv)
            for ge in gv.get_gedges_notnone():
                supdate.add(ge)
                for gp in ge.gpatches:
                    supdate.add(gp)
        
        for gv in self.polystrips.extension_geometry:
            lcorners = gv.get_corners()
            ld = [(c-hit_p3d).length / self.stroke_radius for c in lcorners]
            if not any(d < max_dist for d in ld):
                continue
            lgvextmove += [(gv,ic,c,d) for ic,c,d in zip([0,1,2,3], lcorners, ld) if d < max_dist]
        
        for ge in self.polystrips.gedges:
            for i,gv in ge.iter_igverts():
                p0 = gv.position+gv.tangent_y*gv.radius
                p1 = gv.position-gv.tangent_y*gv.radius
                d0 = (p0-hit_p3d).length / self.stroke_radius
                d1 = (p1-hit_p3d).length / self.stroke_radius
                if d0 >= max_dist and d1 >= max_dist: continue
                ge.freeze()
                lgemove += [(gv,i,p0,d0,p1,d1)]
                supdate.add(ge)
                supdate.add(ge.gvert0)
                supdate.add(ge.gvert3)
                for gp in ge.gpatches:
                    supdate.add(gp)
        
        for gp in self.polystrips.gpatches:
            freeze = False
            for i_pt,pt in enumerate(gp.pts):
                p,_,_ = pt
                d = (p-hit_p3d).length / self.stroke_radius
                if d >= max_dist: continue
                freeze = True
                lgpmove += [(gp,i_pt,p,d)]
            if not freeze: continue
            gp.freeze()
            supdate.add(gp)
            
        
        self.tweak_data = {
            'mouse': eventd['mouse'],
            'lgvmove': lgvmove,
            'lgvextmove': lgvextmove,
            'lgemove': lgemove,
            'lgpmove': lgpmove,
            'lmverts': lmverts,
            'supdate': supdate,
            'mx': mx,
            'mx3x3': mx3x3,
            'imx': imx,
        }
        
    
    def modal_tweak_move_tool(self, context, eventd):
        if eventd['release'] == 'T':
            return 'main'
        
        settings = common_utilities.get_settings()
        region = eventd['region']
        r3d = eventd['r3d']
        
        if eventd['press'] == 'LEFTMOUSE':
            self.modal_tweak_setup(eventd)
            return ''
        
        if (eventd['type'] == 'MOUSEMOVE' and self.tweak_data) or eventd['release'] == 'LEFTMOUSE':
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
            if bpy.context.mode == 'EDIT_MESH':
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
            
            for gp,i_pt,c,d in self.tweak_data['lgpmove']:
                p,v,k = gp.pts[i_pt]
                nc = update(c,d)
                gp.pts[i_pt] = (nc,v,k)
            
            if eventd['release'] == 'LEFTMOUSE':
                for u in self.tweak_data['supdate']:
                   u.update()
                for u in self.tweak_data['supdate']:
                   u.update_visibility(eventd['r3d'])
                self.tweak_data = None
        
    
                
        return ''
    
    def modal_tweak_relax_tool(self, context, eventd):
        if eventd['release'] == 'SHIFT+T':
            return 'main'
        
        settings = common_utilities.get_settings()
        region = eventd['region']
        r3d = eventd['r3d']
        
        if eventd['press'] == 'LEFTMOUSE':
            modal_tweak_setup(self, eventd, max_dist=2.0)
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
                
            
            if eventd['release'] == 'LEFTMOUSE':
                for u in self.tweak_data['supdate']:
                   u.update()
                for u in self.tweak_data['supdate']:
                   u.update_visibility(eventd['r3d'])
                self.tweak_data = None
        
        return ''
    
    def modal_scale_tool(self, context, eventd):
        cx,cy = self.action_center
        mx,my = eventd['mouse']
        ar = self.action_radius
        pr = self.mode_radius
        cr = math.sqrt((mx-cx)**2 + (my-cy)**2)

        if eventd['press'] in {'RET','NUMPAD_ENTER','LEFTMOUSE'}:
            self.tool_fn('commit', eventd)
            return 'main'

        if eventd['press'] in {'ESC', 'RIGHTMOUSE'}:
            self.tool_fn('undo', eventd)
            return 'main'

        if eventd['type'] == 'MOUSEMOVE':
            self.tool_fn(cr / pr, eventd)
            self.mode_radius = cr
            return ''

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

    def modal_rotate_tool(self, context, eventd):
        cx,cy = self.action_center
        mx,my = eventd['mouse']
        px,py = self.prev_pos #mode_pos

        if eventd['press'] in {'RET', 'NUMPAD_ENTER', 'LEFTMOUSE'}:
            self.tool_fn('commit', eventd)
            return 'main'

        if eventd['press'] in {'ESC', 'RIGHTMOUSE'}:
            self.tool_fn('undo', eventd)
            return 'main'

        if eventd['type'] == 'MOUSEMOVE':
            vp = Vector((px-cx,py-cy,0))
            vm = Vector((mx-cx,my-cy,0))
            ang = vp.angle(vm) * (-1 if vp.cross(vm).z<0 else 1)
            self.tool_rot += ang
            self.tool_fn(self.tool_rot, eventd)
            self.prev_pos = (mx,my)
            return ''

        return ''

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
    
    
    ##############################
    # tools
    
    def ready_tool(self, eventd, tool_fn):
        rgn   = eventd['context'].region
        r3d   = eventd['context'].space_data.region_3d
        mx,my = eventd['mouse']
        if self.act_gvert:
            loc   = self.act_gvert.position
            cx,cy = location_3d_to_region_2d(rgn, r3d, loc)
        elif self.act_gedge:
            loc   = (self.act_gedge.gvert0.position + self.act_gedge.gvert3.position) / 2.0
            cx,cy = location_3d_to_region_2d(rgn, r3d, loc)
        else:
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

    def grab_tool_gvert_list(self, command, eventd, lgv):
        '''
        translates list of gverts
        note: translation is relative to first gvert
        '''

        def l3dr2d(p): return location_3d_to_region_2d(eventd['region'], eventd['r3d'], p)

        if command == 'init':
            self.footer = 'Translating GVert position(s)'
            s2d = l3dr2d(lgv[0].position)
            self.tool_data = [(gv, Vector(gv.position), l3dr2d(gv.position)-s2d) for gv in lgv]
        elif command == 'commit':
            pass
        elif command == 'undo':
            for gv,p,_ in self.tool_data: gv.position = p
            for gv,_,_ in self.tool_data:
                gv.update()
                gv.update_visibility(eventd['r3d'], update_gedges=True)
        else:
            factor_slow,factor_fast = 0.2,1.0
            dv = Vector(command) * (factor_slow if eventd['shift'] else factor_fast)
            s2d = l3dr2d(self.tool_data[0][0].position)
            lgv2d = [s2d+relp+dv for _,_,relp in self.tool_data]
            pts = common_utilities.ray_cast_path(eventd['context'], self.obj, lgv2d)
            if len(pts) != len(lgv2d): return ''
            for d,p2d in zip(self.tool_data, pts):
                d[0].position = p2d
            for gv,_,_ in self.tool_data:
                gv.update()
                gv.update_visibility(eventd['r3d'], update_gedges=True)

    def grab_tool_gvert(self, command, eventd):
        '''
        translates selected gvert
        '''
        if command == 'init':
            lgv = [self.act_gvert]
        else:
            lgv = None
        self.grab_tool_gvert_list(command, eventd, lgv)

    def grab_tool_gvert_neighbors(self, command, eventd):
        '''
        translates selected gvert and its neighbors
        note: translation is relative to selected gvert
        '''
        if command == 'init':
            sgv = self.act_gvert
            lgv = [sgv] + [ge.get_inner_gvert_at(sgv) for ge in sgv.get_gedges_notnone()]
        else:
            lgv = None
        self.grab_tool_gvert_list(command, eventd, lgv)

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

