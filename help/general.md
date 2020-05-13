# General Help

When RetopoFlow Mode is enabled, certain shortcuts are available regardless of the tool selected.
For tool-specific help, select the tool from the Tools panel, and either press `F2` or click Tool Help.

Click [here](table_of_contents.md) or press `Shift+F1` to see all of the built-in documentation.

Below is a brief description of some of the features in RetopoFlow.
For more details, see the tooltips when hovering or the product documentation page.


## RetopoFlow Shortcuts

|  |  |  |
| --- | --- | --- |
| `Esc`      | : | quit RetopoFlow |
| `Ctrl+S`   | : | save blend file |
| `F1`       | : | view general help (this document) |
| `Shift+F1` | : | view all help documents (table of contents) |
| `F2`       | : | view help for currently selected tool |
| `F9`       | : | toggle on/off main RF windows |

## Tool Shortcuts

Pressing the tool's shortcut will automatically switch to that tool.
The shortcuts for each tool is a number at top of keyboard (not numpad numbers).

|  |  |  |
| --- | --- | --- |
| `1` | : | Contours |
| `2` | : | PolyStrips |
| `3` | : | PolyPen |
| `4` | : | Relax |
| `5` | : | Tweak |
| `6` | : | Loops |
| `7` | : | Patches |
| `8` | : | Strokes |

Note: selection and the undo stack is maintained between tools.



## Universal Shortcuts

The following shortcuts work across all the tools, although each tool may have a distinct way of performing the action.
For example, pressing `G` in Contours will slide the selected loop.

|  |  |  |
| --- | --- | --- |
| `A` | : | deselect / select all |
| `Action` drag | : | transform selection |
| `Shift+Select` click | : | toggle selection |
| `Select` drag <br> `Shift+Select` drag | : | selection painting |
| `LMB+Double` <br> `Ctrl+Select` <br> `Ctrl+Shift+Select` | : | smart selection |
| `Ctrl+I` | : | invert selection |
| `G` | : | grab and move selected geometry |
| `X` | : | delete / dissolve selection |
| `Ctrl+Z` | : | undo |
| `Ctrl+Shift+Z` | : | redo |


## Defaults

The `Action` command is set to the left mouse button.

The `Select` command is set to the right mouse button.



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

![](help_themes.png)

The Target Drawing options control the rendering of the target mesh.
The Above and Below options control transparency of the target mesh.
Vertex Size and Edge Size control how large the vertices and how think the edges are.






## Symmetry Options

The X, Y, Z checkboxes turn on/off symmetry or mirroring along the X, Y, Z axes.
Note: symmetry utilizes the mirror modifier.

When symmetry is turned on, the mirroring planes can be visualized on the sources choosing either the Edge or Face option.
The Effect setting controls the strength of the visualization.
