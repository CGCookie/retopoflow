# General Help

Help Shortcut: {{ keymaps.general_help }}

When RetopoFlow Mode is enabled, certain shortcuts are available regardless of the tool selected.
For tool-specific help, select the tool from the Tools panel, and either press {{ keymaps.tool_help }} or click Tool Help.

View the [table of contents](table_of_contents.md) for all built-in documentation by pressing {{ keymaps.all_help }} at any time.

Below is a brief description of some of the features in RetopoFlow.
For more details, see the tooltips when hovering or the product documentation page.


## RetopoFlow Shortcuts

|  |  |  |
| :--- | :--- | :--- |
| {{ keymaps.done }}, {{ keymaps.done_alt0 }} | : | quit RetopoFlow |
| {{ keymaps.blender_save }}   | : | save blend file (same as Blender's save) |
| {{ keymaps.general_help }}   | : | view general help (this document) |
| {{ keymaps.all_help }}       | : | view all help documents (table of contents) |
| {{ keymaps.tool_help }}      | : | view help for currently selected tool |
| {{ keymaps.toggle_ui }}      | : | toggle on/off main RF windows |

## Tool Shortcuts

Pressing the tool's shortcut will automatically switch to that tool.
The shortcuts for each tool is a number at top of keyboard (not numpad numbers).

|  |  |  |  |
| :--- | :--- | :--- | :--- |
| {{ keymaps.contours_tool }}   | : | Contours | [help](contours.md) |
| {{ keymaps.polystrips_tool }} | : | PolyStrips | [help](polystrips.md) |
| {{ keymaps.strokes_tool }}    | : | Strokes | [help](strokes.md) |
| {{ keymaps.patches_tool }}    | : | Patches | [help](patches.md) |
| {{ keymaps.polypen_tool }}    | : | PolyPen | [help](polypen.md) |
| {{ keymaps.loops_tool }}      | : | Loops | [help](loops.md) |
| {{ keymaps.tweak_tool }}      | : | Tweak | [help](tweak.md) |
| {{ keymaps.relax_tool }}      | : | Relax | [help](relax.md) |

Note: selection and the undo stack is maintained between tools.

![Pie menu](pie_menu.png max-height:167.5px)

Press {{ keymaps.pie_menu }} at any time to show the tool pie menu.



## Universal Shortcuts

The following shortcuts work across all the tools, although each tool may have a distinct way of performing the action.
For example, pressing `G` in Contours will slide the selected loop.

|  |  |  |
| :--- | :--- | :--- |
| {{ keymaps.insert }}                            | : | create new geometry with current tool / apply relax or tweak |
| {{ keymaps.select_single }}, {{ keymaps.select_single_add }}  | : | select single |
| {{ keymaps.select_paint }}, {{ keymaps.select_paint_add }}    | : | selection painting |
| {{ keymaps.select_smart }}, {{ keymaps.select_smart_add }}    | : | smart selection |
| {{ keymaps.select_all }}                        | : | select / deselect all |
| {{ keymaps.deselect_all }}                      | : | deselect all |
| {{ keymaps.select_invert }}                     | : | invert selection |
| {{ keymaps.action }}                            | : | transform selection when mouse hovers selected geometry |
| {{ keymaps.grab }}                              | : | grab and move selected geometry |
| {{ keymaps.rotate }}                            | : | rotate selected geometry |
| {{ keymaps.scale }}                             | : | scale selected geometry |
| {{ keymaps.smooth_edge_flow }}                  | : | smooths edge flow of selected geometry |
| {{ keymaps.delete }}                            | : | delete / dissolve dialog |
| {{ keymaps.delete_pie_menu }}                   | : | delete / dissolve pie menu
| {{ keymaps.blender_undo }}                      | : | undo |
| {{ keymaps.blender_redo }}                      | : | redo |

Pressing {{ keymaps.delete }} will bring up the Delete/Dissolve dialog, allowing you to delete/dissolve the selected geometry.
Pressing and holding {{ keymaps.delete_pie_menu }} will bring up a Delete/Dissolve pie menu, which has fewer options than the dialog but is generally faster.


![Delete dialog and pie menu](delete_dialog_pie.png max-height:250px)



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