# ![](strokes-icon.png width:32px;height:32px;padding:0px) Strokes Help 

Shortcut: {{strokes tool}}


The Strokes tool helps fill in holes in your topology.
This tool lets you insert edge strips and extruding edges by brushing a stroke on the source.

![](help_strokes.png)

## Creating

|  |  |  |
| --- | --- | --- |
| {{insert}}         | : | insert edge strip and bridge from selected geometry |
| {{increase count}} | : | increase span/loop counts in bridge |
| {{decrease count}} | : | decrease span/loop counts in bridge |


## Selecting

|  |  |  |
| --- | --- | --- |
| {{select single, select single add}} | : | select edges |
| {{select smart, select smart add}}   | : | smart select loop |
| {{select paint, select paint add}}   | : | paint edge selection |
| {{select all}}                       | : | select / deselect all |
| {{deselect all}}                     | : | deselect all |


## Transforming

|  |  |  |
| --- | --- | --- |
| {{action}}        | : | grab and slide selected geometry under mouse |
| {{grab}}          | : | slide selected loop |

## Other

|  |  |  |
| --- | --- | --- |
| {{delete}}         | : | delete/dissolve selected |


## Tips

Creating geometry is dependent on your selection:

- When nothing is selected, a new edge strip is added
- When an edge strip is selected and stroke is not a loop, the selected edge strip is extruded to the stroke as a span
- When an edge loop is selected and stroke is a loop, the selected edge loop is extruded to the stroke as a loop

Note: only edges on boundary of target are considered in selection.

If stroke starts or ends on existing vertex, the Strokes tool will try to bridge the extruded geometry.
