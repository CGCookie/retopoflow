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
import time
from random import randint

from ..lib import common_utilities
from ..lib.common_utilities import bversion, get_object_length_scale, dprint, frange, selection_mouse, showErrorMessage
from ..lib.classes.profiler.profiler import profiler

from ..cache import mesh_cache
from .patch_widget import PatchEditorWidget

class EdgePatches_UI_ModalWait():
    def modal_wait(self, context, eventd):
        settings = common_utilities.get_settings()

        self.footer = 'LMB: draw, RMB: select, G: grab, R: rotate, S: scale, F: brush size, K: knife, M: merge, X: delete, CTRL+D: dissolve, SHIFT+Wheel Up/Down or SHIFT+ +/-: adjust segments, CTRL+C: change selected junction type'

        if eventd['type'] == 'TIMER':
            if len(self.edgepatches.eppatches):
                self.edgepatches.solve_next()
            return ''
            
        ########################################
        # accept / cancel
        if eventd['press'] in self.keymap['help']:
            if  self.help_box.is_collapsed:
                self.help_box.uncollapse()
            else:
                self.help_box.collapse()
            self.help_box.snap_to_corner(eventd['context'],corner = [1,1])
        
        if eventd['press'] in self.keymap['confirm']:
            #self.create_mesh(eventd['context'])
            eventd['context'].area.header_text_set()
            return 'finish'

        if eventd['press'] in self.keymap['cancel']:
            eventd['context'].area.header_text_set()
            return 'cancel'
        
        if eventd['press'] in self.keymap['undo']:
            print('CGC_EdgePatches.undo_action not implemented')
            #self.undo_action()
            return ''

        if eventd['press'] == 'Q':                                                  # profiler printout
            profiler.printout()
            return ''

        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering
            #update brush and brush size
            x,y = eventd['mouse']
            self.sketch_brush.update_mouse_move_hover(eventd['context'], x,y)
            self.sketch_brush.make_circles()
            self.sketch_brush.get_brush_world_size(eventd['context'])
            if self.sketch_brush.world_width:
                self.stroke_radius = self.sketch_brush.world_width
                self.stroke_radius_pressure = self.sketch_brush.world_width
            self.help_box.hover(x, y)

        if eventd['press'] in self.keymap['brush size']:
            self.ready_tool(eventd, self.scale_brush_pixel_radius)
            return 'brush scale tool'

        # Selecting and Sketching
        ## if LMB is set to select, selecting happens in def modal_sketching
        if eventd['press'] in {'LEFTMOUSE', 'SHIFT+LEFTMOUSE', 'CTRL+LEFTMOUSE'}:
            if self.help_box.is_hovered:
                if  self.help_box.is_collapsed:
                    self.help_box.uncollapse()
                else:
                    self.help_box.collapse()
                self.help_box.snap_to_corner(eventd['context'],corner = [1,1])
                return ''
            
            #self.create_undo_snapshot('sketch')
            # start sketching
            self.footer = 'Sketching'
            x,y = eventd['mouse']

            #if settings.use_pressure:
            #    p = eventd['pressure']
            #    r = eventd['mradius']
            #else:
            #    p = 1
            #    r = self.stroke_radius
            p = 1
            r = self.stroke_radius
            self.sketch_curpos = (x,y)
            self.sketch = [((x,y),r)]
            
            return 'sketch'

        # If RMB is set to select, select as normal
        if eventd['press'] in {'RIGHTMOUSE', 'SHIFT+RIGHTMOUSE'}:
            if 'LEFTMOUSE' not in selection_mouse():
                self.pick(eventd)
                if self.patch_widget != None:
                    x, y = eventd['mouse']
                    print(self.patch_widget.pick(eventd['context'], x, y))
            return ''

        if self.act_epvert:
            if eventd['press'] in self.keymap['merge']:
                if self.act_epvert.is_inner():
                    showErrorMessage('Cannot merge inner EPVert')
                    return ''
                x,y = eventd['mouse']
                #pts = common_utilities.ray_cast_path(eventd['context'], self.obj_orig, [(x,y)])
                pts = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'],self.mx, [(x,y)])
                if not pts: return ''
                pt = pts[0]
                
                sel_epe = set(self.act_epvert.epedges)
                for epv,_ in self.edgepatches.pick_epverts(pt, maxdist=self.stroke_radius):
                    if epv.is_inner(): continue
                    if epv == self.act_epvert: continue
                    if any(epe in sel_epe for epe in epv.epedges): continue
                    self.create_undo_snapshot('merge')
                    self.edgepatches.merge_epverts(self.act_epvert, epv)
                    self.act_epvert = epv
                    self.edgepatches.smart_update_eppatches_network()
                    break
                return ''

            if eventd['press'] in self.keymap['translate']:
                if self.act_epvert.from_bmesh: return ''
                self.create_undo_snapshot('grab')
                self.ready_tool(eventd, self.grab_tool_epvert_neighbors)
                return 'grab tool'

            if eventd['press'] in self.keymap['rotate'] and not self.act_epvert.is_inner():
                if self.act_epvert.from_bmesh: return ''
                self.create_undo_snapshot('rotate')
                self.ready_tool(eventd, self.rotate_tool_epvert_neighbors)
                return 'rotate tool'

            if eventd['press'] in self.keymap['scale handles'] and not self.act_epvert.is_inner():
                if self.act_epvert.from_bmesh: return ''
                self.create_undo_snapshot('scale')
                self.ready_tool(eventd, self.scale_tool_epvert)
                return 'scale tool'

            if eventd['press'] in self.keymap['delete']:
                if self.act_epvert.is_inner(): return ''
                elif self.act_epvert.from_bmesh: return ''
                self.create_undo_snapshot('delete')
                self.edgepatches.disconnect_epvert(self.act_epvert)
                self.act_epvert = None
                self.edgepatches.remove_unconnected_epverts()
                return ''
            
            if eventd['press'] in self.keymap['dissolve']:
                if self.act_epvert.is_inner():
                    showErrorMessage('Cannot dissolve inner EPVert')
                    return ''
                if len(self.act_epvert.epedges) != 2:
                    showErrorMessage('Cannot dissolve EPVert that is not connected to exactly 2 EPEdges')
                    return ''
                self.create_undo_snapshot('dissolve')
                self.edgepatches.dissolve_epvert(self.act_epvert)
                self.act_epvert = None
                self.edgepatches.remove_unconnected_epverts()
                self.edgepatches.smart_update_eppatches_network()
                return ''
            
            #this ...rips a single EPV apart?
            if eventd['press'] in self.keymap['knife'] and not self.act_epvert.is_inner():
                x,y = eventd['mouse']
                #pts = common_utilities.ray_cast_path(eventd['context'], self.obj_orig, [(x,y)])
                pts = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'],self.mx, [(x,y)])
                if not pts: return ''
                pt = pts[0]
                
                for epe,_ in self.edgepatches.pick_epedges(pt, maxdist=self.stroke_radius):
                    if epe.has_epvert(self.act_epvert): continue
                    self.create_undo_snapshot('knife')
                    t,_ = epe.get_closest_point(pts[0])
                    _,_,epv = self.edgepatches.split_epedge_at_t(epe, t, connect_epvert=self.act_epvert)
                    self.act_epedge = None
                    self.sel_epedges.clear()
                    self.act_epvert = epv
                    self.act_epvert = epv
                    self.edgepatches.smart_update_eppatches_network()
                    return ''
                return ''
        
        if self.act_epedge:
            if eventd['press'] in self.keymap['delete']:
                self.create_undo_snapshot('delete')
                self.edgepatches.disconnect_epedge(self.act_epedge)
                self.act_epedge = None
                self.edgepatches.remove_unconnected_epverts()
                self.edgepatches.smart_update_eppatches_network()
                return ''
            
            if eventd['press'] in self.keymap['knife']:
                self.create_undo_snapshot('knife')
                x,y = eventd['mouse']
                #pts = common_utilities.ray_cast_path(eventd['context'], self.obj_orig, [(x,y)])
                pts = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'],self.mx, [(x,y)])
                if not pts: return ''
                
                _,_,epv = self.edgepatches.split_epedge_at_pt(self.act_epedge, pts[0], connect_epvert = None)
                self.act_epedge = None
                self.sel_epedges.clear()
                self.act_epvert = epv
                self.act_epvert = epv
                self.edgepatches.smart_update_eppatches_network()
                return ''

            if eventd['press'] in self.keymap['up count']:
                if self.act_epedge.from_bmesh: return ''
                self.act_epedge.subdivision += 1
                self.act_epedge.update(shape = False, subdiv = True, patches = False)
                self.edgepatches.smart_update_eppatches_network()
                return ''
            if eventd['press'] in self.keymap['dn count']:
                if self.act_epedge.from_bmesh: return ''
                cur_sub = self.act_epedge.subdivision
                self.act_epedge.subdivision = max(2, cur_sub-1)
                self.act_epedge.update(shape = False, subdiv = True, patches = False)
                self.edgepatches.smart_update_eppatches_network()
                return ''
        if eventd['press'] in {'p','P'}:
            
            print('Edge patches updating was ' + str(self.edgepatches.live))
            new_live = self.edgepatches.live != True
            self.edgepatches.live = new_live
            print('Edge patches updating is now ' + str(self.edgepatches.live))
            
            for i, ep in enumerate(self.edgepatches.eppatches):
                print('patch %i is now live' % i)
                print(new_live)
                ep.live = new_live
            
            self.edgepatches.smart_update_eppatches_network()
            #self.edgepatches.debug()
            return ''
        
        if self.act_eppatch:
            if eventd['press'] in {'TAB'}:
                #if self.patch_widget != None:
                    #del self.patch_widget
                    #self.patch_widget = None
                #else:
                self.patch_widget = PatchEditorWidget(self.act_eppatch)
                self.patch_widget.p_locs_get()
                self.patch_widget.pole_inds_get()
                self.patch_widget.valid_patterns_get()
                return 'widget'
            
            if eventd['press'] in {'L'}:
                self.act_eppatch.ILP_initial_solve()
                #sleep needed?
                #time.sleep(2)
                print('about to request info from ILP')
                return ''
    
            elif eventd['press'] in {'G'}:
                self.act_eppatch.generate_geometry()
                return ''

            elif eventd['press'] in {'M'}:
                self.act_eppatch.mirror_solution()
                return ''
            elif eventd['press'] in {'RIGHT_ARROW'}:
                self.act_eppatch.rotate_solution(1)
                return ''
            elif eventd['press'] in {'LEFT_ARROW'}:
                self.act_eppatch.rotate_solution(-1)
                return ''
            elif eventd['press'] in {'Z'}:
                unique_patterns = list(set(self.act_eppatch.patch.valid_patterns))
                n = randint(0,len(unique_patterns)-1)
                m = unique_patterns[n]
                self.act_eppatch.change_pattern(m)
                return ''
            
            elif eventd['press'] in {'A'}:
                print('change adjust variable')
                n = self.act_eppatch.patch.param_index
                N = len(self.act_eppatch.patch.get_active_solution_variables())
                
                new_index = (n + 1) % N
                
                self.act_eppatch.patch.param_index = new_index
                self.act_eppatch.patch.delta = 0
                name = self.act_eppatch.patch.get_adjust_variable_name()
                print('adjust parameter %s' % name)
            
            elif eventd['press'] in {'UP_ARROW'}:
                self.act_eppatch.patch.delta += 1
                if self.act_eppatch.patch.adjust_patch():
                    self.act_eppatch.patch.delta = 0
                    self.act_eppatch.generate_geometry()
                    return ''
                
            elif eventd['press'] in {'DOWN_ARROW'}:
                self.act_eppatch.patch.delta -= 1
                if self.act_eppatch.patch.adjust_patch():
                    self.act_eppatch.patch.delta = 0
                    self.act_eppatch.generate_geometry()
                    return ''
                
            elif eventd['press'] in {'J'}:
                n = randint(0,5)
                self.act_eppatch.relax_patch()
                self.act_eppatch.bmesh_to_patch()
            
            elif eventd['press'] in {'R'}:
                self.act_eppatch.patch.report()
                return ''
            
            elif eventd['press'] in {'T'}:
                self.create_undo_snapshot('t_junction')
                x,y = eventd['mouse']
                self.sketch_brush.get_brush_world_size(eventd['context'])
                if not self.sketch_brush.world_width: return ''
                #pts = common_utilities.ray_cast_path(eventd['context'], self.obj_orig, [(x,y)])
                pts = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'],self.mx, [(x,y)])
                if not pts: return ''
                
                epv = self.edgepatches.toggle_t(self.act_eppatch, pts[0], self.sketch_brush.world_width)
                self.edgepatches.smart_update_eppatches_network()
                
                return ''
            
        return ''