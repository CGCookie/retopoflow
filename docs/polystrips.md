# ![](polystrips-icon.png) PolyStrips Help

![](help_polystrips.png)

Shortcut: {{ site.data.keymaps.polystrips_tool }}

The PolyStrips tool provides quick and easy ways to map out key face loops for complex models.
For example, if you need to retopologize a human face, creature, or any other complex organic or hard-surface object.

PolyStrips works by hand drawing strokes on to the high-resolution source object.
The strokes are instantly converted into spline-based strips of polygons.

Any continuous quad strip may be manipulated with PolyStrips via the auto-generated spline handles.

## Creating


| :--- | :--- | :--- |
| {{ site.data.keymaps.insert }}         | : | draw strip of quads |
| {{ site.data.keymaps.brush_radius }}   | : | adjust brush size |
| {{ site.data.keymaps.action }}         | : | grab and move selected geometry |
| {{ site.data.keymaps.increase_count }} | : | increase segment counts in selected strip |
| {{ site.data.keymaps.decrease_count }} | : | decrease segment counts in selected strip |


## Selecting


| :--- | :--- | :--- |
| {{ site.data.keymaps.select_single }}, {{ site.data.keymaps.select_single_add }} | : | select face |
| {{ site.data.keymaps.select_paint }}, {{ site.data.keymaps.select_paint_add }}   | : | paint face selection |
| {{ site.data.keymaps.select_path_add }}                  | : | select faces along shortest path |
| {{ site.data.keymaps.select_all }}                       | : | select / deselect all |
| {{ site.data.keymaps.deselect_all }}                     | : | deselect all |


## Control Points

The following actions apply to when the mouse is hovering over control points of selected strip.


| :--- | :--- | :--- |
| {{ site.data.keymaps.action }}      | : | grab and move control point under mouse |
| {{ site.data.keymaps.action_alt0 }} | : | grab and move all inner control points around neighboring outer control point |
| {{ site.data.keymaps.action_alt1 }} | : | scale strip width by dragging on inner control point |


## Transforming


| :--- | :--- | :--- |
| {{ site.data.keymaps.action }}  | : | grab and move selected geometry under mouse |
| {{ site.data.keymaps.grab }}    | : | grab and move selected geometry |


## Other


| :--- | :--- | :--- |
| {{ site.data.keymaps.delete }} | : | delete/dissolve/collapse selected |


## Options

Cut Count adjusts how many segments the selected PolyStrip has. The option will be greyed out if no strips are selected or if more than one strip is selected. The Cut Count can be altered for multiple strips, however, by using the hotkeys {{ site.data.keymaps.increase_count }} and {{ site.data.keymaps.decrease_count }}

Scale Falloff controls the power of the falloff curve when scaling control points. A low value (minimum 0.25) resembles Blender's smooth falloff and will scale farther segments almost as much as closer ones. A high value (maximum 4.00) resembles Blender's sharp falloff and will scale closer segments much more than those farther away. 
