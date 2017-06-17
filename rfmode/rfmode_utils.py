import bpy
from bpy.app.handlers import persistent, load_post


class RFMode_Utils:
    """
    initialize log
    """
    
    def init_utils(self):
        #self.cb_pl_handle = load_post.append(self.)
        pass

    def handle_exception(self, serious=False):
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
            self.modal_end()
        
        self.fsm_mode = 'main'

