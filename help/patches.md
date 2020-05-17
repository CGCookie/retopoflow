# Patches Help ![](patches_32.png width:32px;height:32px;padding:0px)

Shortcut: {{patches tool}}


The Patches tool helps fill in holes in your topology.
Select the strip of boundary edges that you wish to fill.

![](help_patches_2sides_beforeafter.png)

## Creating

|  |  |  |
| --- | --- | --- |
| {{action alt0}}    | : | toggle vertex as a corner |
| {{fill}}           | : | create visualized patch |
| {{increase count}} | : | increase segment count when bridging |
| {{decrease count}} | : | decrease segment count when bridging |


## Selecting

|  |  |  |
| --- | --- | --- |
| {{select single, select single add}} | : | select edge |
| {{select smart, select smart add}}   | : | smart select boundary edges |
| {{select paint, select paint add}}   | : | paint edge selection |
| {{select all}}                       | : | deselect / select all |


## Transforming

|  |  |  |
| --- | --- | --- |
| {{action}}  | : | grab and move selected geometry under mouse |
| {{grab}}    | : | grab and move selected geometry |


## Notes

The Patches tool currently only handles a limited number of selected regions.
More support coming soon!

- 2 connected strips in an L-shape
- 2 parallel strips: the two strips must contain the same number of edges
- 3 connected strips in a C-shape: first and last strips must contain the same number of edges
- 4 strips in a rectangular loop: opposite strips must contain the same number of edges


If no pre-visualized regions show after selection, no geometry will be created after pressing {{fill}}.

Adjust the Angle parameter to help Patches determine which connected edges should be in the same strip.
Alternatively, you can manually toggle vertex corners using {{action alt0}}.
