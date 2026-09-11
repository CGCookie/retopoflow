# Curve Handles

The non-brush Retopoflow tools can optionally show control points and handles for easily adjusting any selection as if it was a curve. They are only on by default in PolyStrips and Strokes.

The default hotkey for toggling the curve display in Retopoflow is `Alt C`. These curves can also be used outside of Retopoflow using the [Edit as Curve](./operators.html) operator, which shares the same hotkey.

Where the handles show up depends on your selection:
- A continuous path of edges will display the handles along the edges
- A continuous path of faces will display the handles in the center of the faces
- A patch of connected faces will display the handles around the perimeter of the selection

You can click and drag on any control point to adjust its location or on any handle to adjust its rotation and scale. You can also scale control points with `Alt LMB Drag` or rotate them with `Alt Shift LMB Drag`. Scaling the control point of a face strip with the hotkey also scales the width of the faces.

Adjusting a selected patch of faces is different from adjusting the perimiter loop by itself because, with the interior selected, all of the interior verts will be interpolated accordingly.

If you want to affect all surrounding verts, you can turn on proportional editing.

For edge loops and face patches, corners are detected based the edge angle. This angle threshold can be adjusted in the Curve Handles section of the Tweaking panel, along with how many control points are generated along the curve. For face loops, corners are tied to the topology rather than the angle.

There are a few types of curve handles that Retopoflow's control points can have:
- Endpoints are always drawn with a single handle
- Corners are given split, vector sytle handles
- Smooth curves are given automatic handles that only show the control point
- Automatic control points can be converted to aligned ones that have two handles locked together

You can swap handle types for any non-endpoint control point by hovering over it and pressing `V`. Converting to and from vector handles will add or remove sharp angles for edge strips or topological corners for face strips if the sourrounding topology is not already locked in.

When using the curve handles outside of Retopoflow, you can use the axis keys just like in Blender's transform operators to lock the transformation to an axis (`X`, `Y`, `Z`) or plane (`Shift X`, `Shift Y`, `Shift Z`).