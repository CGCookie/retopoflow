# ![](contours-icon.png) Contours Help

Shortcut: {{ site.data.keymaps.contours_tool }}

The Contours tool gives you a quick and easy way to retopologize cylindrical forms.
For example, it's ideal for organic forms, such as arms, legs, tentacles, tails, horns, etc.

The tool works by drawing strokes perpendicular to the form to define the contour of the shape.
Each additional stroke drawn will either extrude the current selection or cut a new loop into the edges drawn over.

You may draw strokes in any order, from any direction.

![](help_contours.png)


## Creating


| :--- | :--- | :--- |
| {{ site.data.keymaps.insert }}                           | : | draw contour stroke perpendicular to form. newly created contour extends selection if applicable. |
| {{ site.data.keymaps.increase_count }}                   | : | increase segment counts in selected loop |
| {{ site.data.keymaps.decrease_count }}                   | : | decrease segment counts in selected loop |
| {{ site.data.keymaps.fill }}                             | : | bridge selected edge loops |


## Selecting


| :--- | :--- | :--- |
| {{ site.data.keymaps.select_single }}, {{ site.data.keymaps.select_single_add }} | : | select edge |
| {{ site.data.keymaps.select_smart }}, {{ site.data.keymaps.select_smart_add }}   | : | smart select loop |
| {{ site.data.keymaps.select_paint }}, {{ site.data.keymaps.select_paint_add }}   | : | paint edge selection |
| {{ site.data.keymaps.select_path_add }}                  | : | select edges along shortest path |
| {{ site.data.keymaps.select_all }}                       | : | select / deselect all |
| {{ site.data.keymaps.deselect_all }}                     | : | deselect all |

## Transforming


| :--- | :--- | :--- |
| {{ site.data.keymaps.action }}           | : | grab and slide selected geometry under mouse |
| {{ site.data.keymaps.grab }}             | : | slide selected loop |
| {{ site.data.keymaps.rotate_plane }}     | : | rotate selected loop in plane |
| {{ site.data.keymaps.rotate_screen }}    | : | rotate selected loop in screen |
| {{ site.data.keymaps.smooth_edge_flow }} | : | smooths edge flow of selected geometry |

## Other


| :--- | :--- | :--- |
| {{ site.data.keymaps.delete }}         | : | delete/dissolve selected |

## Tips

- Extrude Contours from an existing edge loop by selecting it first.
- Contours works with symmetry, enabling you to contour torsos and other symmetrical objects!