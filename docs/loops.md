# ![](loops-icon.png) Loops Help

Shortcut: {{ keymaps.loops_tool }}


The Loops tool allows you to insert new edge loops along a face loop and slide any edge loop along the source mesh.
The Loops tool also works on any strip of edges.

![](help_loops.png)

## Creating

|  |  |  |
| :--- | :--- | :--- |
| {{ keymaps.insert }} | : | insert edge loop |


## Selecting

|  |  |  |
| :--- | :--- | :--- |
| {{ keymaps.select_single }}, {{ keymaps.select_single_add }} | : | select edges |
| {{ keymaps.select_smart }}, {{ keymaps.select_smart_add }}   | : | smart select loop |
| {{ keymaps.select_paint }}, {{ keymaps.select_paint_add }}   | : | paint edge selection |
| {{ keymaps.select_all }}                       | : | select / deselect all |
| {{ keymaps.deselect_all }}                     | : | deselect all |


## Transforming

|  |  |  |
| :--- | :--- | :--- |
| {{ keymaps.slide }}  | : | slide loop |
| {{ keymaps.action }} | : | if mouse over unselected geometry, smart select loop under mouse. <br> grab and slide selected geometry under mouse |
| {{ keymaps.smooth_edge_flow }} | : | smooths edge flow of selected geometry |