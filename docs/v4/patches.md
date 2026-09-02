# ![](/images/icons/patches-icon.png) Patches

The Patches tool fills holes in your retopology.
Select the boundary edges around a hole, check the preview, and press `F` to fill it with quads.

This is the Patches tool from Retopoflow 3, brought over so it is available while the new version is being developed.

## Filling

Select the strips of boundary edges that you want to fill. Patches groups the selected edges into strips and shows a preview of the quads it can create, with a label like `rect: 4x6` giving the edge counts of the strips.

Press `F` (or `Enter`) to create the previewed geometry. When nothing is previewed, `F` is left to Blender, so its own fill still works while the tool is active. The new faces are selected afterward so you can keep working on them with Tweak or Relax.

Once a patch is created its settings appear in the operator panel in the bottom left corner of the viewport, so you can change the counts or the corner placement and have the patch rebuilt without undoing first.

The new patch stays selected after filling, and its boundary still counts as boundary, so Patches waits for you to change the selection before offering another fill. This stops a second patch being stacked on top of the one you just made.

Patches can fill these arrangements of strips:

- 4 strips in a rectangular loop: opposite strips must contain the same number of edges
- 3 connected strips in a C-shape: the first and last strips must contain the same number of edges
- 2 connected strips in an L-shape. Each missing side is a curve that leaves its corner along the existing edge there, so the patch carries the flow of the surrounding mesh on through the corner, and arrives at the fourth corner with that tangent mirrored so it bows evenly. The fourth corner comes from the curvature of the two selected strips, and is drawn in when the sides lean into the patch, since two inward-swooping sides would otherwise meet in a point. Where a corner has no existing edge, the side is an arc bent to the curvature of the selected strips instead of a straight parallelogram
- 2 parallel strips, which get bridged: both strips must contain the same number of edges

Every selected strip shows its edge count between its corners, whether or not it can be filled, which makes it easy to see why two sides do not match. If no preview appears after selecting, pressing `F` creates nothing: the two ends of a C-shape may not match, for instance.

### Two sided patches

When only two sides are selected, whether that is a pair of parallel strips or a pair of loops, there is nothing to say how densely the gap should be filled, so Patches offers the same spacing methods as Contours.

**Average** matches the average edge length of the two sides so the new quads stay even. **Length** sizes each loop to a world space distance. **Fixed** uses **Crosses** exactly as set, which counts the loops added between the two sides and does not include the sides themselves. Crosses of 0 bridges them with a single band of quads.

Scrolling with `Ctrl Mouse Wheel` sets Crosses directly and switches the method to Fixed. Right after a fill it changes the count of the patch you just made, and for a grid fill it flips through its solutions, for as long as the redo panel is available.

If the two sides have different numbers of edges, the sides Patches is about to create close the region into a loop with four corners, so it is filled as a grid, exactly like an enclosed patch with uneven sides. The new vertices along those two created sides are drawn in the selected vertex colour, so you can see where the quads along them are divided. This needs an even number of edges in total. When one side has an odd count and the other an even one, no arrangement of quads can close the gap, and Patches offers nothing.

### Grid Fill

Any closed loop of boundary edges can be filled, even when its sides are uneven or it does not have four corners. Patches divides the loop into four sides the same way Blender's Grid Fill does, always producing a rectangular block of quads, and picks corners where the loop actually bends.

A loop can be divided into quads in several ways. **Solution** picks one: 1 is the automatic choice, the split that keeps the quads squarest with its corners on the loop's real bends, and higher values flip through the alternatives in order of merit, wrapping round to the start. A new selection always begins at 1. **Offset** rotates the four corners around the loop. `Ctrl Mouse Wheel` flips through the solutions and `Shift Mouse Wheel` adjusts the offset. Right after a fill, `Shift Mouse Wheel` adjusts the offset of the patch you just made instead, and when there is no patch to turn it topo-rotates the selection, the same way twist works in Contours.

A loop with an odd number of edges cannot be closed with quads alone, so Patches offers nothing for it. Add or remove one edge to fix it.

## Lofting

Select two closed loops that face each other and Patches bridges them with a tube of quads instead of filling each one separately. Both loops must have the same number of vertices.

Patches works out which vertex of one loop pairs with which vertex of the other, so the bridge does not come out twisted. It matches the two loops both by which vertices sit closest together and by where the loops turn sharply, so corners meet corners even when one loop is larger or sits off to one side. Use **Twist** to rotate the pairing by hand, or scroll with `Shift Mouse Wheel`.

How many loops are created between the two is set by the spacing methods described above.

Two loops that sit in the same plane side by side are treated as two separate holes and filled individually, not lofted. To cap a loop that faces another selected loop, select it on its own.

New vertices are placed by blending the boundary strips across the hole, then projected onto the source surface along the surface normal. With a Mirror modifier that clips, vertices that land on the mirror plane are pinned to it.

**Smooth** relaxes the new vertices before they are created, evening out the spacing of the interior loops. It is off by default so the fill follows the boundary strips exactly; raise it when the boundary spacing is uneven.

### When Patches declines to fill

Patches checks the result before offering it. Each new vertex is placed by blending the sides of the patch and is then projected onto the source surface. On a well behaved surface neighbouring vertices all move in much the same direction, even when they move a long way. Where a patch spans a gap, or a concave area where the nearest surface is somewhere unrelated, every vertex finds its own piece of the source and the result is a noisy tangle that follows nothing.

When that happens no geometry is offered. Select a smaller area, or add some geometry across the gap first, and try again.

Patches only ever fills the empty side of a boundary. Every boundary edge already has a face on one side, so a fill that would land on that same side, such as the outline of a mesh island, is not offered. Selecting the outline of a hole inside a mesh fills the hole.

## Corners

Patches decides where one strip ends and the next begins by how far the boundary bends at each vertex. Where it turns by more than the **Split Angle** setting (default 60°, measured as a deviation from straight, the same way as in PolyStrips) the vertex becomes a corner. Adjust the setting to change how a selection splits into strips.

You can also toggle a vertex manually. Hold `Ctrl` and `LMB Click` on a selected vertex to force it to be a corner, or to force it not to be one if Patches already treats it as a corner. Corners are drawn as highlighted points.

Press `Esc` to clear all manually toggled corners. They are also cleared when you fill or switch tools.

## Selecting

The default selection mode for Patches is Edge. `LMB Double Click` selects the boundary loop or strip under the mouse.

General selection options for all tools can be read about on the [Retopoflow Mode](general.html) docs page under Selection.

## Transforming

Click and drag on selected geometry to move it, or press `G`. The preview updates once you release.
