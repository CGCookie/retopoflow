# RetopoFlow FAQ

Below are answers to some common questions with RetopoFlow.


## Q: I cannot create new geometry!  Help!?

All of the tools (except Patches, Tweak, and Relax) create geometry using {{insert}} action.
Selection uses the {{select single}} action.
See [General Help](general.html) for more actions.


## Q: Why can I not select the geometry?

If you have symmetry turned on, you can only select the geometry on the non-mirrored side of the model.
Sometimes the geometry can snap to source surfaces that are "hidden" (see next Q).


## Q: Why is my geometry below the source mesh?

Sometimes when the source mesh contains objects that overlap (or nearly overlap), RetopoFlow will snap geometry to the inner surface.
Use the "Push and Snap" operation under Options > Target Cleaning to push the vertices out along normal before snapping them back to the source surface.


## Q: I have symmetry turned on, but why is it not working?

RetopoFlow's symmetry follows Blender's symmetry model, where symmetry is based on the origin of the target object.
In fact, enabling symmetry in RetopoFlow will add a Mirror Modifier to the target object in Blender.

RetopoFlow will create the new target object similar to Blender---at the 3D Cursor---so make sure to position correctly the 3D Cursor before creating a new target mesh.
If you have already started working on a target mesh, edit the origin as you would in Blender.


## Q: How do I continue working on a previous target?

To continue working on a target mesh, select the target, switch to Edit Mode, then choose one of the RetopoFlow tools from the RetopoFlow menu.

