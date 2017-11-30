'''
Copyright (C) 2017 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import os
import re
import json
import shelve

retopoflow_version = '2.0.0 beta'

retopoflow_issues_url = "https://github.com/CGCookie/retopoflow/issues"

# XXX: JUST A TEST!!!
# TODO: REPLACE WITH ACTUAL, COOKIE-RELATED ACCOUNT!! :)
# NOTE: can add number to url to start the amount off
# ex: https://paypal.me/retopoflow/5
retopoflow_tip_url    = "https://paypal.me/gfxcoder/"


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

In RetopoFlow 2.0, we completely rewrote the framework so that RF acts like any other Blender Mode (like Edit Mode).
Choosing one of the tools from the RetopoFlow panel will start RetopoFlow Mode with the chosen tool selected.

When RetopoFlow Mode is enabled, all parts of Blender outside the 3D view will be darkened (and disabled) and panels will be added to the 3D view.
These panels allow you to switch between RF tools, set tool options, and set RF options.
Also, a one-time Welcome message will greet you.

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
- SHIFT+X: dissolve selected verts
- CTRL+X: dissolve selected edges
- CTRL+SHIFT+X: dissolve selected faces

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

## Options

- By default, Tweak will not move vertices that are on the boundary.
- By default, Tweak will only move vertices that are visible.
- By default, Tweak will move all vertices under the brush.
- These options are adjustable under the Tweak Options panel.
'''

help_relax = '''
# Relax Help

The Relax tool allows you to easily relax the vertex positions using a brush.

- ACTION: relax vertices that are within brush
- F: adjust brush size
- SHIFT+S: relax all selected vertices
- CTRL+F: adjust falloff
- SHIFT+F: adjust strength

## Options

- By default, Relax will not move vertices that are on the boundary.
- By default, Relax will only move vertices that are visible.
- By default, Relax will move all vertices under the brush.
- These options are adjustable under the Relax Options panel.
'''

help_loops = '''
# Loops Help

The Loops tool allows you to insert new edge loops along a face loop and slide any edge loop along the source mesh.

- CTRL+ACTION: insert edge loop
- SELECT: select edge loop
- S: slide edge loop
'''

help_patches = '''
# Patches Help

The Patches tool helps fill in holes in your topology.
Select the strip of boundary edges that you wish to fill.

- SELECT / SHIFT+SELECT: select inner edge loop
- F: fill selected inner edge loop

## Notes

All boundary edges must be adjacent to exactly one face.

The Patches tool currently only handles a limited number of scenarios (listed below).
More support coming soon!

![](help_patches_2sides_beforeafter.png)

- 2 edges: L shape, | | shape
- 4 edges: Rectangle shape
'''


class Options:
    options_filename = 'rf_options'     # the filename of the Shelve object
                                        # will be located at root of RF plugin
    
    default_options = {                 # all the default settings for unset or reset
        'welcome':              True,   # show welcome message?
        'tools_min':            False,  # minimize tools window?
        'profiler':             False,  # enable profiler?
        'instrument':           False,  # enable instrumentation?
        'version 1.3':          True,   # show RF 1.3 panel?
        
        'tools pos':    7,
        'info pos':     1,
        'options pos':  9,
        
        'tools autocollapse': True,
        
        'select dist':          10,     # pixels away to select
        
        'color theme':          'Green',
        
        'instrument_filename':  'RetopoFlow_instrument',
        'log_filename':         'RetopoFlow_log',
        'backup_filename':      'RetopoFlow_backup',
        'quickstart_filename':  'RetopoFlow_quickstart',
        
        'contours count':   16,
        
        'polystrips scale falloff': -1,
        'polystrips draw curve': False,
        
        'relax selected': False,
        'relax boundary': False,
        'relax hidden':   False,
        
        'tweak selected': False,
        'tweak boundary': True,
        'tweak hidden':   False,
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
    def keys(self): return Options.db.keys()
    def reset(self):
        keys = list(Options.db.keys())
        for key in keys:
            del Options.db[key]
        Options.db.sync()
    def set_default(self, key, val):
        if key not in Options.db: Options.db[key] = val
        #Options.default_options[key] = val
    def set_defaults(self, d_key_vals):
        for key in d_key_vals:
            self.set_default(key, d_key_vals[key])
            #Options.default_options[key] = d_key_vals[key]

def rgba_to_float(r, g, b, a): return (r/255.0, g/255.0, b/255.0, a/255.0)
class Themes:
    themes = {
        'Blue': {
            'mesh':    rgba_to_float( 78, 207,  81, 255),
            'frozen':  rgba_to_float(255, 255, 255, 255),
            'new':     rgba_to_float( 40, 255,  40, 255),
            'select':  rgba_to_float( 26, 111, 255, 255),
            'active':  rgba_to_float( 26, 111, 255, 255),
            'warning': rgba_to_float(182,  31,   0, 125),
            
            'stroke':  rgba_to_float( 40, 255,  40, 255),
        },
        'Green': {
            'mesh':    rgba_to_float( 26, 111, 255, 255),
            'frozen':  rgba_to_float(255, 255, 255, 255),
            'new':     rgba_to_float( 40, 255,  40, 255),
            'select':  rgba_to_float( 78, 207,  81, 255),
            'active':  rgba_to_float( 78, 207,  81, 255),
            'warning': rgba_to_float(182,  31,   0, 125),
            
            'stroke':  rgba_to_float( 40, 255,  40, 255),
        },
        'Orange': {
            'mesh':    rgba_to_float( 26, 111, 255, 255),
            'frozen':  rgba_to_float(255, 255, 255, 255),
            'new':     rgba_to_float( 40, 255,  40, 255),
            'select':  rgba_to_float(207, 135,  78, 255),
            'active':  rgba_to_float(207, 135,  78, 255),
            'warning': rgba_to_float(182,  31,   0, 125),
            
            'stroke':  rgba_to_float( 40, 255,  40, 255),
        },
    }
    
    def __getitem__(self, key): return self.themes[options['color theme']][key]


# set all the default values!
options = Options()
themes = Themes()