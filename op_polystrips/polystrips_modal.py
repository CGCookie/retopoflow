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

from ..lib import common_utilities
from ..lib.common_utilities import showErrorMessage, get_source_object, get_target_object
from ..lib.classes.sketchbrush.sketchbrush import SketchBrush

from ..modaloperator import ModalOperator
from .polystrips_ui            import Polystrips_UI
from .polystrips_ui_modalwait  import Polystrips_UI_ModalWait
from .polystrips_ui_tools      import Polystrips_UI_Tools
from .polystrips_ui_draw       import Polystrips_UI_Draw
from .polystrips_datastructure import Polystrips



class CGC_Polystrips(ModalOperator, Polystrips_UI, Polystrips_UI_ModalWait, Polystrips_UI_Tools, Polystrips_UI_Draw):
    ''' CG Cookie Polystrips Modal Editor '''
    ''' Note: the functionality of this operator is split up over multiple base classes '''
    
    bl_category    = "Retopology"
    bl_idname      = "cgcookie.polystrips"
    bl_label       = "Polystrips"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    def __init__(self):
        FSM = {}
        FSM['sketch']           = self.modal_sketching
        FSM['scale tool']       = self.modal_scale_tool
        FSM['grab tool']        = self.modal_grab_tool
        FSM['rotate tool']      = self.modal_rotate_tool
        FSM['brush scale tool'] = self.modal_scale_brush_pixel_tool
        FSM['tweak move tool']  = self.modal_tweak_move_tool
        FSM['tweak relax tool'] = self.modal_tweak_relax_tool
        self.initialize('help_polystrips.txt', FSM)
        self.initialize_ui()
        self.initialize_draw()

    def start_poll(self, context):
        ''' Called when tool is invoked to determine if tool can start '''
        
        self.settings = common_utilities.get_settings()

        if context.mode == 'EDIT_MESH' and self.settings.source_object == '':
            showErrorMessage('Must specify a source object first')
            return False
        
        if context.mode == 'OBJECT' and self.settings.source_object == '' and not context.active_object:
            showErrorMessage('Must specify a source object or select an object')
            return False

        if get_source_object().type != 'MESH':
            showErrorMessage('Source must be a mesh object')
            return False

        if get_target_object().type != 'MESH':
            showErrorMessage('Target must be a mesh object')
            return False

        if self.settings.source_object == self.settings.target_object and self.settings.source_object and self.settings.target_object:
            showErrorMessage('Source and Target cannot be same object')
            return False

        return True
    
    def start(self, context):
        ''' Called when tool is invoked '''
        self.start_ui(context)
    
    def end(self, context):
        ''' Called when tool is ending modal '''
        self.end_ui(context)
    
    def end_commit(self, context):
        ''' Called when tool is committing '''
        self.cleanup(context, 'commit')
        self.create_mesh(context)
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        self.cleanup(context, 'cancel')
        pass
    
    def update(self, context):
        pass

