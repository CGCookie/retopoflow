# PolyStrips Help ![](polystrips_32.png width:32px;height:32px;padding:0px)

The PolyStrips tool provides quick and easy ways to map out key face loops for complex models.
For example, if you need to retopologize a human face, creature, or any other complex organic or hard-surface object.

PolyStrips works by hand drawing strokes on to the high-resolution source object.
The strokes are instantly converted into spline-based strips of polygons.

Any continuous quad strip may be manipulated with PolyStrips via the auto-generated spline handles.

![](help_polystrips.png)

## Drawing

|  |  |  |
| --- | --- | --- |
| `Action` | : | select quad then grab and move |
| `Select` <br> `Shift+Select` | : | select quads |
| `Ctrl+Select` <br> `Ctrl+Shift+Select` | : | select quad strip |
| `Ctrl+Action` | : | draw strip of quads |
| `F` | : | adjust brush size |
| `A` | : | deselect / select all |

## Control Points

|  |  |  |
| --- | --- | --- |
| `Action` | : | translate control point under mouse |
| `Shift+Action` | : | translate all inner control points around neighboring outer control point |
| `Ctrl+Shift+Action` | : | scale strip width by click+dragging on inner control point |

## Other

|  |  |  |
| --- | --- | --- |
| `X` | : | delete/dissolve selected |
| `Shift+Up` <br> `Shift+Down` | : | increase / decrease segment count of selected strip(s) |
| `Equals` <br> `Minus` | : | increase / decrease segment count of selected strip(s) |
