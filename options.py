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

# the following enables / disables profiler code, overriding the options['profiler']
# TODO: make this False before shipping!
retopoflow_profiler = True

retopoflow_issues_url = "https://github.com/CGCookie/retopoflow/issues"

# XXX: JUST A TEST!!!
# TODO: REPLACE WITH ACTUAL, COOKIE-RELATED ACCOUNT!! :)
# NOTE: can add number to url to start the amount off
# ex: https://paypal.me/retopoflow/5
retopoflow_tip_url    = "https://paypal.me/gfxcoder/"


# sync help texts with https://github.com/CGCookie/retopoflow-docs (http://docs.retopoflow.com/)


firsttime_message = '''
# Welcome to RetopoFlow {version}!

RetopoFlow is an add-on for Blender that brings together a set of retopology tools within a custom Blender mode to enable you to work more quickly, efficiently, and in a more artist-friendly manner.
The RF tools, which are specifically designed for retopology, create a complete workflow in Blender without the need for additional software.

The RetopoFlow tools automatically generate geometry by drawing on an existing surface, snapping the new mesh to the source surface at all times, meaning you never have to worry about your mesh conforming to the original model---no Shrinkwrap modifier required!
Additionally, all mesh generation is quad-based (except for PolyPen).



## Major Changes from Version 1.x

What you see behind this message is here is a complete rewrite of the code base.
RetopoFlow 2.0 now works like another any Blender mode, especially Edit Mode, but it will also feel distinct.
We focused our 2.0 development on two main items: stability and a consistent, intuitive, and efficient user experience.
With an established and solid framework, we will focus more on features with future releases.

- Everything runs within the RF Mode; no more separation of tools!  In fact, the shortcut keys Q, W, E, R, T, Y, and U will switch quickly between the tools.
- Each tool has been simplified to do perform its job well.
- All tools use the current selection for their context.  For example, PolyStrips can edit any strip of quads by simply selecting them.
- The selected and active mesh is the Target Mesh, and any other visible meshes are Source Meshes.
- Many options and configurations are sticky, which means that some settings will remain even if you leave RF Mode or quit Blender.
- All tools have similar and consistent visualization, although they each will have their own custom widget (ex: circle cursor in Tweak) and annotations (ex: edge count in Contours).
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
We focused on stability and bug handling in addition to focusing features, improving overall speed, and making RetopoFlow easier to use.
However, if you find a bug or a missing feature, please let us know so that we can fix them!
Be sure to submit screenshots, .blend files, and/or instructions on reproducing the bug to our bug tracker by clicking the "Report Issue" button or visiting https://github.com/CGCookie/retopoflow/issues.
We have added buttons to open the issue tracker in your default browser and to save screenshots of Blender.

![](help_exception.png)


## Known Issues / Future Work

Below is a list of known issues that we are working on.

- Very large source meshes cause a delay and stutter at start-up time.  Note: the sources are cached, so RF will load much more quickly the second time.
- Very large target meshes causes slowness in some tools.
- Patches handles only simple hole shapes.
- Display scales other than 1.0 (ex: Retina) does not display correct.


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

In RetopoFlow 1.x you were required to select the source and target objects explicitly, but in RetopoFlow 2.0 the source and target objects are determined by RetopoFlow based on which mesh objects are selected, active, and visible.

The target object is either:

- the active mesh object if it is also selected (Object Mode)
- the mesh object currently being edited (Edit Mode)
- otherwise, a newly created mesh object

Any mesh object that is visible and not the target object is considered a source object.
This means that you can hide or move objects to hidden layers to change which source objects will be retopologized.
Note: only newly created or edited target geometry will snap to the source.


RetopoFlow Mode
---------------

The tools in RetopoFlow 1.x were disjoint set of tools, where you would need to quit one tool in order to start another.
Also, because we wrote RF 1.x tools independently, the visualizations and settings were not consistent.
Furthermore, the only indication that a tool was running in RetopoFlow 1.x was a small "Click for Help" button in the top-right corner, which is easily missed.

In RetopoFlow 2.0, we completely rewrote the framework so that RF acts like any other Blender Mode (like Edit Mode).
Choosing one of the tools from the RetopoFlow panel will start RetopoFlow Mode with the chosen tool selected.

When RetopoFlow Mode is enabled, all parts of Blender outside the 3D view will be darkened (and disabled) and panels will be added to the 3D view.
These panels allow you to switch between RF tools, set tool options, and get more information.
Also, a one-time Welcome message will greet you.

'''



