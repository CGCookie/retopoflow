# RetopoFlow Change List

This document contains details about what has changed in RetopoFlow since version 2.x.

### RetopoFlow 3.2.1&rarr;3.2.2

- ...

### RetopoFlow 3.2.0&rarr;3.2.1

- Fixed issue where normals are not computed correctly after applying symmetry
- Added shortcuts to increase and decrease brush radius for Tweak and Relax
- Fixed scrolling UI with trackpad
- Minor fixes across several tools (Contours, PolyStrips, Loops, Strokes, Relax, Tweak)
- Broad and general maintenance (code refactoring, cleaning, and commenting)
- Minor UI/UX improvements

### RetopoFlow 3.1.0&rarr;3.2.0

- Added builtin Keymap Editor (prototype)
- Significantly improved performance of tools with large target meshes!
- Target mesh visualization will now split (under the hood) when working on a small portion, improving feedback performance for some actions
- Shortest path selection keymap default changed from `Shift+Alt+LMB/RMB+Double` to `Ctrl+Shift+LMB/RMB+Click` to better match Blender
- Added ability to hide/reveal target mesh geometry
- Added button to recalculate normals in the Target Cleaning panel
- Added ability to Collapse Edges & Faces from delete/dissolve/collapse menu
- Tweak and Relax can now slide vertices along a boundary
- New Plane Symmetry Visualization setting, which is now default for better performance
- Added selection options to help with selecting hard-to-get vertices
- Improved Updater System
- General code cleanup and refactoring
- Works in Blender 2.83.0--3.0.0alpha (as of 2021.06.21)
- Many bug fixes and UX improvements

### RetopoFlow 3.00.2&rarr;3.1.0

- Knife is a new tool for cutting into existing geometry!
- Selection painting now selects geometry along shortest path from where mouse was first pressed to the geometry nearest current mouse position
- Tools are much more responsive when working on targets with high geometry counts
- Loops, Tweak, and Relax now have quick shortcuts
- The tools pie menu is now `Q` as well as `~` to help reduce finger gymnastics
- Major UI performance improvements from redesign and reimplementation of underlying UI system
- Improved smart selection and added actions for selecting geometry along shortest path
- Added button to push target vertices along normal before snapping to fix vertices snapping to inner source surfaces
- Added updater system for updating to specific branches or commits
- Added actions for hiding or revealing target geometry
- Added button on help system to view help documents in web browser and to open FAQ
- Added Blender operator for creating new target mesh based on active source mesh
- Visualizing non-manifold edges and detached vertices
- Many bug fixes and UX improvements

### RetopoFlow 3.00.1&rarr;3.00.2

- Tweak/Relax: added brush presets
- Symmetry: added button to apply symmetry, improved visualization
- PolyStrips/Strokes: brush settings now remain through sessions
- Strokes: added span insert modes (fixed, brush size) and brush size adjustment
- Improved ability to select geometry
- Added edge flow smooth feature
- Several bug fixes and UX improvements

### RetopoFlow 3.00.0&rarr;3.00.1

- PolyPen: added ability to move edge with drag after inserting new quad (before releasing insert)
- Strokes: added a simple visualization to show how a stroke will connect to hovered existing geometry.  Still a work-in-progress!
- Dissolving edges now dissolves verts (similar to Blender)
- Tweak/Relax: brushes now do not become fully opaque (nor fully transparent) when strength is set to 1 (or 0)
- Patches: improved code to detect good candidates for bridging two I-strips
- PolyPen: PP-specific pie menu now shown in help doc
- Added quit confirmation dialog when using {{done}}.  This dialog can be disabled.
- Added Delete/Dissolve pie menu using {{delete pie menu}}
- Other miscellaneous bug fixes

### RetopoFlow 2.x&rarr;3.00.0

- Left-mouse select is now a thing!
- Mouse dragging, clicking, and double-clicking are now possible actions.
- Some of the keymaps for some tools have changed to allow for LMB-select.
- The target mesh is what you are currently editing (Edit Mode), and the source meshes are any other visible mesh.
- RF now automatically detects many common mesh errors, such as vertices with invalid coordinates and inward-facing normals.
- Some RF tools have improved options.
- Major UI and UX improvements, including: tooltips, labels, help docs, gizmo rendering, minimizing main tool window
- Improved consistency across all tools
- Tools refresh faster when in middle of editing
- Code optimization, cleanup, and refactoring
- Reworked Auto Save and Save to be more intuitive and handle errors better
- Works in Blender 2.8x and 2.9x
- Fixed many issues

## Blender versions

As of the time of this release, RetopoFlow has been tested to work well with Blender&nbsp;2.83&nbsp;(LTS)--2.92α.

Note: This version of RetopoFlow will *not* work in Blender&nbsp;2.79b or earlier.

## Version 2.x&rarr;3.x Notes

In RetopoFlow&nbsp;2.x, we completely rewrote the framework so that RF acts like any other Blender mode (like Edit Mode, Sculpt Mode, Vertex Paint Mode).
Choosing one of the tools from the RetopoFlow panel will start RetopoFlow Mode with the chosen tool selected.

Although the underlying framework has changed significantly, RetopoFlow&nbsp;3.x uses a similar workflow to RetopoFlow&nbsp;2.x.

When RetopoFlow Mode is enabled, all parts of Blender outside the 3D view will be darkened (and disabled) and windows will be added to the 3D view.
These windows allow you to switch between RF tools, set tool options, and get more information.
Also, this one-time Welcome message will greet you.

## New Framework

Due to some significant changes in the Blender&nbsp;2.80 Python API, we had to rewrite a few key parts of RetopoFlow, specifically the rendering and UI.
Rather than keeping these updates only for RetopoFlow users, we decided to build the changes into a new framework called [CookieCutter](https://github.com/CGCookie/addon_common).
The CookieCutter framework has several brand new systems to handle states, UI drawing and interaction, debugging and exceptions, rendering, and much more.
CookieCutter was built from the ground up to be a maintainable, extensible, and configurable framework for Blender add-ons.

The new RetopoFlow sits on top of the CookieCutter framework, and we are excited to show off CookieCutter's features through RetopoFlow!

But with any unveiling on new things, there are new bugs and performance issues.
Our hope is that these problems will be much easier to fix in the new CookieCutter framework.
We will need your help, though.
If you notice a bug, please report it on the [Blender Market](https://blendermarket.com/products/retopoflow) or on [GitHub](https://github.com/CGCookie/retopoflow/issues).
