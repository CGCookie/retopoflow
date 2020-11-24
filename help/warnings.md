# RetopoFlow Warnings

RetopoFlow might present a warning if it detects a situation which is not ideal to start in.

![](warnings.png max-height:300px)

## Layout: Quad View / Multiple 3D Views

RetopoFlow is designed to work in a single 3D view.
Running RetopoFlow with Quad View turned on or with multiple 3D Views can result in RetopoFlow showing up in every 3D View, but only allowing interaction in one.

If either Lock to Object or Lock to 3D View are enabled, navigating in RetopoFlow can be incorrect.
Disable either of these settings in the 3D View Sidebar (`N`) before starting RetopoFlow.

![View Locks](warning_viewlock.png max-height:103px)

## Auto Save / Save

If Blender's auto save is disabled, any work done since the last time you saved can be lost if Blender crashes. To enable auto save, go Edit > Preferences > Save & Load > Auto Save.

If you are working on an unsaved blend file, your changes will be saved to a temporary file (see path below) when you press {{blender save}}.

Temporary file path: `{`options.get_auto_save_filepath()`}`

<input type="checkbox" value="options['check auto save']">Warn if auto save is disabled</input>

<input type="checkbox" value="options['check unsaved']">Warn if file is unsaved</input>


## Performance: Target/Sources Too Large

RetopoFlow is designed to perform well on _typical_ production retopology scenarios.
Running RetopoFlow on source/target meshes beyond a reasonable range is possible, but it will result in slower performance and a poorer experience.

A typical retopology workflow would involve <{[warning max sources]} polygons in total for all source meshes and <{[warning max target]} polygons for the target mesh. That's the point at which Blender starts to slow down, and there's not a lot we can do to be faster than Blender itself.

If your retopology target polygon count exceeds the {[warning max target]} count threshold, please try the following:

- Capture the surface details using a normal or a bump map instead of through geometry
- Use a Subdivision Surface modifier to smooth the mesh rather than additional edge loops
- Use the Mirror modifier and only retopologize half of the source

If your total source mesh(es) polygon count exceeds the {[warning max sources]} count threshold, try the following:

- Use a Decimate or Remesh modifier to reduce the overall count.
- Create a decimated copy of your source mesh and retopologize the copy. As long as it doesn't noticibly impact the silhouette of the object, decimation won't affect the resulting retopology at all
- Disable any Subdivision Surface modifiers or lower the Multiresolution Modifier display level
- Segment your sources into separate parts and retopologize one at a time



## Inverted Normals

If a source mesh is detected to have inward facing normals, RetopoFlow will report a warning.
Inward facing normals will cause new geometry to be created incorrectly or to prevent it from being selected.

Possible fix: exit RetopoFlow, switch to Edit Mode on the source mesh, recalculate normals, then try RetopoFlow again.

