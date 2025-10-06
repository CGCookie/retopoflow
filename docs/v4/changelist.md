# Change List

This document contains details about what has changed in Retopoflow in version 4.x.

### 4.0.0 beta 8

- Added Shift hotkey for moving in small increments while tweaking
- Improved drawing from the line of symmetry in PolyStrips
- Fixed PolyStrips width when the retopo object has non-uniform scale
- Fixed issue when deleting source objects while Retopoflow is running

### 4.0.0 beta 7

New:
- Retopoflow can now use non-mesh objects like curves and NURBS as sources as long as they have evaluated faces
- The existing faces are no longer selected after using PolyStrips to bridge
- Added RK4 as a new iteration method for Relax
    - RK4 is significantly more stable overall but may apply too much or too little strength in some cases
- Added preferences for disabling the help and pie menu hotkeys

Improved:
- Fixed random crashing in Strokes and PolyStrips in Blender 4.5
- Fixed occasional flipped normals in Contours
- Fixed several smaller issues

### 4.0.0 beta 6

New:
- Added preferences for what to name newly created retopology objects
- Added limits to how far Relax can move geometry as a percent of the brush radius
- Added option to apply retopology settings to non-Retopoflow tools
- Added option to revert retopology settings if they were applied to non-Retopoflow tools
- Added option to reset all Retopoflow tool settings

Improved:
- Improved drawing PolyStrips across and along the line of symmetry
- Increased default vertex selection distance in response to feedback
- Fixed PolyPen crash when closest edge has zero length
- Fixed PolyStrips crash when bridging two faces that share a vertex
- Fixed info menu icon missing in Blender 4.2
- Fixed twisting in Relax when rotation was not applied
- Re-enabled Face Angles and Face Radius in Relax by default
- Fixed crash when toggling maximize area
- Fixed issue when switching workspaces into Retopoflow
- Fixed retopology overlay not being enabled in all 3D Views in the workspace
- Fixed issue when packaging Retopoflow using Blender's extension build command


### 4.0.0 beta 5

New:
- You can now draw across the symmetry line in PolyPen, Contours, and PolyStrips

Improved:
- Fixed issue with Blender 4.5 on Mac

### 4.0.0 beta 4

New:
- Added quick hotkeys for Tweak and Relax
    - Shift drag for Relax
    - Ctrl Shift drag for Tweak
- Added option to use Blender's native transform to the Tweaking panel
    - Allows snapping to the edges and verts of the source object
    - Allows all bonus features like edge slide and constraints
    - Great for low poly or hard surface objects but not for high poly organic sculpts
- Strokes now takes into account the line of symmetry when a mirror is enabled
    - New options for behavior at the line of symmetry and determining which side is being mirrored
- PolyStrips has a new stroke preview that shows the width of the resulting strip.

Improved:
- Fixed issue with Tweak and Relax not working when the retopo object scale was extreme
- Fixed issue with transforms not working when the retopo object was not at world origin
- Fixed crash when restoring factory defaults while Retopoflow is enabled


### 4.0.0 beta 3

New:
- A Mirroring panel with quick actions was added to the tool settings
- There is now a warning if entering Retopoflow when no sources are detected
- You can now control the merge distance of the Strokes brush

Improved:
- All tools now use Face Nearest snapping by default
- Masking corners in Tweak and Relax now respects concave corners
- The Tweak and Relax brush falloff control is now much more user friendly
- Strokes bridges can now be untwisted in edge cases where they are twisted
- Improved visualization for proportional editing
- Fixed several issues with mirror modifier clipping
- Fixed conflict with keymaps that use Ctrl LMB Drag as box or lasso select
- Fixed case where Relax would mangle n-gons if they had multiple sides on a boundary
- Fixed case where Relax would affect vertices outside of the brush
- Fixed Strokes merge circle sometimes highlighting when the result would not be merged
- Fixed Retopoflow exiting when maximizing the 3D View

### 4.0.0 beta 2

New:
- Contours can now extend from the correct boundary regardless of which loop is selected
- Improved Relax performance
- Disabled Relax Face Radius and Face Angles options by default since they are not always stable
- Renamed Stroke Smoothing to Stabilize to match Blender's term
- Added Stabilize control to Strokes
- F1 now opens documentation and F2 reports an issue

Fixed:
- Fixed crash when a conflicting add-on listens for mesh changes and frees bmesh while we're using it
- Fixed issue with flipped normals when the retopology object's origin is far away

### 4.0.0 beta 1

Retopoflow 4 is a complete rewrite of Retopoflow that massively improves performance and integrates the tools directly into Blender's Edit Mode.

Some key changes include:
- General
    - The tools are now in the Edit Mode toolbar
    - Ctrl scroll is now used instead of Shift scroll for adjusting insert count
- Contours
    - A new Fast method was added, which can improve performance on dense meshes and work in some cases where the mesh is split
- PolyStrips
    - Proportional Editing can now be used for smoothly affecting the surrounding geometry while adjusting existing strips
    - The angle at which new strips are split to create sharp corners can now be specified
    - Strip spacing is now calculated in world space
- Strokes
    - Several new stroke shapes are now supported so drawing new geometry feels more natural
    - Extrudes can now match the curvature of the original geometry if the method is set to Adapt
    - A smoothing control has been added for naturally blending between strokes created at different angles
    - The new default insert count, Average, always creates perfectly even quads when extruding
