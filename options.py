import os
import re
import json
import shelve

retopoflow_version = "2.0.0"

firsttime_message = '''
# Welcome to RetopoFlow {version}!

RetopoFlow is an add-on for Blender that brings together a set of retopology tools within a custom Blender mode to enable you to work more quickly, efficiently, and in a more artist-friendly manner.
The tools, which are specifically designed for retopology, create a complete workflow in Blender without the need for additional software.

The RetopoFlow tools automatically generate geometry by drawing on an existing surface, snapping the new mesh to the source surface at all times, meaning you never have to worry about your mesh conforming to the original model (no Shrinkwrap modifier required!).
Additionally, all mesh generation is quad-based (except for PolyPen).



## Major Changes from Version 1.x

What you see behind this message is here is a complete rewrite of the code base.
RetopoFlow 2.0 now works like another any Blender mode, especially Edit Mode, but it will also feel distinct.
We focused our 2.0 development on two main items: stability and a consistent, intuitive, and efficient user experience.
With an established and solid framework, we will focus more on features with future releases.

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

- Give us a rating with comments on the Blender Market. (requires purchasing a copy through Blender Market)
- Purchase a copy of RetopoFlow on the Blender Market to help fund future developments.
- Consider donating to our drink funds :)

We have worked hard to make this as production ready as possible.
We focused on stability and bug handling in addition to focusing features and improving overall speed.
However, if you find a bug, please let us know so that we can fix them!
Be sure to submit screenshots, .blend files, and/or instructions on reproducing the bug to our bug tracker by clicking the "Report Issue" button or visiting https://github.com/CGCookie/retopoflow/issues.


## Known Issues / Future Work

Below is a list of known issues that we are working on.

- Very large source meshes cause a very long start-up time.  Temporary workaround: reduce the number of faces by using Decimate Modifier.
- Very large target meshes causes slowness in some tools.
- Some of the tools are still missing features from version 1.x.


## Final Words

We thank you for using RetopoFlow, and we look forward to hearing back from you!

Cheers!

--The RetopoFlow Team
'''.format(version=retopoflow_version)


help_quickstart = '''
RetopoFlow 2.0 Quick Start Guide
================================

We wrote this guide to help you get started as quickly a possible with the new RetopoFlow 2.0.
More detailed help is available after you start RF.


Target and Source Objects
-------------------------

In RetopoFlow 1.3 you were required to select explicitly the source and target objects, but in RetopoFlow 2.0 the source and target objects are determined by RetopoFlow.

The target object is either:

- the active mesh object if it is also selected (Object Mode)
- the mesh object currently being edited (Edit Mode)
- otherwise, a newly created mesh object

Any mesh object that is visible and not the target object is considered a source object.
This means that you can hide or move objects to hidden layers to change which source objects will be retopologized.
Note: only newly created or edited target geometry will snap to the source.


RetopoFlow Mode
---------------

The tools in RetopoFlow 1.3 were disjoint set of tools, where you would need to quit one tool in order to start another.
Also, because we wrote RF 1.3 tools independently, the visualizations and settings were not consistent.

In RetopoFlow 2.0, we 

'''




help_contours = '''
# Contours Help

The Contours tool gives you a quick and easy way to retopologize cylindrical forms.
For example, it's ideal for organic forms, such as arms, legs, tentacles, tails, horns, etc.

The tool works by drawing strokes perpendicular to the form to define the contour of the shape.
Immediately upon drawing the first stroke, a preview mesh is generated, showing you exactly what you'll get.
You can draw as many strokes as you like, in any order, from any direction.

![](help_contours.png)


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

The PolyStrips tool provides quick and easy ways to create the key face loops needed to retopologize a complex model.
For example, if you need to retopologize a human face, creatures, or any other complex organic or hard-surface object.

PolyStrips works by hand-drawing stokes on to the high-resolution source object.
The strokes are instantly converted into spline-based strips of polygons, which can be used to quickly map out the key topology flow.
Clean mesh previews are generated on the fly, showing you the exact mesh that will be created.


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

The PolyPen tool provides everything you need for fast retopology in those scenarios where you need absolute control of every vertex position (e.g., low-poly game models).
This tool lets you insert vertices, extrude edges, fill faces, and transform the subsequent geometry all within one tool and in just a few clicks.


## Drawing

- SELECT / SHIFT+SELECT: select geometry
- CTRL+ACTION: insert geometry connected to selected geometry
- SHIFT+ACTION: insert edge strip
- A: deselect / select all

## Other

- G: translate
- X: delete selection
- SHIFT+X: dissolve selection

## Tips

- Creating vertices/edges/faces is dependent on your selection:
'''

help_tweak = '''
# Tweak Help

The Tweak tool allows you to easily adjust the vertex positions using a brush.

- ACTION: move vertices that are within brush
- F: adjust brush size
- CTRL+F: adjust falloff
- SHIFT+F: adjust strength
'''

help_relax = '''
# Relax Help

The Relax tool allows you to easily relax the vertex positions using a brush.

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

The Loops tool allows you to insert new edge loops along a face loop and slide any edge loop along the source mesh.

- CTRL+ACTION: insert edge loop
- SELECT / SHIFT+SELECT: select edge loop
- S: slide edge loop
'''


class Options:
    options_filename = 'rf_options'     # the filename of the Shelve object
                                        # will be located at root of RF plugin
    
    default_options = {                 # all the default settings for unset or reset
        'profiler':             False,
        'welcome':              True,
        'tools_min':            False,
        'instrument':           False,
        'version 1.3':          False,
        'color theme':          'Green',
        'instrument_filename':  'RetopoFlow_instrument',
        'log_filename':         'RetopoFlow_log',
        'backup_filename':      'RetopoFlow_backup',
        'quickstart_filename':  'RetopoFlow_quickstart',
    }
    
    db = None                           # current Shelve object
    
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
