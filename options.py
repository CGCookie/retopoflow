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

- All tools work within the RF Mode.  No more separation of tools!  In fact, the shortcut keys Q, W, E, R, T, and Y will switch quickly between the tools.
- All tools use the current selection for their context.  For example, PolyStrips can edit any strip of quads by simply selecting them.
- The selected and active mesh is the Target Mesh, and any other visible meshes are Source Meshes.
- Many options and configurations are sticky, which means that some settings will remain even if you leave RF Mode or quit Blender.
- All tools render similarly, although they each will have their own custom widget (ex: circle cursor in Tweak) and annotations (ex: edge count in Contours).
- Mirroring (X, Y, and/or Z) is now visualized by overlaying a color on all the source meshes.
- Every change automatically changes the target mesh!
- Auto saves will trigger!

We want to know how RetopoFlow has benefited you in your work.
Please consider doing the following:

- Purchase a copy of RetopoFlow on the Blender Market to help fund future developments.
- Give us a rating with comments on the Blender Market.
- Consider donating to our drink funds :)

We have worked hard to make this as production ready as possible.
We focused on stability and bug handling in addition to adding features and improving overall speed.
However, if you find a bug, please let us know so that we can fix them!
Be sure to submit screenshots, .blend files, and/or instructions on reproducing the bug to our bug tracker by clicking the "Report Issue" button or visiting https://github.com/CGCookie/retopoflow/issues.
Below is a list of known issues that we are working on.

- Very large source meshes cause a very long start-up time.  Temporary workaround: reduce the number of faces by using Decimate Modifier.
- Very large target meshes causes slowness in some tools.
- Some of the tools are still missing features from their 1.x version.

Thanks for using RetopoFlow!

Cheers!

--The RetopoFlow Team
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