help_general = '''
# General Help

When RetopoFlow Mode is enabled, certain shortcuts are available regardless of the tool selected.
For tool-specific help, select the tool from the Tools panel, and either press F1 or click Tool Help.


## RetopoFlow Shortcuts

- ENTER / ESC: quit RetopoFlow
- TAB: quit RetopoFlow and enter Edit Mode
- F1: general help
- F2: tool help

## Tool Shortcuts

Pressing the tool's shortcut will automatically switch to that tool.
Note: selection and the undo stack is maintained between tools.

- Q: Contours
- W: PolyStrips
- E: PolyPen
- R: Relax
- T: Tweak
- Y: Loops
- U: Patches

## Universal Shortcuts

The following shortcuts work across all the tools, although each tool may have a distinct way of performing the action.
For example, pressing G in Contours will slide the selected loop.

- A: deselect / select all
- ACTION: select then grab and move
- SELECT / SHIFT+SELECT: selection painting
- CTRL+SELECT / CTRL+SHIFT+SELECT: smart selection
- G: grab and move selected geometry
- X: delete / dissolve selection
- CTRL+Z: undo
- CTRL+SHIFT+Z: redo


## Defaults

The ACTION command is set to the left mouse button.

The SELECT command is set to the right mouse button.


## General Options

The Maximize Area button will make the 3D view take up the entire Blender window, similar to pressing CTRL+UP / SHIFT+SPACE.

The Snap All Verts button will move all of the target vertices to the nearest point on the sources.

The Theme option changes the color of selected geometry.

![](help_themes.png)

When the Auto Collapse Options is checked, tool options will automatically collapse in the options panel when the current tool changes.


## Symmetry Options

The X,Y,Z checkboxes turn on/off symmetry or mirroring along the X, Y, and Z axes.
Note: symmetry is the same as with mirror modifier.

When symmetry is turned on, the mirroring planes can be visualized on the sources choosing either the Edge or Face option.
The Effect setting controls the strength of the visualization.
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

- ACTION: select edge then grab and move
- SELECT / SHIFT+SELECT: select edge
- CTRL+SELECT / CTRL+SHIFT+SELECT: select loop
- CTRL+ACTION: draw contour stroke perpendicular to form. newly created contour extends selection if applicable.
- A: deselect / select all

## Transform

- G: slide
- S: shift
- SHIFT+S: rotate

## Other

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

![](help_polystrips.png)

## Drawing

- ACTION: select quad then grab and move
- SELECT / SHIFT+SELECT: select quads
- CTRL+ACTION: draw strip of quads
- F: adjust brush size
- A: deselect / select all

## Control Points

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

![](help_polypen.png)

## Drawing

- SELECT / SHIFT+SELECT: select geometry
- CTRL+ACTION: insert geometry connected to selected geometry
- SHIFT+ACTION: insert edge strip
- A: deselect / select all

## Tips

Creating vertices/edges/faces is dependent on your selection:

- When nothing is selected, a new vertex is added.
- When a single vertex is selected, an edge is added between mouse and selected vertex.
- When an edge is selected, a triangle is added between mouse and selected edge.
- When a triangle is selected, a vertex is added to the triangle, turning the triangle into a quad
'''

help_tweak = '''
# Tweak Help

The Tweak tool allows you to easily adjust the vertex positions using a brush.

![](help_tweak.png)

- ACTION: move vertices that are within brush
- F: adjust brush size
- CTRL+F: adjust falloff
- SHIFT+F: adjust strength

## Options

Tweak has several options to control which vertices are or are not moved.

- Selected: only move vertices that are selected.
- Boundary: allow boundary vertices to be moved.
- Hidden: allow vertices that are behind geometry to be moved.
'''

help_relax = '''
# Relax Help

The Relax tool allows you to easily relax the vertex positions using a brush.

![](help_relax.png)

- ACTION: relax vertices that are within brush
- F: adjust brush size
- SHIFT+S: relax all selected vertices
- CTRL+F: adjust falloff
- SHIFT+F: adjust strength

## Options

Relax has several options to control which vertices are or are not moved.

- Selected: only move vertices that are selected.
- Boundary: allow boundary vertices to be moved.
- Hidden: allow vertices that are behind geometry to be moved.
'''

