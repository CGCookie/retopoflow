# General Help

When RetopoFlow Mode is enabled, certain shortcuts are available regardless of the tool selected.
For tool-specific help, select the tool from the Tools panel, and either press `F2` or click Tool Help.

Click [here](table_of_contents.md) or press `Shift+F1` to see all of the built-in documentation.

Below is a brief description of some of the features in RetopoFlow.
For more details, see the tooltips when hovering or the product documentation page.


## RetopoFlow Shortcuts

|  |  |  |
| --- | --- | --- |
| `Esc` <br> `Tab` | : | quit RetopoFlow |
| `Shift+F1` | : | view all help documents |
| `F1` | : | view general help |
| `F2` | : | view tool help |
| `F9` | : | toggle on/off main RF windows |

## Tool Shortcuts

Pressing the tool's shortcut will automatically switch to that tool.
Note: selection and the undo stack is maintained between tools.

|  |  |  |
| --- | --- | --- |
| `Q` | : | Contours |
| `W` | : | PolyStrips |
| `E` | : | PolyPen |
| `R` | : | Relax |
| `T` | : | Tweak |
| `Y` | : | Loops |
| `U` | : | Patches |
| `I` | : | Strokes |


## Universal Shortcuts

The following shortcuts work across all the tools, although each tool may have a distinct way of performing the action.
For example, pressing `G` in Contours will slide the selected loop.

|  |  |  |
| --- | --- | --- |
| `A` | : | deselect / select all |
| `Action` drag | : | transform selection |
| `Shift+Select` click | : | toggle selection |
| `Select` drag <br> `Shift+Select` drag | : | selection painting |
| `Ctrl+Select` <br> `Ctrl+Shift+Select` | : | smart selection |
| `G` | : | grab and move selected geometry |
| `X` | : | delete / dissolve selection |
| `Ctrl+Z` | : | undo |
| `Ctrl+Shift+Z` | : | redo |


## Defaults

The `Action` command is set to the left mouse button.

The `Select` command is set to the right mouse button.


## General Options

The Maximize Area button will make the 3D view take up the entire Blender window, similar to pressing `Ctrl+Up` / `Shift+Space` / `Alt+F10`.

The Snap Verts button will snap either All vertices or only Selected vertices to the nearest point on the source meshes.

The Theme option changes the color of selected geometry.

![](help_themes.png)

When the Auto Collapse Options is checked, tool options will automatically collapse in the options panel when the current tool changes.


## Symmetry Options

The X, Y, Z checkboxes turn on/off symmetry or mirroring along the X, Y, Z axes.
Note: symmetry utilizes the mirror modifier.

When symmetry is turned on, the mirroring planes can be visualized on the sources choosing either the Edge or Face option.
The Effect setting controls the strength of the visualization.
