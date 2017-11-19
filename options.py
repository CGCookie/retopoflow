import os
import re
import json
import shelve

retopoflow_version = "2.0.0 beta"

firsttime_message = '''
Welcome to RetopoFlow 2.0.0 beta!

What you see is here is a complete rewrite of the code base.
RetopoFlow 2.0 works like another any Blender mode, especially Edit Mode, but it will also feel distinct.

Major changes from version 1.x:

- All tools work within the RF Mode.  In fact, shortcut keys (ex: Q,W,E,R,T,Y) will switch quickly between the tools.
- All tools use the current selection for their context.  For example, PolyStrips can edit any strip of quads by simply selecting them.
- The selected and active mesh is the Target Mesh, and any other visible meshes are Source Meshes.
- Many options and configurations are sticky, which means that some settings will remain even if you leave RF Mode or quit Blender.
- All tools render similarly, although they each will have their own custom widget (ex: circle cursor in Tweak) and annotations (ex: edge count in Contours).

Note:
We have worked hard to make this as production ready as possible, but please let us know if you find bugs so that we can fix them!
Be sure to submit screenshots, .blend files, and/or instructions on reproducing the bug to our GitHub bug tracker at https://github.com/CGCookie/retopoflow/issues.
'''

help_contours = '''
Contours Help

Drawing:

- SELECTMOUSE: select stroke
- CTRL+LMB: draw contour stroke perpendicular to form. newly created contour extends selection if applicable.

Transform:

- G: slide / grab
- S: shift loop
- SHIFT+S: rotate

Other:

- X: delete
- SHIFT+X: dissolve
- SHIFT+UP / SHIFT+DOWN: increase / decrease counts

Tips:

- Extrude Contours from an existing edgeloop by selecting it in Edit Mode before starting Contours.
'''


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
