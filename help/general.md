# General Help

Help Shortcut: {{general help}}

When RetopoFlow Mode is enabled, certain shortcuts are available regardless of the tool selected.
For tool-specific help, select the tool from the Tools panel, and either press {{tool help}} or click Tool Help.

View the [table of contents](table_of_contents.md) for all built-in documentation by pressing {{all help}} at any time.

Below is a brief description of some of the features in RetopoFlow.
For more details, see the tooltips when hovering or the product documentation page.


## RetopoFlow Shortcuts

|  |  |  |
| --- | --- | --- |
| {{done}}          | : | quit RetopoFlow |
| {{blender save}}  | : | save blend file (same as Blender's save) |
| {{general help}}  | : | view general help (this document) |
| {{all help}}      | : | view all help documents (table of contents) |
| {{tool help}}     | : | view help for currently selected tool |
| {{toggle ui}}     | : | toggle on/off main RF windows |

## Tool Shortcuts

Pressing the tool's shortcut will automatically switch to that tool.
The shortcuts for each tool is a number at top of keyboard (not numpad numbers).

|  |  |  |  |
| --- | --- | --- | --- |
| {{contours tool}}   | : | Contours | [help](contours.md) |
| {{polystrips tool}} | : | PolyStrips | [help](polystrips.md) |
| {{strokes tool}}    | : | Strokes | [help](strokes.md) |
| {{patches tool}}    | : | Patches | [help](patches.md) |
| {{polypen tool}}    | : | PolyPen | [help](polypen.md) |
| {{loops tool}}      | : | Loops | [help](loops.md) |
| {{tweak tool}}      | : | Tweak | [help](tweak.md) |
| {{relax tool}}      | : | Relax | [help](relax.md) |

Note: selection and the undo stack is maintained between tools.

![Pie menu](pie_menu.png max-height:167.5px)

Press {{pie menu}} at any time to show the tool pie menu.



## Universal Shortcuts

The following shortcuts work across all the tools, although each tool may have a distinct way of performing the action.
For example, pressing `G` in Contours will slide the selected loop.

|  |  |  |
| --- | --- | --- |
| {{insert}}                            | : | create new geometry with current tool / apply relax or tweak |
| {{select single, select single add}}  | : | select single |
| {{select paint, select paint add}}    | : | selection painting |
| {{select smart, select smart add}}    | : | smart selection |
| {{select all}}                        | : | select / deselect all |
| {{select invert}}                     | : | invert selection |
| {{action}}                            | : | transform selection when mouse hovers selected geometry |
| {{grab}}                              | : | grab and move selected geometry |
| {{rotate}}                            | : | rotate selected geometry |
| {{scale}}                             | : | scale selected geometry |
| {{delete}}                            | : | delete / dissolve selection |
| {{blender undo}}                      | : | undo |
| {{blender redo}}                      | : | redo |




## General Options

The UI Scale option controls how large or small RetopoFlow will draw things.
Larger numbers produce larger fonts, thicker lines, larger vertices, etc.

If the Auto Hide Tool Options is checked, the options for the currently selected tool will be shown, but all other tool options will be hidden.

<!-- The Maximize Area button will make the 3D view take up the entire Blender window, similar to pressing `Ctrl+Up` / `Shift+Space` / `Alt+F10`. -->




### Target Cleaning

The Snap Verts buttons will snap either All vertices or only Selected vertices to the nearest point on the source meshes.

The Merge by Distance will merge vertices into a single vertex if they are within a given distance.




### View Options

The Clipping options control the near and far clipping planes.

The Theme option changes the color of selected geometry.

![](help_themes.png max-height:100px)

The Target Drawing options control the rendering of the target mesh.
The Above and Below options control transparency of the target mesh.
Vertex Size and Edge Size control how large the vertices and how think the edges are.






## Symmetry Options

The X, Y, Z checkboxes turn on/off symmetry or mirroring along the X, Y, Z axes.
Note: symmetry utilizes the mirror modifier.

When symmetry is turned on, the mirroring planes can be visualized on the sources choosing either the Edge or Face option.
The Effect setting controls the strength of the visualization.
