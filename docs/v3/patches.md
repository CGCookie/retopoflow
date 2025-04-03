# ![](images/patches-icon.png) Patches Help

Shortcut: {{ site.data.keymaps.patches_tool }}


The Patches tool helps fill in holes in your topology.
Select the strip of boundary edges that you wish to fill.

![](images/help_patches.png)

## Creating


| :--- | :--- | :--- |
| {{ site.data.keymaps.action_alt1 }}    | : | toggle vertex as a corner |
| {{ site.data.keymaps.fill }}           | : | create visualized patch |
| {{ site.data.keymaps.increase_count }} | : | increase segment count when bridging |
| {{ site.data.keymaps.decrease_count }} | : | decrease segment count when bridging |


## Selecting


| :--- | :--- | :--- |
| {{ site.data.keymaps.select_single }}, {{ site.data.keymaps.select_single_add }} | : | select edge |
| {{ site.data.keymaps.select_smart }}, {{ site.data.keymaps.select_smart_add }}   | : | smart select boundary edges |
| {{ site.data.keymaps.select_paint }}, {{ site.data.keymaps.select_paint_add }}   | : | paint edge selection |
| {{ site.data.keymaps.select_path_add }}                  | : | select edges along shortest path |
| {{ site.data.keymaps.select_all }}                       | : | select / deselect all |
| {{ site.data.keymaps.deselect_all }}                     | : | deselect all |


## Transforming


| :--- | :--- | :--- |
| {{ site.data.keymaps.action }}  | : | grab and move selected geometry under mouse |
| {{ site.data.keymaps.grab }}    | : | grab and move selected geometry |


## Notes

The Patches tool currently only handles a limited number of selected regions.
More support coming soon!

- 2 connected strips in an L-shape
- 2 parallel strips: the two strips must contain the same number of edges
- 3 connected strips in a C-shape: first and last strips must contain the same number of edges
- 4 strips in a rectangular loop: opposite strips must contain the same number of edges


If no pre-visualized regions show after selection, no geometry will be created after pressing {{ site.data.keymaps.fill }}.

Adjust the Angle parameter to help Patches determine which connected edges should be in the same strip.
Alternatively, you can manually toggle vertex corners using {{ site.data.keymaps.action_alt0 }}.
