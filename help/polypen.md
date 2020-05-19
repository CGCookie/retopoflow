# PolyPen Help ![](polypen_32.png width:32px;height:32px;padding:0px)

Shortcut: {{polypen tool}}


The PolyPen tool provides absolute control for creating complex topology on a vertex-by-vertex basis (e.g., low-poly game models).
This tool lets you insert vertices, extrude edges, fill faces, and transform the subsequent geometry all within one tool and in just a few clicks.

![](help_polypen.png)

## Creating

|  |  |  |
| --- | --- | --- |
| {{insert}} | : | insert geometry connected to selected geometry |
| {{insert alt1}} | : | insert only edges connected to selected geometry |

## Selecting

|  |  |  |
| --- | --- | --- |
| {{select single, select single add}} | : | select geometry |
| {{select paint, select paint add}} | : | paint geometry selection |
| {{select all}} | : | deselect / select all |


## Transforming

|  |  |  |
| --- | --- | --- |
| {{grab}}   | : | grab and move selected geometry |
| {{action}} | : | grab and move selected geometry under mouse |


## Other

|  |  |  |
| --- | --- | --- |
| {{delete}} | : | delete/dissolve selected |


## Tips

Creating vertices/edges/faces is dependent on your selection:

- When nothing is selected, a new vertex is added.
- When a single vertex is selected, an edge is added between mouse and selected vertex.
- When an edge is selected, a triangle is added between mouse and selected edge.
- When a triangle is selected, a vertex is added to the triangle, turning the triangle into a quad

Selecting an edge and clicking onto another edge will create a quad in one step.

The PolyPen tool can be used like a knife, cutting vertices into existing edges for creating new topology routes.
