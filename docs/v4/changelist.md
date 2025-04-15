# Change List

This document contains details about what has changed in Retopoflow in version 4.x.

### 4.0.0 alpha

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

