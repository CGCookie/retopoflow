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


class EdgePatches_UI_ModalWait():
    def modal_wait(self, context, eventd):
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

            if settings.use_pressure:
                p = eventd['pressure']
                r = eventd['mradius']
            else:
                p = 1
                r = self.stroke_radius

            self.sketch_curpos = (x,y)

            if False and eventd['ctrl'] and self.act_epvert:
                # continue sketching from selected gvert position
                gvx,gvy = location_3d_to_region_2d(eventd['region'], eventd['r3d'], self.act_gvert.position)
                self.sketch = [((gvx,gvy),self.act_gvert.radius), ((x,y),r)]
            else:
                self.sketch = [((x,y),r)]
            
            return 'sketch'

        # If RMB is set to select, select as normal
        if eventd['press'] in {'RIGHTMOUSE', 'SHIFT+RIGHTMOUSE'}:
            if 'LEFTMOUSE' not in selection_mouse():
                self.pick(eventd)
            return ''

        if self.act_epvert:
            if eventd['press'] in self.keymap['merge']:
                if self.act_epvert.is_inner():
                    showErrorMessage('Cannot merge inner EPVert')
                    return ''
                x,y = eventd['mouse']
                pts = common_utilities.ray_cast_path(eventd['context'], self.obj, [(x,y)])
                if not pts: return ''
                pt = pts[0]
                sel_epe = set(self.act_epvert.epedges)
                for epv in self.edgepatches.epverts:
                    if epv.is_inner() or not epv.is_picked(pt) or epv == self.act_epvert: continue
                    if any(epe in sel_epe for epe in epv.epedges):
                        showErrorMessage('Cannot merge EPVerts that share an EPEdge')
                        continue
                    self.create_undo_snapshot('merge')
                    self.edgepatches.merge_epverts(self.act_epvert, epv)
                    self.act_epvert = epv
                    return ''
                return ''

            if eventd['press'] in self.keymap['translate']:
                self.create_undo_snapshot('grab')
                self.ready_tool(eventd, self.grab_tool_epvert_neighbors)
                return 'grab tool'

            if eventd['press'] in self.keymap['delete']:
                if self.act_epvert.is_inner(): return ''
                self.create_undo_snapshot('delete')
                self.edgepatches.disconnect_epvert(self.act_epvert)
                self.act_epvert = None
                self.edgepatches.remove_unconnected_epverts()
                return ''
        
        if self.act_epedge:
            if eventd['press'] in self.keymap['delete']:
                self.create_undo_snapshot('delete')
                self.edgepatches.disconnect_epedge(self.act_epedge)
                self.act_epedge = None
                self.edgepatches.remove_unconnected_epverts()
                return ''

