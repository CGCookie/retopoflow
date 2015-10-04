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

from ..lib import common_utilities
from ..lib.common_utilities import bversion, get_object_length_scale, dprint, profiler, frange, selection_mouse, showErrorMessage
from ..cache import mesh_cache

class Polystrips_UI_ModalWait():
    def modal_wait(self, context, eventd):
        '''
        Place code here to handle commands issued by user
        Return string that corresponds to FSM key, used to change states.  For example:
        - '':     do not change state
        - 'main': transition to main state
        - 'nav':  transition to a navigation state (passing events through to 3D view)
        '''
        

        settings = common_utilities.get_settings()

        self.footer = 'LMB: draw, RMB: select, G: grab, R: rotate, S: scale, F: brush size, K: knife, M: merge, X: delete, CTRL+D: dissolve, SHIFT+Wheel Up/Down or SHIFT+ +/-: adjust segments, CTRL+C: change selected junction type'

        ########################################
        # accept / cancel
        if eventd['press'] in self.keymap['help']:
            if  self.help_box.is_collapsed:
                self.help_box.uncollapse()
            else:
                self.help_box.collapse()
            self.help_box.snap_to_corner(eventd['context'],corner = [1,1])
        if eventd['press'] in self.keymap['confirm']:
            self.create_mesh(eventd['context'])
            eventd['context'].area.header_text_set()
            return 'finish'

        if eventd['press'] in self.keymap['cancel']:
            eventd['context'].area.header_text_set()
            return 'cancel'

        #####################################
        # General

        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering
            #update brush and brush size
            x,y = eventd['mouse']
            self.sketch_brush.update_mouse_move_hover(eventd['context'], x,y)
            self.sketch_brush.make_circles()
            self.sketch_brush.get_brush_world_size(eventd['context'])

            if self.sketch_brush.world_width:
                self.stroke_radius = self.sketch_brush.world_width
                self.stroke_radius_pressure = self.sketch_brush.world_width

            self.hover_geom(eventd)

        if eventd['press'] in self.keymap['undo']:
            self.undo_action()
            return ''

        if eventd['press'] in self.keymap['brush size']:
            self.ready_tool(eventd, self.scale_brush_pixel_radius)
            return 'brush scale tool'

        if eventd['press'] == 'Q':                                                  # profiler printout
            profiler.printout()
            return ''

        if eventd['press'] == 'P':                                                  # grease pencil => strokes
            # TODO: only convert gpencil strokes that are visible and prevent duplicate conversion
            for gpl in self.obj_orig.grease_pencil.layers: gpl.hide = True
            for stroke in self.strokes_original:
                self.polystrips.insert_gedge_from_stroke(stroke, True)
            self.polystrips.remove_unconnected_gverts()
            self.polystrips.update_visibility(eventd['r3d'])
            return ''
        
        if eventd['press'] in self.keymap['tweak move']:
            self.create_undo_snapshot('tweak')
            self.footer = 'Tweak: ' + ('Moving' if eventd['press']=='T' else 'Relaxing')
            self.act_gvert = None
            self.act_gedge = None
            self.sel_gedges = set()
            self.act_gpatch = None
            return 'tweak move tool' if eventd['press']=='T' else 'tweak relax tool'
        
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
            
            self.create_undo_snapshot('sketch')
            # start sketching
            self.footer = 'Sketching'
            x,y = eventd['mouse']

            if settings.use_pressure:
                p = eventd['pressure']
                r = eventd['mradius']
            else:
                p = 1
                r = self.stroke_radius

            self.sketch_curpos = (x,y)

            if eventd['ctrl'] and self.act_gvert:
                # continue sketching from selected gvert position
                gvx,gvy = location_3d_to_region_2d(eventd['region'], eventd['r3d'], self.act_gvert.position)
                self.sketch = [((gvx,gvy),self.act_gvert.radius), ((x,y),r)]
            else:
                self.sketch = [((x,y),r)]
            
            return 'sketch'

        # If RMB is set to select, select as normal
        if eventd['press'] in {'RIGHTMOUSE', 'SHIFT+RIGHTMOUSE'}:
            if 'LEFTMOUSE' not in selection_mouse():
                # Select element
                self.pick(eventd)
            return ''

        if eventd['press'] in self.keymap['update']:
            self.create_undo_snapshot('update')
            for gv in self.polystrips.gverts:
                gv.update_gedges()

        if eventd['press'] in self.keymap['symmetry_x']:
            if self.settings.symmetry_plane == 'none':
                self.settings.symmetry_plane = 'x'
            else:
                self.settings.symmetry_plane = 'none'

        ###################################
        # Selected gpatch commands
        
        if self.act_gpatch:
            if eventd['press'] in self.keymap['delete']:
                self.create_undo_snapshot('delete')
                self.polystrips.disconnect_gpatch(self.act_gpatch)
                self.act_gpatch = None
                return ''
            if eventd['press'] in self.keymap['rotate pole']:
                reverse = eventd['press']=='SHIFT+R'
                self.act_gpatch.rotate_pole(reverse=reverse)
                self.polystrips.update_visibility(eventd['r3d'])
                return ''

        ###################################
        # Selected gedge commands
     
        if self.act_gedge:
            if eventd['press'] in self.keymap['delete']:
                self.create_undo_snapshot('delete')
                self.polystrips.disconnect_gedge(self.act_gedge)
                self.act_gedge = None
                self.sel_gedges.clear()
                self.polystrips.remove_unconnected_gverts()
                return ''

            if eventd['press'] in self.keymap['knife'] and not self.act_gedge.is_zippered() and not self.act_gedge.has_zippered() and not self.act_gedge.is_gpatched():
                self.create_undo_snapshot('knife')
                x,y = eventd['mouse']
                pts = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'], self.mx, [(x,y)])
                if not pts:
                    return ''
                t,_    = self.act_gedge.get_closest_point(pts[0])
                _,_,gv = self.polystrips.split_gedge_at_t(self.act_gedge, t)
                self.act_gedge = None
                self.sel_gedges.clear()
                self.act_gvert = gv
                self.act_gvert = gv
                return ''

            if eventd['press'] in self.keymap['update']:
                self.create_undo_snapshot('update')
                self.act_gedge.gvert0.update_gedges()
                self.act_gedge.gvert3.update_gedges()
                return ''

            if eventd['press'] in self.keymap['up count']:
                self.create_undo_snapshot('count')
                self.act_gedge.set_count(self.act_gedge.n_quads + 1)
                self.polystrips.update_visibility(eventd['r3d'])
                return ''

            if eventd['press'] in self.keymap['dn count']:

                if self.act_gedge.n_quads > 3:
                    self.create_undo_snapshot('count')
                    self.act_gedge.set_count(self.act_gedge.n_quads - 1)
                    self.polystrips.update_visibility(eventd['r3d'])
                return ''

            if eventd['press'] in self.keymap['zip'] and not self.act_gedge.is_gpatched():

                if self.act_gedge.zip_to_gedge:
                    self.create_undo_snapshot('unzip')
                    self.act_gedge.unzip()
                    return ''

                lge = self.act_gedge.gvert0.get_gedges_notnone() + self.act_gedge.gvert3.get_gedges_notnone()
                if any(ge.is_zippered() for ge in lge):
                    # prevent zippering a gedge with gvert that has a zippered gedge already
                    # TODO: allow this??
                    return ''

                x,y = eventd['mouse']
                pts = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'], self.mx, [(x,y)])
                if not pts:
                    return ''
                pt = pts[0]
                for ge in self.polystrips.gedges:
                    if ge == self.act_gedge: continue
                    if not ge.is_picked(pt): continue
                    self.create_undo_snapshot('zip')
                    self.act_gedge.zip_to(ge)
                    return ''
                return ''

            if eventd['press'] in self.keymap['translate']:
                if not self.act_gedge.is_zippered():
                    self.create_undo_snapshot('grab')
                    self.ready_tool(eventd, self.grab_tool_gedge)
                    return 'grab tool'
                return ''

            if eventd['press'] in self.keymap['select all']:
                self.act_gvert = self.act_gedge.gvert0
                self.act_gedge = None
                self.sel_gedges.clear()
                return ''

            if eventd['press'] in self.keymap['rip'] and not self.act_gedge.is_zippered():
                self.create_undo_snapshot('rip')
                self.act_gedge = self.polystrips.rip_gedge(self.act_gedge)
                self.sel_gedges = [self.act_gedge]
                self.ready_tool(eventd, self.grab_tool_gedge)
                return 'grab tool'

            if eventd['press'] in self.keymap['fill']:
                self.create_undo_snapshot('simplefill')
                self.fill(eventd)
                return ''

        ###################################
        # selected gvert commands

        if self.act_gvert:

            if eventd['press'] in self.keymap['knife']:
                if not self.act_gvert.is_endpoint():
                    showErrorMessage('Selected GVert must be endpoint (exactly one GEdge)')
                    return ''
                x,y = eventd['mouse']
                pts = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'], self.mx, [(x,y)])
                if not pts:
                    return ''
                pt = pts[0]
                for ge in self.polystrips.gedges:
                    if not ge.is_picked(pt): continue
                    if ge.is_zippered() or ge.is_gpatched():
                        showErrorMessage('Cannot knife a GEdge that is zippered or patched')
                        continue
                    self.create_undo_snapshot('split')
                    t,d = ge.get_closest_point(pt)
                    self.polystrips.split_gedge_at_t(ge, t, connect_gvert=self.act_gvert)
                    return ''
                return ''

            if eventd['press'] in self.keymap['delete']:
                if self.act_gvert.is_inner():
                    return ''
                self.create_undo_snapshot('delete')
                self.polystrips.disconnect_gvert(self.act_gvert)
                self.act_gvert = None
                self.polystrips.remove_unconnected_gverts()
                return ''

            if eventd['press'] in self.keymap['dissolve']:
                if any(ge.is_zippered() or ge.is_gpatched() for ge in self.act_gvert.get_gedges_notnone()):
                    showErrorMessage('Cannot dissolve GVert with GEdge that is zippered or patched')
                    return ''
                self.create_undo_snapshot('dissolve')
                self.polystrips.dissolve_gvert(self.act_gvert)
                self.act_gvert = None
                self.polystrips.remove_unconnected_gverts()
                self.polystrips.update_visibility(eventd['r3d'])
                return ''

            if eventd['press'] in self.keymap['scale'] and not self.act_gvert.is_unconnected():
                self.create_undo_snapshot('scale')
                self.ready_tool(eventd, self.scale_tool_gvert_radius)
                return 'scale tool'

            if eventd['press'] in self.keymap['translate']:
                self.create_undo_snapshot('grab')
                self.ready_tool(eventd, self.grab_tool_gvert_neighbors)
                return 'grab tool'

            if eventd['press'] in self.keymap['change junction']:
                if any(ge.is_zippered() or ge.is_gpatched() for ge in self.act_gvert.get_gedges_notnone()):
                    showErrorMessage('Cannot change corner type of GVert with GEdge that is zippered or patched')
                    return ''
                self.create_undo_snapshot('toggle')
                self.act_gvert.toggle_corner()
                self.act_gvert.update_visibility(eventd['r3d'], update_gedges=True)
                return ''

            if eventd['press'] in self.keymap['scale handles'] and not self.act_gvert.is_unconnected():
                self.create_undo_snapshot('scale')
                self.ready_tool(eventd, self.scale_tool_gvert)
                return 'scale tool'

            if eventd['press'] in self.keymap['smooth']:
                self.create_undo_snapshot('smooth')
                self.act_gvert.smooth()
                self.act_gvert.update_visibility(eventd['r3d'], update_gedges=True)
                return ''

            if eventd['press'] in self.keymap['rotate']:
                self.create_undo_snapshot('rotate')
                self.ready_tool(eventd, self.rotate_tool_gvert_neighbors)
                return 'rotate tool'

            if eventd['press'] in self.keymap['update']:
                self.act_gvert.update_gedges()
                return ''

            if eventd['press'] in self.keymap['rip']:
                # self.polystrips.rip_gvert(self.act_gvert)
                # self.act_gvert = None
                # return ''
                if any(ge.is_zippered() or ge.is_gpatched() for ge in self.act_gvert.get_gedges_notnone()):
                    showErrorMessage('Cannot rip GVert with GEdge that is zippered or patched')
                    return ''
                x,y = eventd['mouse']
                pts = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'], self.mx, [(x,y)])
                if not pts:
                    return ''
                pt = pts[0]
                for ge in self.act_gvert.get_gedges_notnone():
                    if not ge.is_picked(pt): continue
                    self.create_undo_snapshot('rip')
                    self.act_gvert = self.polystrips.rip_gedge(ge, at_gvert=self.act_gvert)
                    self.ready_tool(eventd, self.grab_tool_gvert_neighbors)
                    return 'grab tool'
                showErrorMessage('Must hover over GEdge you wish to rip')
                return ''
  
            if eventd['press'] in self.keymap['merge']:
                if self.act_gvert.is_inner():
                    showErrorMessage('Cannot merge inner GVert')
                    return ''
                if any(ge.is_zippered() or ge.is_gpatched() for ge in self.act_gvert.get_gedges_notnone()):
                    showErrorMessage('Cannot merge inner GVert with GEdge that is zippered or patched')
                    return ''
                x,y = eventd['mouse']
                pts = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'], self.mx, [(x,y)])
                if not pts:
                    return ''
                pt = pts[0]
                sel_ge = set(self.act_gvert.get_gedges_notnone())
                for gv in self.polystrips.gverts:
                    if gv.is_inner() or not gv.is_picked(pt) or gv == self.act_gvert: continue
                    if any(ge.is_zippered() or ge.is_gpatched() for ge in gv.get_gedges_notnone()):
                        showErrorMessage('Cannot merge GVert with GEdge that is zippered or patched')
                        return ''
                    if len(self.act_gvert.get_gedges_notnone()) + len(gv.get_gedges_notnone()) > 4:
                        showErrorMessage('Too many connected GEdges for merge!')
                        continue
                    if any(ge in sel_ge for ge in gv.get_gedges_notnone()):
                        showErrorMessage('Cannot merge GVerts that share a GEdge')
                        continue
                    self.create_undo_snapshot('merge')
                    self.polystrips.merge_gverts(self.act_gvert, gv)
                    self.act_gvert = gv
                    return ''
                return ''

            if self.act_gvert.zip_over_gedge:
                gvthis = self.act_gvert
                gvthat = self.act_gvert.get_zip_pair()

                if eventd['press'] in self.keymap['zip down']:
                    self.create_undo_snapshot('zip count')
                    max_t = 1 if gvthis.zip_t>gvthat.zip_t else gvthat.zip_t-0.05
                    gvthis.zip_t = min(gvthis.zip_t+0.05, max_t)
                    gvthis.zip_over_gedge.update()
                    dprint('+ %f %f' % (min(gvthis.zip_t, gvthat.zip_t),max(gvthis.zip_t, gvthat.zip_t)), l=4)
                    return ''

                if eventd['press'] in self.keymap['zip up']:
                    self.create_undo_snapshot('zip count')
                    min_t = 0 if gvthis.zip_t<gvthat.zip_t else gvthat.zip_t+0.05
                    gvthis.zip_t = max(gvthis.zip_t-0.05, min_t)
                    gvthis.zip_over_gedge.update()
                    dprint('- %f %f' % (min(gvthis.zip_t, gvthat.zip_t),max(gvthis.zip_t, gvthat.zip_t)), l=4)
                    return ''

            if eventd['press'] in self.keymap['fill']:
                self.create_undo_snapshot('simplefill')
                self.fill(eventd)
                return ''
                
        return ''
            
        
        return ret
        
    