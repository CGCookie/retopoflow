import os
import json
import shelve

retopoflow_version = "2.0.0 beta"

firsttime_message = '''
Welcome to RetopoFlow 2.0.0 beta!

What you see is here is a major rewrite of the code base.  We have worked hard to make this as production ready as possible.  However, if you find bugs, please let us know so that we may fix them!  Screenshots, .blend files, and instructions on reproducing the bug is very helpful.
'''[1:-1]  # skip first and final \n

class Options:
    options_filename = 'rf_options'
    default_options = {
        'profiler': False,
        'welcome': True,
    }
    
    def __init__(self):
        pass
    def __getitem__(self, key):
        with shelve.open(self.options_filename) as db:
            val = db[key] if key in db else self.default_options[key]
        return val
    def __setitem__(self, key, val):
        with shelve.open(self.options_filename, writeback=True) as db:
            db[key] = val
    def reset(self):
        with shelve.open(self.options_filename, writeback=True) as db:
            keys = db.keys()
            for key in keys: del db[key]
    def set_defaults(self, d_key_vals):
        for key in d_key_vals: self.default_options[key] = d_key_vals[key]

# set all the default values!
options = Options()
