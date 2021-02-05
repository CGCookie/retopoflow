# ![](knife-icon.png) Knife Help

Shortcut: {{knife tool}}

Quick Shortcut: {{knife quick}}

The Knife tool allows you to cut into the existing geometry similarly to Blender's Knife tool.

![](help_knife.png)

Note: the Knife tool will only cut into existing geometry; it will not create new vertices, edges, or faces.

If nothing is selected, the first insert will

- insert a new detached vertex if the mouse is hovering a face,
- split the hovered edge,
- select the hovered vertex, or
- set a knife starting point (does _not_ create a new vertex).

The subsequent insertions will cut in new edges, splitting faces and edges accordingly.

Note: an existing face will not be split until there are distinct entrance and exit vertices.
Until the face can split, the created vertices and edges will be non-manifold (possibly detached) geometry.


<!-- ![](help_polypen.png) -->

## Creating

|  |  |  |
| --- | --- | --- |
| {{insert}} | : | insert geometry connected to selected geometry |
| {{knife reset}} | : | resets the knife starting point |

## Selecting

|  |  |  |
| --- | --- | --- |
| {{select single, select single add}} | : | select geometry |
| {{select paint, select paint add}}   | : | paint geometry selection |
| {{select all}}                       | : | select / deselect all |
| {{deselect all}}                     | : | deselect all |


## Transforming

|  |  |  |
| --- | --- | --- |
| {{grab}}             | : | grab and move selected geometry |
| {{action}}           | : | grab and move selected geometry under mouse |
| {{smooth edge flow}} | : | smooths edge flow of selected geometry |

## Other

|  |  |  |
| --- | --- | --- |
| {{delete}} | : | delete/dissolve selected |



