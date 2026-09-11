# Helper Ops

Retopoflow includes a handfull of operators for assisting with modeling and retopology. Those that work outside of Retopoflow mode can be found in the right click context menu or in Edit Mode's Vertex, Edge, or Face menus. You can modify the hotkeys for these operators or restrict them to only fire in Retopoflow mode in the add-on preferences.


## Auto Fill

The goal of Auto Fill is for you to be able to press `F` to fill anything. It is context-aware and responds based on the selection.

It uses the same algorithm and has all the same options as [Patches](patches.html). You can get used to how it works by using [Patches](patches.html), which has a live preview.


## Relax

Smooth vertices using the same algorithm and settings as the [Relax Brush](relax.html). The unique advantage of the operator version is that it can work on specific selections that may be too complex or too fine for the brush to handle well, such as a long loop winding around a mesh. It works great with proportional editing, where the falloff can curve around and follow the selection.

There are a few **Shaping** options that help control the size of the result and combat the shrinkage that often comes with smoothing:
- Preserve Volume
- Interpolate Loop Curvature
- Slide Edges

There are also **Snapping** options:
- Original Mesh will keep the surface curvature of the mesh the same while repositioning the vertices along it
- The various object options allow you to snap to the surface of objects in the scene
    - Including snapping to their nearby edge attributes such as seams or sharp edges


## Even

Evenly space vertices based on the selection, preserving sharp angles by default.
- Edge loops are fit to a curve path and evenly spaced along it. The **Smooth Loops** option changes the fit curve from linear to cubic.
- Faces either have their edges averaged or their angles and areas averaged based on the **Equalize Faces** option.
- All remaining edges simply have their lengths averaged.

Even has all the same snapping options as the Relax operator above.


## Twist Loops

Rotate loops along their individual axes. **Retain Shape** slides the vertices along the original curve of the loop when on and rotates the loop as a whole while off.

The tool automatically detects the loops in the selection to twist and interpolates everything else accordingly, so you can select whole areas at a time. A continuous path of selected edges counts as a loop even if it contains poles. It works great with proportional editing and finds all the appropriate loops in the falloff radius as well.


## Edit as Curve

Adjust any selection of connected edges or faces using curve handles. This operator is only available outside of Retopoflow mode, since in Retopoflow mode you can enable or disable the curve handle overlays at any time using the same default hotkey, `Alt C`.


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


## Rotate Topology

You can rotate the topology of any section of faces by selecting them and using the hotkey `Alt R`. This can be useful for re-aligning a grid fill, for example.


## Diamond Bevel

Quickly add creases to a set of connected edges. The result is the same as beveling with two segments, dissolving the resulting traingles, and manually welding and adjusting the diamond quad left over... but without all that work. When the set of edges runs off the boundary, that end will run straight off rather than being capped with a diamond quad. The **Flatten** options determine how the inner loop is interpolated on a curved surface.


## Adjust Loop Count

Resamples the vert or edge count on any edge strip or face strip that is not already locked in by surrounding topology.