help_loops = '''
# Loops Help

The Loops tool allows you to insert new edge loops along a face loop and slide any edge loop along the source mesh.

![](help_loops.png)

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
    options_filename = 'RetopoFlow_options' # the filename of the Shelve object
                                            # will be located at root of RF plug-in
    
    default_options = {                 # all the default settings for unset or reset
        'welcome':              True,   # show welcome message?
        'tools_min':            False,  # minimize tools window?
        'profiler':             False,  # enable profiler?
        'instrument':           False,  # enable instrumentation?
        'version 1.3':          True,   # show RF 1.3 panel?
        'debug level':          0,      # debug level, 0--5 (for printing to console)
        
        'show tooltips':        True,
        
        'github issues url':    'https://github.com/CGCookie/retopoflow/issues',
        'github new issue url': 'https://github.com/CGCookie/retopoflow/issues/new',
        
        'tools pos':    7,
        'info pos':     1,
        'options pos':  9,
        
        'tools autocollapse': True,
        'tools general collapsed': False,       # is general tools collapsed
        'tools symmetry collapsed': True,       # is symmetry tools collapsed
        'tool contours collapsed': True,       # is contours tools collapsed
        'tool polystrips collapsed': True,     # is polystrips tools collapsed
        'tool polypen collapsed': True,        # is polypen tools collapsed
        'tool relax collapsed': True,          # is relax tools collapsed
        'tool tweak collapsed': True,          # is tweak tools collapsed
        'tool loops collapsed': True,          # is loops tools collapsed
        'tool patches collapsed': True,        # is patches tools collapsed
        
        'select dist':          10,     # pixels away to select
        
        'color theme':          'Green',
        'symmetry view':        'Face',
        'symmetry effect':      0.5,
        
        'screenshot filename':  'RetopoFlow_screenshot.png',
        'instrument_filename':  'RetopoFlow_instrument',
        'log_filename':         'RetopoFlow_log',
        'backup_filename':      'RetopoFlow_backup',
        'quickstart_filename':  'RetopoFlow_quickstart',
        
        'contours count':   16,
        
        'polystrips scale falloff': -1,
        'polystrips draw curve':    False,
        'polystrips max strips':    10,     # PS will not show handles if knot count is above max
        'polystrips arrows':        False,
        
        'relax selected': False,
        'relax boundary': False,
        'relax hidden':   False,
        
        'tweak selected': False,
        'tweak boundary': True,
        'tweak hidden':   False,
    }
    
    db = None                           # current options dict
    fndb = None
    
    def __init__(self):
        if not Options.fndb:
            path = os.path.split(os.path.abspath(__file__))[0]
            Options.fndb = os.path.join(path, Options.options_filename)
            print('RetopoFlow Options path: %s' % Options.fndb)
            self.read()
    def __del__(self):
        #self.write()
        pass
    def __getitem__(self, key):
        return Options.db[key] if key in Options.db else Options.default_options[key]
    def __setitem__(self, key, val):
        assert key in Options.default_options, 'Attempting to write "%s":"%s" to options, but key does not exist' % (str(key),str(val))
        Options.db[key] = val
        self.write()
    def write(self):
        json.dump(Options.db, open(Options.fndb, 'wt'))
    def read(self):
        Options.db = {}
        if os.path.exists(Options.fndb):
            try:
                Options.db = json.load(open(Options.fndb, 'rt'))
            except Exception as e:
                print('Exception caught while trying to read options from file')
                print(str(e))
        else:
            print('No options file')
    def keys(self): return Options.db.keys()
    def reset(self):
        keys = list(Options.db.keys())
        for key in keys:
            del Options.db[key]
        self.write()
    def set_default(self, key, val):
        assert key in Options.default_options, 'Attempting to write "%s":"%s" to options, but key does not exist' % (str(key),str(val))
        if key not in Options.db: Options.db[key] = val
    def set_defaults(self, d_key_vals):
        for key in d_key_vals:
            self.set_default(key, d_key_vals[key])

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