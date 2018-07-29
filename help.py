'''
Copyright (C) 2018 CG Cookie
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

from .options import retopoflow_version


# sync help texts with https://github.com/CGCookie/retopoflow-docs (http://docs.retopoflow.com/)


firsttime_message = '''
# Welcome to RetopoFlow {version}!

RetopoFlow is an add-on for Blender that brings together a set of retopology tools within a custom Blender mode to enable you to work more quickly, efficiently, and in a more artist-friendly manner.
The RF tools, which are specifically designed for retopology, create a complete workflow in Blender without the need for additional software.

The RetopoFlow tools automatically generate geometry by drawing on an existing surface, snapping the new mesh to the source surface at all times, meaning you never have to worry about your mesh conforming to the original model---no Shrinkwrap modifier required!
Additionally, all mesh generation is quad-based (except for PolyPen).



## Major Changes from Version 1.x

What you see behind this message is here is a complete rewrite of the code base.
RetopoFlow 2.x now works like another any Blender mode, especially Edit Mode, but it will also feel distinct.
We focused our 2.x development on two main items: stability and user experience.
With an established and solid framework, we will focus more on features in future releases.

- Everything runs within the RF Mode; no more separation of tools!  In fact, the shortcut keys Q, W, E, R, T, Y, and U will switch quickly between the tools.
- Each tool has been simplified to do perform its job well.
- All tools use the current selection for their context.  For example, PolyStrips can edit any strip of quads by simply selecting them.
- The selected and active mesh is the Target Mesh, and any other visible meshes are Source Meshes.
- Many options and configurations are sticky, which means that some settings will remain even if you leave RF Mode or quit Blender.
- All tools have similar and consistent visualization, although they each will have their own custom widget (ex: circle cursor in Tweak) and annotations (ex: edge count in Contours).
- Mirroring (X, Y, and/or Z) is now visualized by overlaying a color on all the source meshes.
- Every change automatically commits to the target mesh; geometry is created in real-time! No more lost work from crashing.
- Auto saves will trigger!
- Undo and redo are universally available within RF Mode. Press CTRL+Z roll back any change, or CTRL+SHIFT+Z to redo.
- New Strokes tool!


## Feedback

We want to know how RetopoFlow has benefited you in your work.
Please consider doing the following:

- Give us a rating with comments on the Blender Market. (requires purchasing a copy through Blender Market)
- Purchase a copy of RetopoFlow on the Blender Market to help fund future developments.
- Consider donating to our drink funds :)

We have worked hard to make this as production ready as possible.
We focused on stability and bug handling in addition to new features, improving overall speed, and making RetopoFlow easier to use.
However, if you find a bug or a missing feature, please let us know so that we can fix them!
Be sure to submit screenshots, .blend files, and/or instructions on reproducing the bug to our bug tracker by clicking the "Report Issue" button or visiting https://github.com/CGCookie/retopoflow/issues.
We have added buttons to open the issue tracker in your default browser and to save screenshots of Blender.

![](help_exception.png)


## Known Issues / Future Work

Below is a list of known issues that we are working on.

- Very large source meshes cause a delay and stutter at start-up time.  Note: the sources are cached, so RF will load much more quickly the second time.
- Very large target meshes causes slowness in some tools.
- Patches supports only rudimentary fills
- RF runs _very_ slowly (<1.0 FPS) on certain machines


## Final Words

We thank you for using RetopoFlow, and we look forward to hearing back from you!

Cheers!

--The CG Cookie Tool Development Team
'''.format(version=retopoflow_version)


help_quickstart = '''
RetopoFlow 2.x Quick Start Guide
================================

We wrote this guide to help you get started as quickly a possible with the new RetopoFlow 2.x.
More detailed help is available by pressing F1 after you start RF.


TL;DR
-----

When you are retopologizing for the first time, deselect all objects and click one of the RetopoFlow tools.

When continuing work on a previous retopology session, select the target object, and click one of the RetopoFlow tools.


Terminology
-----------

Source Object(s)

: The original object(s) that you are re-creating.  These meshes typically have a high polygon count with poor topology and edge flow (ex: result of Dyntopo in Sculpt Mode).

Target Object

: The new object that stores the retopologized surface.  This mesh typically has a low polygon count with good topology and edge flow.


Target and Source Objects
-------------------------

In RetopoFlow 1.x you were required to select the source and target objects explicitly, but in RetopoFlow 2.x the source and target objects are determined by RetopoFlow based on which mesh objects are selected, active, and visible.

