# Strokes Help ![](strokes_32.png width:32px;height:32px;padding:0px)

The Strokes tool helps fill in holes in your topology.
This tool lets you insert edge strips and extruding edges by brushing a stroke on the source.

![](help_strokes.png width:100%;border:0px)

## Drawing

|  |  |  |
| --- | --- | --- |
| `Select` <br> `Shift+Select` | : | select geometry |
| `Ctrl+Select` <br> `Ctrl+Shift+Select` | : | select edge loop |
| `Ctrl+Action` | : | insert edge strip / extrude selected geometry |
| `A` | : | deselect / select all |
| `Shift+Up` <br> `Shift+Down` | : | adjust segment count |

## Other

|  |  |  |
| --- | --- | --- |
| `X` | : | delete/dissolve selected |

## Tips

Creating geometry is dependent on your selection:

- When nothing is selected, a new edge strip is added
- When an edge strip is selected and stroke is not a loop, the selected edge strip is extruded to the stroke
- When an edge loop is selected and stroke is a loop, the selected edge loop is extruded to the stroke

Note: only edges on boundary of target are considered in selection.

If stroke starts or ends on existing vertex, the Strokes tool will try to bridge the extruded geometry.
