# RetopoFlow Change List

This document contains details about what has changed in RetopoFlow since version 2.x.

### RetopoFlow 3.3.0&rarr;3.4.0

- Added `view_roll` keymap
- Fixed compatibility with Blender 2.93--3.2
- Improved performance when navigating
- Improved error handling during startup
- Continued removing code that uses `bgl` module
- Added keymap to select all linked
- Fixed crashing bug when cutting across non-manifold edge using Contours
- Fixed bug when using knife where no source geometry exists
- Added `plus` key to default for increasing vertex count (Contours, PolyStrips, etc.)
- Fixed and improved recovery of auto saves
- Improved reporting and operations with auto saves
- Fixed NDOF inputs
- Fixed bug when cancelling Contours cut
- Improved indication of warnings
- Consistent fixed span/segment count for all insertions with Strokes
- Added button to continue editing with active mesh as target
- Improved start up feedback
- Added simple rip and rip fill to PolyPen

### RetopoFlow 3.2.9&rarr;3.3.0

- New undo system
- New recovery system
- Revamped action system
- Added button to open online documents for Warning Details
- Improved error handling at startup
- Refactored large sections and cleaned code
- Removed code for Blender 2.79 and earlier
- Reorganized file structure
- Improved Hive integration
- Added option to keep viewport orbit center when nothing is selected
- Added options to control Tweak/Relax brush alpha
- Fixed disappearing text on detail UI elements at certain Blender UI scales
- Fixed crash when exiting RetopoFlow after starting in wireframe mode
- Fixed issue where selected but hidden geometry could get deleted
- Turning off shading optimization now restores original shading settings
- General code improvement

### RetopoFlow 3.2.8&rarr;3.2.9

- Fixed bug where scaling of target and viewport changes with save/undo
- Fixed rare bug in PolyPen

### RetopoFlow 3.2.7&rarr;3.2.8

- Fixed bug where checkedness of alert checkboxes is not saved
- Fixed bug with Stroke snapping distance

### RetopoFlow 3.2.6&rarr;3.2.7

- Fixed bug when pressing MMB while moving geometry with LMB
- Significantly improved Auto Save and Auto Save recovery
- Added quick bail if unexpected exceptions occur to prevent work loss
- Temp mesh is used when updating to prevent work loss
- PolyPen now has option to adjust distance for inserting vertex into edge
- Fixed issue where loose verts and edges are unselectable
- Fixed issue with crashing when using tablet
- Improved auto adjustment of view clipping
- Improved stability of Strokes and PolyPen
- Added option for snapping to geometry while using Strokes instead of using brush radius
- Checking for invalid characters in add-on folder name
- Improved and debugged UI code
- Removed RetopoFlow menu from all modes other than Object and Mesh Edit
- Moved version number from the menu title to the menu header

### RetopoFlow 3.2.5&rarr;3.2.6

- Vertex pinning and unpinning, where pinned vertices cannot be moved
- Seam edges can be pinned
- Option to hide mouse cursor when moving geometry
- Keymap editor improvements: shows keys for done and toggle UI, added Blender passthrough, fixed many bugs
- Fixed bug where modifier key states would be out of sync if pressed or unpressed while changing view
- Added auto clip adjustment setting, which adjusts clip settings based on view position and distance to bbox of sources
- Fixed visualization bug where depth test wasn't always enabled and depth range might not be [0,1]
- Added check for and button to select vertices that are on the "wrong" side of symmetry planes.
- Fixed many bugs and cleaned up code

### RetopoFlow 3.2.4&rarr;3.2.5

- Worked around a major crashing bug in Blender 3.0 and 3.1
- Overhauled RetopoFlow's Blender menu, by adding custom icons to buttons, improving the wording, buttons to online help documents, buttons to updater
- Modifier keys (i.e., `Ctrl`, `Shift`, `Alt`, `OSKey`) now show OSX-specific symbols (i.e., `^`, `⇧`, `⌥`, `⌘`) for better readability on OSX machines
- Improved keymap editor
- Minor improvements for smaller screens
- Started working on improvements for error reporting
- Started refactoring code for major changes to Blender 3.0+ API, such as removing dependence on the deprecated `bgl` module
- Many bug fixes
- General cleaning up of old code and adding comments

### RetopoFlow 3.2.3&rarr;3.2.4

- Fixed visual bug that affected machines with Apple's M1 processor (issue #915)

### RetopoFlow 3.2.2&rarr;3.2.3

- Worked around a bug with Apple M1 MacBook Pro / Intel graphics card where Blender would crash on load
- Warn if a source or the target has non-invertible transformation matrix
- Minor change due to Blender 3.0 deprecating `blf.KERNING_DEFAULT`

### RetopoFlow 3.2.1&rarr;3.2.2

- Fixed major updater bug
- Fixed bug where Brush Falloff with `Ctrl+F` was not working

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
