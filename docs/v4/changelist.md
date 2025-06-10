# Change List

This document contains details about what has changed in Retopoflow in version 4.x.

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

