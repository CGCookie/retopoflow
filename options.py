import os
import re
import json
import shelve

retopoflow_version = "2.0.0 beta"

firsttime_message = '''
Welcome to RetopoFlow 2.0.0 beta!

What you see is here is a complete rewrite of the code base.
RetopoFlow 2.0 works like another any Blender mode, and it will also feel distinct.

Note:
We have worked hard to make this as production ready as possible, but please let us know if you find bugs so that we can fix them!
Be sure to submit screenshots, .blend files, and instructions on reproducing the bug.
'''


# process message similarly to Markdown
firsttime_message = firsttime_message[1:-1]                         # skip first and final \n
firsttime_message = re.sub(r'\n\n\n*', r'\n\n', firsttime_message)  # 2+ \n => \n\n
paragraphs = firsttime_message.split('\n\n')                        # split into paragraphs
paragraphs = [re.sub(r'\n', '  ', p) for p in paragraphs]           # join sentences of paragraphs
firsttime_message = '\n\n'.join(paragraphs)                         # join paragraphs


class Options:
    options_filename = 'rf_options'
    default_options = {
        'profiler': False,
        'welcome': True,
        'instrument': False,
        'instrument_filename': 'RetopoFlow_instrument',
        'log_filename': 'RetopoFlow_log',
        'backup_filename': 'RetopoFlow_backup',
        'tools_min': False,
    }
    db = None
    
    def __init__(self):
        if not Options.db:
            Options.db = shelve.open(Options.options_filename, writeback=True)
    def __del__(self):
        Options.db.close()
        Options.db = None
    def __getitem__(self, key):
        return Options.db[key] if key in Options.db else Options.default_options[key]
    def __setitem__(self, key, val):
        Options.db[key] = val
        Options.db.sync()
    def reset(self):
        keys = list(Options.db.keys())
        for key in keys:
            del Options.db[key]
        Options.db.sync()
    def set_defaults(self, d_key_vals):
        for key in d_key_vals:
            Options.default_options[key] = d_key_vals[key]

# set all the default values!
options = Options()
