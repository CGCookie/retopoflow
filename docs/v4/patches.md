# ![](/images/icons/patches-icon.png) Patches

The Patches tool is a context-aware filling tool that creates new faces based on the selected topology.

## Filling

Select the edges or vertices along the boundary that you want to fill. Patches groups the selected edges into strips and shows a preview of the faces it will create.

Press `F`, `Enter`, or `Ctrl LMB` to create the previewed geometry. When nothing is previewed, `F` falls through to Blender's hotkey for Make Edge/Face from Vertices, so you can still use it for things like turning a group of selected faces into an n-gon.

When boundary edges or vertices are selected and the preview is displayed, the settings for the patch will appear in the tool properties. These same settings are also available in the redo panel after the patch has been created.

Some fill patterns depend on which vertices are considered to be the **corners** of the patch. These corners appear as yellow dots which can be dragged around. You can toggle corners on or off for a vertex using `Ctrl LMB`, and reset to the default corners with `Esc` or by using the Reset Corners button in the tool settings. The **Split Angle** setting controls the threshold for which these corners are automatically placed.

The **Smooth** property relaxes the new vertices inside of the patch.

Patches can fill these selections:

### Corner Vertices
Select a vertex that has two connected boundary edges wich are at an angle to fill a quad from those edges.

### Straight Edges
Select one or more boundary edges in a row that do not have a sharp angle to fill one step outwards. The number of steps and the width of each step can be controlled in the tool properties or with `Ctrl Scroll` and `Shift Scroll`, allowing you to extend out whole patches at a time. If the selected edges have a sharp angle at the end, the extrusion will step to that next vertex. If the selected edges are wires with no faces on either side, the fill will take the side that the cursor is on.

### L Shapes
Select two connected strips of edges that have a corner between them to form a rectangular patch of quads.

### Bridges
Select two strips of boundary edges that are roughly parallel to connect them with a bridge. You can use `Ctrl Scroll` to adjust the number of cuts in the bridge.

### C Shapes
Select three strips of connected edges that have two interior corners to fill the enclosed area.

### Holes
Select the entirety of a closed boundary loop to fill the hole. Complex hole shapes are not all supported, so it is recommended to fill one section at a time in those cases.

### Lofts
Select two closed loops that are roughly facing each other to bridge between them with a loft. You can use `Ctrl Scroll` to adjust the number of cuts and `Shift Scroll` to control the twist.

For Bridges, C Shapes, and Holes, if the selected edge counts do not match, you will have a variety of options for how to complete the bridge using the **Solution** and **Offset** properties. Quads will be used whenever possible, with an inner n-gons or triangle offered as solutions when an all quads pattern is not possible. You can scroll through Solutions with `Ctrl Scroll` and through Offsets, the varients of that solution, with `Shift Scroll`.

If a solution contains a pole, a vert with three or five connected edges, it will be displayed with a control point that can be dragged to reposition it.

## Selecting

The default selection mode for Patches is Vertex + Edge.
General selection options for all tools can be read about on the [Retopoflow Mode](general.html) docs page under Selection.

## Transforming

Click and drag on selected geometry to move it, or press `G`. The preview updates once you release.
