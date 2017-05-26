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
    
    def handle_exception(self. serious=False):
        errormsg = print_exception()
        # if max number of exceptions occur within threshold of time, abort!
        curtime = time.time()
        self.exceptions_caught += [(errormsg, curtime)]
        # keep exceptions that have occurred within the last 5 seconds
        self.exceptions_caught = [(m,t) for m,t in self.exceptions_caught if curtime-t < 5]
        # if we've seen the same message before (within last 5 seconds), assume
        # that something has gone badly wrong
        c = sum(1 for m,t in self.exceptions_caught if m == errormsg)
        if serious or c > 1:
            self.log.add('\n'*5)
            self.log.add('-'*100)
            self.log.add('Something went wrong. Please start an error report with CG Cookie so we can fix it!')
            self.log.add('-'*100)
            self.log.add('\n'*5)
            showErrorMessage('Something went wrong. Please start an error report with CG Cookie so we can fix it!', wrap=240)
            self.exception_quit = True
            self.end_ui()
        
        self.fsm_mode = 'main'

    def modal_poll(self):
        '''
        return True if modal can start; otherwise False
        '''
        return True
    
    def modal_start(self):
        '''
        get everything ready to be run as modal tool
        '''
        pass

    def modal_end(self):
        '''
        finish up stuff, as our tool is leaving modal mode
        '''
        pass



    def modal(self, context, event):
        '''
        Called by Blender while our tool is running modal.
        This state checks if navigation is occurring.
        This state calls auxiliary wait state to see into which state we transition.
        '''

        self.context = context
        self.eventd.update(self.context, event)
        
        if self.exception_quit:
            try:
                self.modal_end()
                self.ui_end()
            except:
                self.handle_exception(serious=True)
            return {'CANCELLED'}            # Something bad happened, so bail!

        # when does this occur?
        if not self.context.area:
            print('Context with no area')
            print(self.context)
            return {'RUNNING_MODAL'}

        # TODO : is this necessary??
        self.context.area.tag_redraw()       # force redraw
        
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
                self.ui_end()
            except:
                self.handle_exception(serious=True)
            return {'FINISHED'}
        
        return {'RUNNING_MODAL'}            # tell Blender to continue running our tool in modal

    def invoke(self, context, event):
        '''
        called by Blender when the user invokes (calls/runs) our tool
        '''
        self.context = context
        self.eventd.update(self.context, event)
        if not self.modal_poll(): return {'CANCELLED'}    # tool cannot start
        self.modal_start()
        self.ui_start()
        self.context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}    # tell Blender to continue running our tool in modal
