# ![](images/knife-icon.png) Knife Help

Shortcut: {{ site.data.keymaps.knife_tool }}

Quick Shortcut: {{ site.data.keymaps.knife_quick }}

The Knife tool allows you to cut into the existing geometry similarly to Blender's Knife tool.

![](images/help_knife.png)

Note: the Knife tool will only cut into existing geometry; it will not create new vertices, edges, or faces.

If nothing is selected, the first insert will

- insert a new detached vertex if the mouse is hovering a face,
- split the hovered edge,
- select the hovered vertex, or
- set a knife starting point (does _not_ create a new vertex).

The subsequent insertions will cut in new edges, splitting faces and edges accordingly.

Note: an existing face will not be split until there are distinct entrance and exit vertices.
Until the face can split, the created vertices and edges will be non-manifold (possibly detached) geometry.



## Creating


| :--- | :--- | :--- |
| {{ site.data.keymaps.insert }} | : | insert geometry connected to selected geometry |
| {{ site.data.keymaps.knife_reset }} | : | resets the knife starting point |

## Selecting


| :--- | :--- | :--- |
| {{ site.data.keymaps.select_single }}, {{ site.data.keymaps.select_single_add }} | : | select geometry |
| {{ site.data.keymaps.select_paint }}, {{ site.data.keymaps.select_paint_add }}   | : | paint geometry selection |
| {{ site.data.keymaps.select_path_add }}                  | : | select along shortest path |
| {{ site.data.keymaps.select_all }}                       | : | select / deselect all |
| {{ site.data.keymaps.deselect_all }}                     | : | deselect all |


## Transforming


| :--- | :--- | :--- |
| {{ site.data.keymaps.grab }}             | : | grab and move selected geometry |
| {{ site.data.keymaps.action }}           | : | grab and move selected geometry under mouse |
| {{ site.data.keymaps.smooth_edge_flow }} | : | smooths edge flow of selected geometry |

## Other


| :--- | :--- | :--- |
| {{ site.data.keymaps.delete }} | : | delete/dissolve/collapse selected |

