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
from mathutils import Vector, Matrix, Quaternion
import math

from ..lib import common_drawing_px
from ..lib.common_utilities import iter_running_sum, dprint, get_object_length_scale, profiler, AddonLocator
from ..lib.common_utilities import showErrorMessage
from .tweak_ui import Tweak_UI
from .tweak_ui_tools import Tweak_UI_Tools

from ..modaloperator import ModalOperator

from ..lib import common_utilities

from ..preferences import RetopoFlowPreferences



class CGC_Tweak(ModalOperator, Tweak_UI, Tweak_UI_Tools):
    ''' CG Cookie Tweak Modal Editor '''
    
    bl_category    = "Retopology"
    bl_idname      = "cgcookie.tweak"
    bl_label       = "Tweak"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    def __init__(self):
        FSM = {}
        FSM['tweak move tool']  = self.modal_tweak_move_tool
        FSM['tweak relax tool'] = self.modal_tweak_relax_tool
        FSM['brush scale tool'] = self.modal_scale_brush_pixel_tool
        ModalOperator.initialize(self, FSM)
    
    def start_poll(self, context):
        ''' Called when tool is invoked to determine if tool can start '''
        
        self.settings = common_utilities.get_settings()

        if context.mode != 'EDIT_MESH':
            showErrorMessage('Must be in Edit Mode')

        if context.mode == 'EDIT_MESH' and not self.settings.source_object:
            showErrorMessage('Must specify a Source Object')
            return False
        
        if context.object.type != 'MESH':
            showErrorMessage('Must select a mesh object')
            return False
        
        return True
    
    def start(self, context):
        ''' Called when tool is invoked '''
        self.start_ui(context)
    
    def end(self, context):
        ''' Called when tool is ending modal '''
        self.end_ui(context)
        self.cleanup(context)
    
    def end_commit(self, context):
        ''' Called when tool is committing '''
        pass
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        pass
    
    def update(self, context):
        pass
    
    def draw_postview(self, context):
        ''' Place post view drawing code in here '''
        pass
    
    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
        settings = common_utilities.get_settings()
        region,r3d = context.region,context.space_data.region_3d
        
        color_inactive = RetopoFlowPreferences.theme_colors_mesh[settings.theme]
        color_selection = RetopoFlowPreferences.theme_colors_selection[settings.theme]
        color_active = RetopoFlowPreferences.theme_colors_active[settings.theme]

        color_frozen = RetopoFlowPreferences.theme_colors_frozen[settings.theme]
        color_warning = RetopoFlowPreferences.theme_colors_warning[settings.theme]

        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        color_handle = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
        color_border = (color_inactive[0], color_inactive[1], color_inactive[2], 1.00)
        color_fill = (color_inactive[0], color_inactive[1], color_inactive[2], 0.20)
        

        bgl.glLineWidth(1)

        if self.fsm_mode == 'brush scale tool':
            # scaling brush size
            self.sketch_brush.draw(context, color=(1, 1, 1, .5), linewidth=1, color_size=(1, 1, 1, 1))
        elif not self.is_navigating:
            # draw the brush oriented to surface
            ray,hit = common_utilities.ray_cast_region2d(region, r3d, self.cur_pos, self.obj, settings)
            hit_p3d,hit_norm,hit_idx = hit
            if hit_idx != -1: # and not self.hover_ed:
                mx = self.obj.matrix_world
                mxnorm = mx.transposed().inverted().to_3x3()
                hit_p3d = mx * hit_p3d
                hit_norm = mxnorm * hit_norm
                if settings.use_pressure:
                    common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius_pressure, (1,1,1,.5))
                else:
                    common_drawing_px.draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius, (1,1,1,.5))

        if settings.show_help:
            self.help_box.draw()
    
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
        
        #####################################
        # General

        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering
            #update brush and brush size
            x,y = eventd['mouse']
            self.sketch_brush.update_mouse_move_hover(eventd['context'], x,y)
            self.sketch_brush.make_circles()
            self.sketch_brush.get_brush_world_size(eventd['context'])

            self.help_box.hover(x,y)

            if self.sketch_brush.world_width:
                self.stroke_radius = self.sketch_brush.world_width
                self.stroke_radius_pressure = self.sketch_brush.world_width


        if eventd['press'] in self.keymap['undo']:
            self.undo_action()
            return ''

        if eventd['press'] in self.keymap['brush size']:
            self.ready_tool(eventd, self.scale_brush_pixel_radius)
            return 'brush scale tool'

        if eventd['press'] == 'Q': # profiler printout
            profiler.printout()
            return ''

        if eventd['press'] in self.keymap['brush size']:
            self.ready_tool(eventd, self.scale_brush_pixel_radius)
            return 'brush scale tool'

        if eventd['press'] in self.keymap['action']: # in self.keymap['tweak move']:
            if self.help_box.is_hovered:
                if  self.help_box.is_collapsed:
                    self.help_box.uncollapse()
                else:
                    self.help_box.collapse()
                self.help_box.snap_to_corner(context,corner = [1,1])
                return ''

            else:
                self.create_undo_snapshot('tweak')
                self.footer = 'Tweak: ' + ('Moving' if eventd['press']=='T' else 'Relaxing')
                self.modal_tweak_setup(context, eventd)
                return 'tweak move tool' # if eventd['press']=='T' else 'tweak relax tool'

        return ''