The target object is either:

- the active mesh object if it is also selected (Object Mode)
- the mesh object currently being edited (Edit Mode)
- otherwise, a newly created mesh object

Any mesh object that is visible and not the target object is considered a source object.
This means that you can hide or move objects to hidden layers to change which source objects will be retopologized.
Note: only newly created or edited target geometry will snap to the source.


RetopoFlow Mode
---------------

The tools in RetopoFlow 1.x were set of disjoint tools, where you would need to quit one tool in order to start another.
Also, because we wrote RF 1.x tools separately, the visualizations and settings were not consistent.
Furthermore, the only indication that a tool was running in RetopoFlow 1.x was a small "Click for Help" button in the top-right corner, which is easily missed.

In RetopoFlow 2.x, we completely rewrote the framework so that RF acts like any other Blender Mode (like Edit Mode, Sculpt Mode, Vertex Paint Mode).
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
- I: Strokes

## Universal Shortcuts

The following shortcuts work across all the tools, although each tool may have a distinct way of performing the action.
For example, pressing G in Contours will slide the selected loop.

- A: deselect / select all
- ACTION drag: transform selection
- SELECT drag / SHIFT+SELECT drag: selection painting
- SHIFT+SELECT click: toggle selection
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

The Snap Verts button will snap either All vertices or only Selected vertices to the nearest point on the source meshes.

The Theme option changes the color of selected geometry.

![](help_themes.png)

When the Auto Collapse Options is checked, tool options will automatically collapse in the options panel when the current tool changes.


## Symmetry Options

The X,Y,Z checkboxes turn on/off symmetry or mirroring along the X, Y, and Z axes.
Note: symmetry utilizes the mirror modifier.

When symmetry is turned on, the mirroring planes can be visualized on the sources choosing either the Edge or Face option.
The Effect setting controls the strength of the visualization.
'''


help_contours = '''
# Contours Help

The Contours tool gives you a quick and easy way to retopologize cylindrical forms.
For example, it's ideal for organic forms, such as arms, legs, tentacles, tails, horns, etc.

The tool works by drawing strokes perpendicular to the form to define the contour of the shape.
Each additional stroke drawn will either extrude the current selection or cut a new loop into the edges drawn over.

You may draw strokes in any order, from any direction.

![](help_contours.png)


## Drawing

- ACTION: select and slide loop
- SELECT / SHIFT+SELECT: select edge
- CTRL+SELECT / CTRL+SHIFT+SELECT: select loop
- CTRL+ACTION: draw contour stroke perpendicular to form. newly created contour extends selection if applicable.
- A: deselect / select all
- F: Bridge selected edge loops

## Transform

- G: slide
- S: shift
- SHIFT+S: rotate

## Other

- X: delete/dissolve selected
- SHIFT+UP / SHIFT+DOWN: increase / decrease segment counts
- EQUALS / MINUS: increase / decrease segment counts

## Tips

- Extrude Contours from an existing edge loop by selecting it first.
- Contours works with symmetry, enabling you to contour torsos and other symmetrical objects!
'''


help_polystrips = '''
# PolyStrips Help

The PolyStrips tool provides quick and easy ways methods to map out key face loops for complex models.
For example, if you need to retopologize a human face, creature, or any other complex organic or hard-surface object.

PolyStrips works by hand-drawing stokes on to the high-resolution source object.
The strokes are instantly converted into spline-based strips of polygons.

Any continuous face loop of quads may be manipulated with PolyStrips via the auto-generated spline handles.

![](help_polystrips.png)

## Drawing

- ACTION: select quad then grab and move
- SELECT / SHIFT+SELECT: select quads
- CTRL+SELECT / CTRL+SHIFT+SELECT: select quad strip
- CTRL+ACTION: draw strip of quads
- F: adjust brush size
- A: deselect / select all

## Control Points

- ACTION: translate control point under mouse
- SHIFT+ACTION: translate all inner control points around neighboring outer control point
- CTRL+SHIFT+ACTION: scale strip width by click+dragging on inner control point

## Other

- X: delete/dissolve selected
- SHIFT+UP / SHIFT+DOWN: increase / decrease segment count of selected strip(s)
- EQUALS / MINUS: increase / decrease segment count of selected strip(s)
'''


help_polypen = '''
# PolyPen Help

The PolyPen tool provides absolute control for creating complex topology on a vertex-by-vertex basis (e.g., low-poly game models).
This tool lets you insert vertices, extrude edges, fill faces, and transform the subsequent geometry all within one tool and in just a few clicks.

