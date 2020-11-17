# RetopoFlow Warnings Details

This document provides details about various warnings that RetopoFlow might present.

Note: some of these warnings are due to how RetopoFlow is currently implemented, and others are due to how the Blender Python API works.
We are continually working on improving where we can, but there may simply be limitations that we are unable to work around.



## Performance: Target/Sources Too Large

RetopoFlow is designed to perform well on _typical_ retopology scenarios.
Running RetopoFlow on source/target meshes beyond a reasonable range is possible, but it will result in slower performance and poorer experience.

A typical retopology workflow would involve <{[warning max sources]} polygons in total for all source meshes and <{[warning max target]} polygons for the target mesh.

If your target polygon count exceeds the {[warning max target]} count threshold, try the following:

- Capture the surface details using various maps (normal, bump, displacement) instead of through geometry
- Reduce the loop count in the target and use Subdivision Surface and Shrinkwrap modifier to increase polycount and improve silhouette as needed
- Use the Mirror modifier and only retopologize half of the source

If your total source mesh(es) polygon count exceeds the {[warning max sources]} count threshold, try the following:

- Use a Decimate or Remesh modifiers to reduce the overall count
- Disable any Subdivision Surface modifiers
- Segment your sources into separate parts and only retopologize one at a time



## Layout: Quad View / Multiple 3D Views

RetopoFlow is designed to work in a single 3D view.
Running RetopoFlow with Quad View turned on or with multiple 3D Views can result in RetopoFlow showing up in every 3D View, but only allowing interaction in one.


## Auto Save / Save

If Blender's auto save is disabled, any work done since the last time you saved can be lost if Blender crashes.
To enable auto save, go Edit > Preferences > Save & Load > Auto Save.

If you are working on an _unsaved_ blend file, your changes will be saved to `{`options.get_auto_save_filepath()`}` when you press {{blender save}}.


