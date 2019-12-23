# Patches Help ![](patches_32.png width:32px;height:32px;padding:0px)

The Patches tool helps fill in holes in your topology.
Select the strip of boundary edges that you wish to fill.

![](help_patches_2sides_beforeafter.png)

## Actions

|  |  |  |
| --- | --- | --- |
| `Select` <br> `Shift+Select` | : | select edge |
| `Ctrl+Select` <br> `Ctrl+Shift+Select` | : | select edge loop |
| `Shift+Up` <br> `Shift+Down` | : | adjust segment count |
| `Ctrl+Shift+Action` | : | toggle vertex as corner |
| `F` | : | fill visualized patch |

## Notes

The Patches tool currently only handles a limited number of selected regions.
More support coming soon!

- 2 connected strips in an L-shape
- 2 parallel strips: the two strips must contain the same number of edges
- 3 connected strips in a C-shape: first and last strips must contain the same number of edges
- 4 strips in a rectangular loop: opposite strips must contain the same number of edges


If no pre-visualized regions show after selection, no geometry will be created after pressing F.

Adjust the Angle parameter to help Patches determine which connected edges should be in the same strip.
Alternatively, you can manually toggle vertex corners using `Ctrl+Shift+Action`.
