from . import key_maps
from .lib import common_utilities
from .lib.common_utilities import print_exception, showErrorMessage
from .lib.eventdetails import EventDetails
from .lib.classes.logging.logger import Logger

class RFMode_Framework:
    def init_framework(self):
        self.context = None
        self.eventd = EventDetails()
        self.logger = Logger()
        self.settings = common_utilities.get_settings()
        
        self.keymap = key_maps.rtflow_default_keymap_generate()                 # BUG?: need to update these??
        key_maps.navigation_language() # check keymap against system language
        self.events_nav = key_maps.rtflow_user_keymap_generate()['navigate']    # BUG?: need to update these??

        self.exceptions_caught = []
        self.exception_quit = False
    
    def modal_poll(self):
        '''
        return True if modal can start; otherwise False
        '''
        return True
    
    def modal_start(self):
        self.context_start()
        self.ui_start()

    def modal_end(self):
        '''
        finish up stuff, as our tool is leaving modal mode
        '''
        try:    self.ui_end()
        except: pass
        try:    self.context_end()
        except: pass



    def modal(self, context, event):
        '''
        Called by Blender while our tool is running modal.
        This state checks if navigation is occurring.
        This state calls auxiliary wait state to see into which state we transition.
        '''

        self.rfctx.update(context, event)
        
        if self.exception_quit:
            # something bad happened, so bail!
            try:    self.modal_end()
            except: self.handle_exception(serious=True)
            return {'CANCELLED'}

        # when does this occur?
        if not context.area:
            print('Context with no area')
            print(context)
            return {'RUNNING_MODAL'}

        # TODO : is this necessary??
        context.area.tag_redraw()       # force redraw
        
        if self.eventd.ftype in self.events_nav:
            # pass navigation events (mouse,keyboard,etc.) on to region
            return {'PASS_THROUGH'}
        
        if self.tool is not None:
            # are we currently using a tool?
            try:
                handled = self.tool.modal()
                if handled:
                    # tool handled event; no need to process further
                    return {'RUNNING_MODAL'}
            except:
                self.handle_exception()
                return {'RUNNING_MODAL'}
        
        # accept / cancel
        if eventd['press'] in self.keymap['confirm']:
            # commit the operator
            # (e.g., create the mesh from internal data structure)
            try:
                self.modal_end()
            except:
                self.handle_exception(serious=True)
            return {'FINISHED'}
        
        return {'RUNNING_MODAL'}            # tell Blender to continue running our tool in modal

    def invoke(self, context, event):
        '''
        called by Blender when the user invokes (calls/runs) our tool
        '''
        self.rfctx.update(context, event)
        if not self.modal_poll(): return {'CANCELLED'}    # tool cannot start
        self.modal_start()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}    # tell Blender to continue running our tool in modal
