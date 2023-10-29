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
| {{done,done alt0}} | : | quit RetopoFlow |
| {{blender save}}   | : | save blend file (same as Blender's save) |
| {{general help}}   | : | view general help (this document) |
| {{all help}}       | : | view all help documents (table of contents) |
| {{tool help}}      | : | view help for currently selected tool |
| {{toggle ui}}      | : | toggle on/off main RF windows |

## Tool Shortcuts

Pressing the tool's shortcut will automatically switch to that tool.
The shortcuts for each tool is a number at top of keyboard (not numpad numbers).

|  |  |  |  |
| --- | --- | --- | --- |
| {{contours tool}}   | : | Contours   | [help](contours.md)   |
| {{polystrips tool}} | : | PolyStrips | [help](polystrips.md) |
| {{strokes tool}}    | : | Strokes    | [help](strokes.md)    |
| {{patches tool}}    | : | Patches    | [help](patches.md)    |
| {{polypen tool}}    | : | PolyPen    | [help](polypen.md)    |
| {{knife tool}}      | : | Knife      | [help](knife.md)      |
| {{loops tool}}      | : | Loops      | [help](loops.md)      |
| {{tweak tool}}      | : | Tweak      | [help](tweak.md)      |
| {{relax tool}}      | : | Relax      | [help](relax.md)      |
| {{select tool}}     | : | Select     | [help](select.md)     |

Note: selection and the undo stack is maintained between tools.

![Pie menu](images/pie_menu.png max-height:240px)

Press {{pie menu}} at any time to show the tool pie menu.


## Quick Tool Shortcuts

Pressing the tool's quick shortcut will temporarily switch to that tool.
RetopoFlow will switch back to the previously selected tool once you are done.

|  |  |  |
| --- | --- | --- |
| {{loops quick}}  | : | Loops |
| {{knife quick}}  | : | Knife |
| {{tweak quick}}  | : | Tweak |
| {{relax quick}}  | : | Relax |
| {{select quick}} | : | Select |


## Universal Shortcuts

The following shortcuts work across all the tools, although each tool may have a distinct way of performing the action.
For example, pressing `G` in Contours will slide the selected loop.

|  |  |  |
| --- | --- | --- |
| {{insert}}                                     | : | create new geometry with current tool / apply relax or tweak |
| {{select single, select single add}}           | : | select single |
| {{select paint, select paint add}}             | : | selection painting when mouse hovers geometry |
| {{select box}}                                 | : | box select when mouse does not hover geometry |
| {{select smart, select smart add}}             | : | smart selection |
| {{select path add}}                            | : | select along shortest path |
| {{select all}}                                 | : | select / deselect all |
| {{deselect all}}                               | : | deselect all |
| {{select invert}}                              | : | invert selection |
| {{select linked}}                              | : | select all linked |
| {{select linked mouse, deselect linked mouse}} | : | select / deselect all linked under mouse |
| {{hide selected}}                              | : | hide selected geometry |
| {{hide unselected}}                            | : | hide unselected geometry |
| {{reveal hidden}}                              | : | reveal hidden geometry |
| {{action}}                                     | : | transform selection when mouse hovers selected geometry |
| {{grab}}                                       | : | grab and move selected geometry |
| {{rotate}}                                     | : | rotate selected geometry |
| {{scale}}                                      | : | scale selected geometry |
| {{rip}}                                        | : | rip selected edge |
| {{rip fill}}                                   | : | rip and fill selected edge |
| {{smooth edge flow}}                           | : | smooths edge flow of selected geometry |
| {{delete}}                                     | : | delete / dissolve dialog |
| {{delete pie menu}}                            | : | delete / dissolve pie menu
| {{blender undo}}                               | : | undo |
| {{blender redo}}                               | : | redo |
| {{pin}}                                        | : | pin selected geometry |
| {{unpin}}                                      | : | unpin selected geometry |
| {{unpin all}}                                  | : | unpin all pinned geometry |
| {{mark seam}}                                  | : | mark selected edges as seam |
| {{clear seam}}                                | : | unmark selected edges as seam |


General selection has a few options to help with selecting troublesome vertices (ex: just below surface of source).
When `Occlusion Test` is enabled, geometry that is occluded by the source(s) are not selectable.
When `Backface Test` is enabled, geometry that is facing away are not selectable.
Disable these options to make geometry easier to select.

![Selection options](images/selection_options.png max-height:250px)




Pressing {{delete}} will bring up the Delete/Dissolve/Collapse dialog, allowing you to delete/dissolve/collapse the selected geometry.
Pressing and holding {{delete pie menu}} will bring up a Delete/Dissolve pie menu, which has fewer options than the dialog but is generally faster.


![Delete dialog and pie menu](images/delete_dialog_pie.png max-height:250px)



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

![](images/help_themes.png max-height:100px)

The Target Drawing options control the rendering of the target mesh.
The Above and Below options control transparency of the target mesh.
Vertex Size and Edge Size control how large the vertices and how thick the edges are.






## Mirror Options

The X, Y, Z checkboxes turn on/off mirroring along the X, Y, Z axes.
Note: these options utilize the mirror modifier.

When mirroring is turned on, the mirroring planes can be visualized directly using Plane option, or indirectly by coloring the sources choosing either the Edge or Face option.
The Effect setting controls the strength of the visualization.
