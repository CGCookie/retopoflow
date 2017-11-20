import os
import re
import json
import shelve

retopoflow_version = "2.0.0 beta"

firsttime_message = '''
# Welcome to RetopoFlow 2.0.0 beta!

What you see is here is a complete rewrite of the code base.
RetopoFlow 2.0 works like another any Blender mode, especially Edit Mode, but it will also feel distinct.

## Major changes from version 1.x

- Everything runs within the RF Mode; no more separation of tools!  In fact, the shortcut keys Q, W, E, R, T, and Y will switch quickly between the tools.
- Each tool has been simplified to do perform its job well.
- All tools use the current selection for their context.  For example, PolyStrips can edit any strip of quads by simply selecting them.
- The selected and active mesh is the Target Mesh, and any other visible meshes are Source Meshes.
- Many options and configurations are sticky, which means that some settings will remain even if you leave RF Mode or quit Blender.
- All tools have similar visualization, although they each will have their own custom widget (ex: circle cursor in Tweak) and annotations (ex: edge count in Contours).
- Mirroring (X, Y, and/or Z) is now visualized by overlaying a color on all the source meshes.
- Every change automatically changes the target mesh!
- Auto saves will trigger!
- Undo and redo are universally available within RF Mode.  Call them to roll back any change.


## Feedback

We want to know how RetopoFlow has benefited you in your work.
Please consider doing the following:

- Purchase a copy of RetopoFlow on the Blender Market to help fund future developments.
- Give us a rating with comments on the Blender Market.
- Consider donating to our drink funds :)

We have worked hard to make this as production ready as possible.
We focused on stability and bug handling in addition to adding features and improving overall speed.
However, if you find a bug, please let us know so that we can fix them!
Be sure to submit screenshots, .blend files, and/or instructions on reproducing the bug to our bug tracker by clicking the "Report Issue" button or visiting https://github.com/CGCookie/retopoflow/issues.


## Known Issues / Future Work

Below is a list of known issues that we are working on.

- Very large source meshes cause a very long start-up time.  Temporary workaround: reduce the number of faces by using Decimate Modifier.
- Very large target meshes causes slowness in some tools.
- Some of the tools are still missing features from their 1.x version.


## Final Words

We thank you for using RetopoFlow, and we look forward to hearing back from you!

Cheers!

--The RetopoFlow Team
'''

help_contours = '''
# Contours Help

## Drawing

- SELECT / SHIFT+SELECT: select stroke
- CTRL+ACTION: draw contour stroke perpendicular to form. newly created contour extends selection if applicable.
- A: deselect / select all

## Transform

- G: slide / grab
- S: shift loop
- SHIFT+S: rotate

## Other

- X: delete
- SHIFT+X: dissolve
- SHIFT+UP / SHIFT+DOWN: increase / decrease counts
- EQUALS / MINUS: increase / decrease counts

## Tips

- Extrude Contours from an existing edge loop by selecting it in Edit Mode before starting Contours.
- Contours works well with mirroring!
'''


help_polystrips = '''
# PolyStrips Help

## Drawing

- SELECT / SHIFT+SELECT: select quads
- CTRL+ACTION: draw strip of quads
- F: adjust brush size
- A: deselect / select all

## Transform

- G: translate
- ACTION: translate control point under mouse
- SHIFT+ACTION: translate all inner control points around neighboring outer control point

## Other

- X: delete selected
- SHIFT+UP / SHIFT_DOWN: increase / decrease counts
- EQUALS / MINUS: increase / decrease counts
'''


help_polypen = '''
# PolyPen Help

## Drawing

- SELECT / SHIFT+SELECT: select geometry
- CTRL+ACTION: insert geometry connected to selected geometry
- SHIFT+ACTION: insert edge strip
- A: deselect / select all

## Other

- G: translate
- X: delete selection

## Tips

- Creating vertices/edges/faces is dependent on your selection:
'''

help_tweak = '''
# Tweak Help

- ACTION: move vertices that are within brush
- F: adjust brush size
- CTRL+F: adjust falloff
- SHIFT+F: adjust strength
'''

help_relax = '''
# Relax Help

- ACTION: relax vertices that are within brush
- F: adjust brush size
- CTRL+F: adjust falloff
- SHIFT+F: adjust strength

## Options

- By default, Relax will not move vertices that are on the boundary.
- By default, Relax will only move vertices that are visible.
- These options are adjustable under the Relax Options panel.
'''

help_loops = '''
# Loops Help

- CTRL+ACTION: insert edge loop
- SELECT / SHIFT+SELECT: select edge loop
- S: slide edge loop
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