![](help_polypen.png)

## Drawing

- SELECT / SHIFT+SELECT: select geometry
- CTRL+ACTION: insert geometry connected to selected geometry
- A: deselect / select all

## Other

- X: delete/dissolve selected

## Tips

Creating vertices/edges/faces is dependent on your selection:

- When nothing is selected, a new vertex is added.
- When a single vertex is selected, an edge is added between mouse and selected vertex.
- When an edge is selected, a triangle is added between mouse and selected edge.
- When a triangle is selected, a vertex is added to the triangle, turning the triangle into a quad

Selecting an edge and clicking onto another edge will create a quad in one step.

The PolyPen tool can be used like a knife, cutting vertices into existing edges for creating new topology routes.
'''

help_tweak = '''
# Tweak Help

The Tweak tool allows you to easily adjust vertex positions with a brush.

![](help_tweak.png)

- ACTION: move all vertices within brush radius
- SHIFT+ACTION: move only selected vertices within brush radius
- F: adjust brush size
- SHIFT+F: adjust brush strength
- CTRL+F: adjust brush falloff

## Options

Tweak has several options to control which vertices are or are not moved.

- Boundary: allow boundary vertices to be moved.
- Hidden: allow vertices that are behind geometry to be moved.
- Selected: limit transformation to selection
'''

help_relax = '''
# Relax Help

The Relax tool allows you to easily relax the vertex positions using a brush.

![](help_relax.png)

- ACTION: relax all vertices within brush radius
- SHIFT+ACTION: relax only selected vertices within brush radius
- F: adjust brush size
- SHIFT+F: adjust brush strength
- CTRL+F: adjust brush falloff

## Options

Relax has several options to control which vertices are or are not moved.

- Boundary: allow boundary vertices to be moved.
- Hidden: allow vertices that are behind geometry to be moved.
- Selected: limit transformation to selection
'''

help_loops = '''
# Loops Help

The Loops tool allows you to insert new edge loops along a face loop and slide any edge loop along the source mesh.

![](help_loops.png)

- CTRL+ACTION: insert edge loop
- SELECT / SHIFT+SELECT: select edge(s)
- CTRL+SELECT / CTRL+SHIFT+SELECT: select edge loop
- S: slide edge loop
'''

help_patches = '''
# Patches Help

The Patches tool helps fill in holes in your topology.
Select the strip of boundary edges that you wish to fill.

- SELECT / SHIFT+SELECT: select edge
- CTRL+SELECT / CTRL+SHIFT+SELECT: select edge loop
- SHIFT+UP / SHIFT+DOWN: adjust segment count
- CTRL+SHIFT+ACTION: toggle vertex as corner
- F: fill visualized patch

## Notes

The Patches tool currently only handles a limited number of selected regions.
More support coming soon!

- 2 connected strips in an L-shape
- 2 parallel strips: the two strips must contain the same number of edges
- 3 connected strips in a C-shape: first and last strips must contain the same number of edges
- 4 strips in a rectangular loop: opposite strips must contain the same number of edges

![](help_patches_2sides_beforeafter.png)

If no pre-visualized regions show after selection, no geometry will be created after pressing F.

Adjust the Angle parameter to help Patches determine which connected edges should be in the same strip.
Alternatively, you can manually toggle vertex corners using CTRL+SHIFT+ACTION.
'''

help_strokes = '''
# Strokes Help

The Strokes tool helps fill in holes in your topology.
This tool lets you insert edge strips and extruding edges by brushing a stroke on the source.

![](help_strokes.png)

## Drawing

- SELECT / SHIFT+SELECT: select geometry
- CTRL+SELECT / CTRL+SHIFT+SELECT: select edge loop
- CTRL+ACTION: insert edge strip / extrude selected geometry
- A: deselect / select all
- SHIFT+UP / SHIFT+DOWN: adjust segment count

## Other

- X: delete/dissolve selected

## Tips

Creating geometry is dependent on your selection:

- When nothing is selected, a new edge strip is added
- When an edge strip is selected and stroke is not a loop, the selected edge strip is extruded to the stroke
- When an edge loop is selected and stroke is a loop, the selected edge loop is extruded to the stroke

Note: only edges on boundary of target are considered in selection.

If stroke starts or ends on existing vertex, the Strokes tool will try to bridge the extruded geometry.
'''

help_stretch = '''
# Stretch Help

Foo Bar!!
'''
