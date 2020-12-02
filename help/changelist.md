# RetopoFlow {[rf version]}

This document contains details about what has changed in RetopoFlow since version 2.x.


## Version 2.x => 3.x Notes

In RetopoFlow&nbsp;2.x, we completely rewrote the framework so that RF acts like any other Blender mode (like Edit Mode, Sculpt Mode, Vertex Paint Mode).
Choosing one of the tools from the RetopoFlow panel will start RetopoFlow Mode with the chosen tool selected.

Although the underlying framework has changed significantly, RetopoFlow&nbsp;3.x uses a similar workflow to RetopoFlow&nbsp;2.x.

When RetopoFlow Mode is enabled, all parts of Blender outside the 3D view will be darkened (and disabled) and windows will be added to the 3D view.
These windows allow you to switch between RF tools, set tool options, and get more information.
Also, this one-time Welcome message will greet you.

Below are more details about the current version of RetopoFlow.


## Change List

Below is a list of changes from RetopoFlow&nbsp;3.0.0.

- PolyPen: added ability to move edge with drag after inserting new quad (before releasing insert)
- Strokes: added a simple visualization to show how a stroke will connect to hovered existing geometry.  Still a work-in-progress!
- Dissolving edges now dissolves verts (similar to Blender)
- Tweak/Relax: brushes now do not become fully opaque (nor fully transparent) when strength is set to 1 (or 0)
- Patches: improved code to detect good candidates for bridging two I-strips
- PolyPen: PP-specific pie menu now shown in help doc
- Added quit confirmation dialog when using {{done}}.  This dialog can be disabled.
- Other miscellaneous bug fixes


Below is a short list of major changes from RetopoFlow&nbsp;2.x.

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
