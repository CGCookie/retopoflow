# Helper Ops

Retopoflow includes a couple operators for assisting with retopology that can be accessed from any Retopoflow tool.


## Mesh Cleanup

Some operations that you can do in Edit Mode do not automatically snap the resulting mesh to the surface like RetopoFlow does. Or, you may find while working that you have common mesh issues like doubles or flipped faces.

To fix all of the common retopology problems at once, you can use Retopoflow's **Clean Up** operator. It can be found in the tool settings and in the pie menu (`W`) and be used on either all vertices or selected vertices only.

The clean up operator can optionally:
- Snap the mesh to the nearest source surface
- Merge by distance
- Recalculate and / or flip normals
- Fill holes
- Delete loose geometry, interior faces, or n-gons
- Triangulate concave faces, non-planar faces, or n-gons

If you are working on a very dense mesh and do not need all of those operations, consider turning the unnecissary ones off to speed up the operation.


## Topo Rotate

You can rotate the topology of any section of faces by selecting them and using the hotkey `Alt R`. This can be useful for re-aligning a grid fill, for example.