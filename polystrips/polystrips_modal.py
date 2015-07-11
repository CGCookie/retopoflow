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
        ModalOperator.initialize(self, FSM)
        self.initialize_ui()
    
    def start_poll(self, context):
        ''' Called when tool is invoked to determine if tool can start '''
        
        if context.mode == 'EDIT_MESH' and len(context.selected_objects) != 2:
            showErrorMessage('Must select exactly two objects when in Edit Mode')
            return False
        
        if context.mode == 'OBJECT' and len(context.selected_objects) != 1:
            showErrorMessage('Must select only one object when in Object Mode')
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

