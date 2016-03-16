'''
Created on Jul 11, 2015

@author: Patrick
'''

from ..lib import common_utilities
from ..lib.common_utilities import bversion
from ..modaloperator import ModalOperator
from ..preferences import RetopoFlowPreferences
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d, region_2d_to_vector_3d
from bpy.props import StringProperty

class  CGC_EyeDropper(ModalOperator):
    '''Use Eyedropper To pick object from scene'''
    bl_idname = "cgcookie.eye_dropper"      # unique identifier for buttons and menu items to reference
    bl_label = "Eye Dropper"       # display name in the interface
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    target_prop = StringProperty(default = '')

    def __init__(self):
        FSM = {}
        
        '''
        main, nav, and wait states are automatically added in initialize function, called below.
        '''
        self.initialize('Click an object', FSM)
        
    def start_poll(self, context):
        ''' Called when tool is invoked to determine if tool can start '''
        settings = common_utilities.get_settings()
        if not hasattr(settings, self.target_prop):
            return False
        return len(context.scene.objects) > 0
    
    def start(self, context):
        ''' Called when tool has been invoked '''
        self.ob = None
        self.ob_preview = 'None'
        
        self.help_box.uncollapse()
        self.help_box.fit_box_width_to_text_lines()
        self.help_box.snap_to_corner(context, corner = [1,1])
        pass
    
    def update(self,context):
        '''Place update stuff here'''
        pass
    
    def end(self, context):
        ''' Called when tool is ending modal '''
        
        context.area.header_text_set()
        return
    
    def end_commit(self, context):
        ''' Called when tool is committing '''
        settings = common_utilities.get_settings()
        
        if self.ob and self.ob.type == 'MESH':
                settings.__setattr__(self.target_prop, self.ob.name)
        return
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        pass
    
    def draw_postview(self, context):
        ''' Place post view drawing code in here '''
        
        pass
    
    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
        return
    
    def modal_wait(self, context, eventd):
        '''
        Place code here to handle commands issued by user
        Return string that corresponds to FSM key, used to change states.  For example:
        - '':     do not change state
        - 'main': transition to main state
        - 'nav':  transition to a navigation state (passing events through to 3D view)
        '''
        
        if eventd['type'] == 'MOUSEMOVE':
            x, y = eventd['mouse']
            self.hover_scene(context, x, y)
            return ''
            
        if eventd['press'] == 'LEFTMOUSE':
            return 'finish'
        
        return ''
    
    def hover_scene(self,context,x, y):
        scene = context.scene
        region = context.region
        rv3d = context.region_data
        coord = x, y
        ray_max = 10000
        view_vector = region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = region_2d_to_origin_3d(region, rv3d, coord)
        ray_target = ray_origin + (view_vector * ray_max)

        if bversion() <= '002.076.000':
            result, ob, mx, loc, normal = scene.ray_cast(ray_origin, ray_target)
        else:
            result, loc, normal, idx, ob, mx = scene.ray_cast(ray_origin, ray_target)

        if result:
            self.ob = ob
            self.ob_preview = ob.name
            context.area.header_text_set(ob.name)
        else:
            self.ob = None
            self.ob_preview = 'None'
            context.area.header_text_set('None')

