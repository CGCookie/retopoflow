# ![](polystrips-icon.png) PolyStrips Help

Shortcut: {{ keymaps.polystrips_tool }}


The PolyStrips tool provides quick and easy ways to map out key face loops for complex models.
For example, if you need to retopologize a human face, creature, or any other complex organic or hard-surface object.

PolyStrips works by hand drawing strokes on to the high-resolution source object.
The strokes are instantly converted into spline-based strips of polygons.

Any continuous quad strip may be manipulated with PolyStrips via the auto-generated spline handles.

![](help_polystrips.png)

## Creating

|  |  |  |
| :--- | :--- | :--- |
| {{ keymaps.insert }}         | : | draw strip of quads |
| {{ keymaps.brush_radius }}   | : | adjust brush size |
| {{ keymaps.action }}         | : | grab and move selected geometry |
| {{ keymaps.increase_count }} | : | increase segment counts in selected strip |
| {{ keymaps.decrease_count }} | : | decrease segment counts in selected strip |


## Selecting

|  |  |  |
| :--- | :--- | :--- |
| {{ keymaps.select_single }}, {{ keymaps.select_single_add }} | : | select face |
| {{ keymaps.select_paint }}, {{ keymaps.select_paint_add }}   | : | paint face selection |
| {{ keymaps.select_all }}                       | : | select / deselect all |
| {{ keymaps.deselect_all }}                     | : | deselect all |


## Control Points

The following actions apply to when the mouse is hovering over control points of selected strip.

|  |  |  |
| :--- | :--- | :--- |
| {{ keymaps.action }}      | : | grab and move control point under mouse |
| {{ keymaps.action_alt0 }} | : | grab and move all inner control points around neighboring outer control point |
| {{ keymaps.action_alt1 }} | : | scale strip width by dragging on inner control point |


## Transforming

|  |  |  |
| :--- | :--- | :--- |
| {{ keymaps.action }}  | : | grab and move selected geometry under mouse |
| {{ keymaps.grab }}    | : | grab and move selected geometry |


## Other

|  |  |  |
| :--- | :--- | :--- |
| {{ keymaps.delete }} | : | delete/dissolve selected |